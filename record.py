import asyncio
import base64
import json
import sys

import sounddevice as sd
import audioop
import websockets


# =========================
# CONFIG
# =========================

WS_URL = "ws://localhost:8000/media"

# Twilio Media Streams audio format
SAMPLE_RATE = 8000
CHANNELS = 1

# 20 ms of audio = 160 samples at 8 kHz
CHUNK_SAMPLES = 160

# Change this to your microphone device ID.
# Use None for the Windows default microphone.
DEVICE = None


# =========================
# AUDIO QUEUE
# =========================

audio_queue = asyncio.Queue(maxsize=50)


def microphone_callback(indata, frames, time_info, status):
    """
    Called by PortAudio from the microphone thread.
    """

    if status:
        print("Audio status:", status, file=sys.stderr)

    # sounddevice gives us signed 16-bit PCM.
    pcm = bytes(indata)

    try:
        audio_queue.put_nowait(pcm)
    except asyncio.QueueFull:
        # Drop oldest audio rather than allowing latency
        # to grow indefinitely.
        try:
            audio_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass

        try:
            audio_queue.put_nowait(pcm)
        except asyncio.QueueFull:
            pass


async def send_audio(ws):
    """
    Convert microphone PCM -> μ-law -> base64
    and send Twilio-style media messages.
    """

    while True:
        pcm = await audio_queue.get()

        # Convert signed 16-bit PCM to μ-law.
        mulaw = audioop.lin2ulaw(pcm, 2)

        payload = base64.b64encode(mulaw).decode("ascii")

        message = {
            "event": "media",
            "streamSid": "MZ_TEST_STREAM",
            "media": {
                "track": "inbound",
                "chunk": "0",
                "timestamp": "0",
                "payload": payload,
            },
        }

        await ws.send(json.dumps(message))


async def main():

    print("Connecting to:", WS_URL)

    async with websockets.connect(
        WS_URL,
        ping_interval=20,
        ping_timeout=20,
        max_size=None,
    ) as ws:

        print("Connected!")

        # Simulate Twilio's connected event.
        await ws.send(json.dumps({
            "event": "connected",
            "protocol": "Call",
            "version": "1.0"
        }))

        # Simulate Twilio's start event.
        await ws.send(json.dumps({
            "event": "start",
            "sequenceNumber": "1",
            "start": {
                "accountSid": "TEST_ACCOUNT",
                "callSid": "CA_TEST_CALL",
                "streamSid": "MZ_TEST_STREAM",
                "tracks": ["inbound"],
                "mediaFormat": {
                    "encoding": "audio/x-mulaw",
                    "sampleRate": 8000,
                    "channels": 1
                }
            },
            "streamSid": "MZ_TEST_STREAM"
        }))

        print("Microphone streaming started.")
        print("Speak into your laptop microphone.")
        print("Press Ctrl+C to stop.")

        sender = asyncio.create_task(send_audio(ws))

        try:

            with sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                blocksize=CHUNK_SAMPLES,
                device=DEVICE,
                channels=CHANNELS,
                dtype="int16",
                callback=microphone_callback,
            ):

                while True:
                    await asyncio.sleep(1)

        except KeyboardInterrupt:
            print("\nStopping...")

        finally:

            sender.cancel()

            # Simulate Twilio stop event.
            await ws.send(json.dumps({
                "event": "stop",
                "sequenceNumber": "999",
                "stop": {
                    "accountSid": "TEST_ACCOUNT",
                    "callSid": "CA_TEST_CALL"
                },
                "streamSid": "MZ_TEST_STREAM"
            }))


if __name__ == "__main__":
    asyncio.run(main())