"""
Call simulator — a local test client for the /media WebSocket.

Speaks the exact same Twilio Media Streams JSON protocol that
app/api/endpoints/routes.py and services.py expect ("connected" ->
"start" -> repeated "media" -> "stop"), so it exercises the real
STT -> LLM -> TTS pipeline without needing an actual Twilio call.

Two input modes:
  --mic          stream live microphone audio (Ctrl+C to stop)
  --wav FILE     stream a .wav file, paced at real-time (20ms/frame)

Any audio the server streams back (the assistant's TTS replies) is
played through your speakers as it arrives.

Audio path:
  mic/wav (any rate, mono/stereo, 16-bit)
    -> resampled to 8kHz mono PCM16          [audioop.ratecv]
    -> mu-law encoded, 160-byte/20ms frames    [audioop.lin2ulaw]
    -> base64 -> "media" WS message

  server "media" message (base64 mu-law/8kHz)
    -> mu-law decoded to PCM16                 [audioop.ulaw2lin]
    -> resampled to the output device rate     [audioop.ratecv]
    -> played via sounddevice

Install:
    pip install -r client/requirements.txt

Usage:
    python client/call_simulator.py --url ws://localhost:8000/media --mic
    python client/call_simulator.py --url ws://localhost:8000/media --wav sample.wav
"""

import argparse
import asyncio
import base64
import json
import queue
import sys
import threading
import uuid
import wave

# audioop was removed from the stdlib in Python 3.13; `audioop-lts`
# (see client/requirements.txt) reinstates it as a drop-in "audioop"
# module, so this import works unchanged on older and newer Pythons.
import audioop

import sounddevice as sd
import websockets

SAMPLE_RATE = 8000        # what the backend/Twilio expect
SAMPLE_WIDTH = 2          # 16-bit PCM
FRAME_MS = 20
FRAME_BYTES = int(SAMPLE_RATE * FRAME_MS / 1000) * SAMPLE_WIDTH  # 320 bytes = 160 samples

MIC_CAPTURE_RATE = 16000  # a rate real audio devices reliably support
PLAYBACK_RATE = 16000     # upsample 8kHz server audio to this for output


def pcm_to_mulaw_b64(pcm_chunk: bytes) -> str:
    """Mu-law encode a linear PCM16 chunk and base64 it for the wire."""
    return base64.b64encode(audioop.lin2ulaw(pcm_chunk, SAMPLE_WIDTH)).decode("ascii")


def make_ids() -> tuple[str, str]:
    stream_sid = f"MZ{uuid.uuid4().hex[:32]}"
    call_sid = f"CA{uuid.uuid4().hex[:32]}"
    return stream_sid, call_sid


# --------------------------------------------------------------------------
# Outgoing audio sources
# --------------------------------------------------------------------------

def mic_frame_source(stop_event: threading.Event) -> "queue.Queue[bytes | None]":
    """
    Starts capturing from the default microphone in the background and
    returns a thread-safe queue that yields 20ms/8kHz/mono/16-bit PCM
    frames (already resampled down from MIC_CAPTURE_RATE), terminated
    by a single `None` once stop_event is set.
    """
    frame_q: "queue.Queue[bytes | None]" = queue.Queue()
    resample_state = None
    leftover = b""

    def callback(indata, frames, time_info, status):
        nonlocal resample_state, leftover
        if status:
            print(f"[mic] {status}", file=sys.stderr)
        pcm_8k, resample_state = audioop.ratecv(
            bytes(indata), SAMPLE_WIDTH, 1, MIC_CAPTURE_RATE, SAMPLE_RATE, resample_state
        )
        buf = leftover + pcm_8k
        offset = 0
        while offset + FRAME_BYTES <= len(buf):
            frame_q.put(buf[offset : offset + FRAME_BYTES])
            offset += FRAME_BYTES
        leftover = buf[offset:]

    stream = sd.RawInputStream(
        samplerate=MIC_CAPTURE_RATE,
        channels=1,
        dtype="int16",
        callback=callback,
        blocksize=int(MIC_CAPTURE_RATE * FRAME_MS / 1000),
    )
    stream.start()

    def watcher():
        stop_event.wait()
        stream.stop()
        stream.close()
        frame_q.put(None)

    threading.Thread(target=watcher, daemon=True).start()
    return frame_q


def wav_frames(path: str):
    """Yield 20ms/8kHz/mono/16-bit PCM frames read from a .wav file."""
    with wave.open(path, "rb") as wf:
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())

    if sampwidth != SAMPLE_WIDTH:
        raw = audioop.lin2lin(raw, sampwidth, SAMPLE_WIDTH)
    if channels == 2:
        raw = audioop.tomono(raw, SAMPLE_WIDTH, 0.5, 0.5)
    elif channels > 2:
        raise ValueError(f"unsupported channel count: {channels}")

    if framerate != SAMPLE_RATE:
        raw, _ = audioop.ratecv(raw, SAMPLE_WIDTH, 1, framerate, SAMPLE_RATE, None)

    for offset in range(0, len(raw), FRAME_BYTES):
        chunk = raw[offset : offset + FRAME_BYTES]
        if len(chunk) < FRAME_BYTES:
            chunk += b"\x00" * (FRAME_BYTES - len(chunk))
        yield chunk


# --------------------------------------------------------------------------
# Playback of the server's TTS replies
# --------------------------------------------------------------------------

class Player:
    """Plays back 8kHz mu-law frames received from the server, live."""

    def __init__(self):
        self._q: "queue.Queue[bytes]" = queue.Queue()
        self._resample_state = None
        self._stream = sd.RawOutputStream(
            samplerate=PLAYBACK_RATE, channels=1, dtype="int16"
        )
        self._stream.start()

    def push(self, mulaw_payload_b64: str) -> None:
        mulaw = base64.b64decode(mulaw_payload_b64)
        pcm_8k = audioop.ulaw2lin(mulaw, SAMPLE_WIDTH)
        pcm_out, self._resample_state = audioop.ratecv(
            pcm_8k, SAMPLE_WIDTH, 1, SAMPLE_RATE, PLAYBACK_RATE, self._resample_state
        )
        self._stream.write(pcm_out)

    def close(self) -> None:
        self._stream.stop()
        self._stream.close()


# --------------------------------------------------------------------------
# Main protocol driver
# --------------------------------------------------------------------------

async def run(url: str, caller: str, wav_path: str | None, mic: bool, seconds: float | None):
    stream_sid, call_sid = make_ids()
    print(f"Connecting to {url} ...")

    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        await ws.send(
            json.dumps(
                {
                    "event": "start",
                    "start": {
                        "streamSid": stream_sid,
                        "callSid": call_sid,
                        "customParameters": {"caller": caller},
                    },
                }
            )
        )
        print(f"Call started: callSid={call_sid} streamSid={stream_sid}")

        player = Player()

        async def receiver():
            try:
                async for raw in ws:
                    data = json.loads(raw)
                    if data.get("event") == "media":
                        player.push(data["media"]["payload"])
                    elif data.get("event") == "mark":
                        pass
            except websockets.ConnectionClosed:
                pass

        recv_task = asyncio.create_task(receiver())

        try:
            if wav_path:
                for frame in wav_frames(wav_path):
                    await ws.send(
                        json.dumps(
                            {
                                "event": "media",
                                "streamSid": stream_sid,
                                "media": {"payload": pcm_to_mulaw_b64(frame)},
                            }
                        )
                    )
                    await asyncio.sleep(FRAME_MS / 1000)
            elif mic:
                stop_event = threading.Event()
                frame_q = mic_frame_source(stop_event)
                print("Recording from microphone — press Ctrl+C to stop.")
                loop = asyncio.get_running_loop()
                start = loop.time()
                try:
                    while seconds is None or (loop.time() - start) < seconds:
                        frame = await asyncio.to_thread(frame_q.get)
                        if frame is None:
                            break
                        await ws.send(
                            json.dumps(
                                {
                                    "event": "media",
                                    "streamSid": stream_sid,
                                    "media": {"payload": pcm_to_mulaw_b64(frame)},
                                }
                            )
                        )
                except KeyboardInterrupt:
                    pass
                finally:
                    stop_event.set()

            # Give the server a moment to send any final reply audio
            # before we tear the connection down.
            await asyncio.sleep(1.5)

        finally:
            await ws.send(
                json.dumps({"event": "stop", "stop": {"callSid": call_sid, "streamSid": stream_sid}})
            )
            recv_task.cancel()
            player.close()

    print("Call ended.")


def main():
    parser = argparse.ArgumentParser(description="Simulate a Twilio call against the /media WebSocket.")
    parser.add_argument("--url", default="ws://localhost:8000/media", help="WebSocket URL of the /media endpoint")
    parser.add_argument("--caller", default="default", help="Caller number to pass as customParameters.caller")
    parser.add_argument("--wav", default=None, help="Path to a .wav file to stream instead of the microphone")
    parser.add_argument("--mic", action="store_true", help="Stream live microphone audio")
    parser.add_argument("--seconds", type=float, default=None, help="Stop mic capture after N seconds")
    args = parser.parse_args()

    if not args.wav and not args.mic:
        parser.error("pass either --mic or --wav FILE")

    try:
        asyncio.run(run(args.url, args.caller, args.wav, args.mic, args.seconds))
    except KeyboardInterrupt:
        print("\nInterrupted.")


if __name__ == "__main__":
    main()
