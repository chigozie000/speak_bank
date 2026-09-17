"""
Speech-to-Text provider: Azure Cognitive Services Speech SDK.

Twilio media streams send inbound audio as base64-encoded 8kHz/16-bit
mu-law mono frames. The Azure Speech SDK wants raw PCM, so each chunk
is decoded from mu-law -> 16-bit linear PCM (via `audioop`) before
being pushed into a `PushAudioInputStream`.

Recognition is continuous and callback-driven (that's how the Azure
SDK works), so `feed_audio_nowait()` itself never returns a transcript.
Call `poll_transcript()` (non-blocking) after each `feed_audio_nowait`
call to drain any finals that arrived — see CallSession.handle_media in
services.py for the calling pattern.

Install: pip install azure-cognitiveservices-speech
"""

import audioop
import logging
import queue
import threading
from dataclasses import dataclass

import azure.cognitiveservices.speech as speechsdk

from app.config import AZURE_SPEECH_KEY, AZURE_SPEECH_LANGUAGE, AZURE_SPEECH_REGION

logger = logging.getLogger("stt")

# Twilio media streams are 8kHz mu-law mono.
TWILIO_SAMPLE_RATE = 8000
TWILIO_SAMPLE_WIDTH = 2  # bytes per sample once decoded to linear PCM


@dataclass
class TranscriptChunk:
    text: str
    is_final: bool


class AzureSTTSession:
    """Per-call STT session backed by Azure Speech continuous recognition."""

    def __init__(self, call_sid: str):
        self.call_sid = call_sid
        self._results: "queue.Queue[TranscriptChunk]" = queue.Queue()
        self._closed = False

        if not AZURE_SPEECH_KEY or not AZURE_SPEECH_REGION:
            raise RuntimeError(
                "AZURE_SPEECH_KEY / AZURE_SPEECH_REGION are not configured."
            )

        speech_config = speechsdk.SpeechConfig(
            subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION
        )
        speech_config.speech_recognition_language = AZURE_SPEECH_LANGUAGE

        stream_format = speechsdk.audio.AudioStreamFormat(
            samples_per_second=TWILIO_SAMPLE_RATE,
            bits_per_sample=16,
            channels=1,
        )
        self._push_stream = speechsdk.audio.PushAudioInputStream(stream_format)
        audio_config = speechsdk.audio.AudioConfig(stream=self._push_stream)

        self._recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config, audio_config=audio_config
        )
        self._recognizer.recognized.connect(self._on_recognized)
        self._recognizer.speech_start_detected.connect(
            lambda evt: logger.debug("Speech started: call=%s", self.call_sid)
        )
        self._recognizer.speech_end_detected.connect(self._on_speech_end)
        self._recognizer.session_started.connect(
            lambda evt: logger.info("Azure STT session started: call=%s session=%s", self.call_sid, evt.session_id)
        )
        self._recognizer.session_stopped.connect(self._on_session_stopped)
        self._recognizer.canceled.connect(self._on_canceled)

        self._recognizer.start_continuous_recognition_async()

        # Audio arrives on the event loop thread (~50 frames/sec, one
        # every 20ms). PushAudioInputStream.write() is normally fast,
        # but if the recognizer's consumer ever stalls (e.g. right
        # after a silent cancellation) it can start blocking — and a
        # blocking call from task_processor freezes the whole event
        # loop. So writes go through a small queue drained by a
        # dedicated thread instead of happening inline.
        self._write_queue: "queue.Queue[bytes | None]" = queue.Queue()
        self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer_thread.start()

    def _on_recognized(self, evt: speechsdk.SpeechRecognitionEventArgs) -> None:
        # This is the actual "pause of speech -> transcript" moment:
        # Azure's own VAD/endpointer decided the caller stopped
        # talking and finalized what it heard into evt.result.text.
        text = evt.result.text.strip()
        if text:
            self._results.put(TranscriptChunk(text=text, is_final=True))

    def _on_speech_end(self, evt) -> None:
        # Fires the instant Azure's VAD detects the caller went quiet
        # — slightly before the recognized event above delivers the
        # actual transcribed text for that pause.
        logger.debug("Speech ended (pause detected): call=%s", self.call_sid)

    def _on_session_stopped(self, evt) -> None:
        logger.info("Azure STT session stopped: call=%s", self.call_sid)
        self._push_stream.close()

    def _on_canceled(self, evt: speechsdk.SpeechRecognitionCanceledEventArgs) -> None:
        # This is the important one: without logging here, a bad region,
        # a rejected/expired key, or a dropped connection all fail
        # *silently* — poll_transcript() just returns None forever and
        # the call looks "stuck" with no error anywhere.
        details = evt.cancellation_details
        logger.error(
            "Azure STT canceled: call=%s reason=%s error_code=%s details=%s",
            self.call_sid,
            details.reason,
            getattr(details, "error_code", None),
            details.error_details,
        )
        self._push_stream.close()

    def _writer_loop(self) -> None:
        while True:
            chunk = self._write_queue.get()
            if chunk is None:  # shutdown sentinel
                return
            try:
                self._push_stream.write(chunk)
            except Exception:
                logger.exception("Azure STT push_stream.write failed for call %s", self.call_sid)
                return

    def feed_audio_nowait(self, audio_chunk: bytes) -> None:
        """
        Feed one inbound mu-law audio chunk from Twilio (already
        base64-decoded by the caller). Converts to 16-bit linear PCM
        and hands it to the writer thread — this call itself never
        blocks, regardless of what the SDK's write() is doing. Never
        blocks on a transcript either — poll `poll_transcript()`
        separately.
        """
        if self._closed:
            return
        pcm16 = audioop.ulaw2lin(audio_chunk, TWILIO_SAMPLE_WIDTH)
        self._write_queue.put(pcm16)

    def poll_transcript(self) -> TranscriptChunk | None:
        """Non-blocking: returns the next finalized transcript chunk, if any."""
        try:
            return self._results.get_nowait()
        except queue.Empty:
            return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._write_queue.put(None)
        self._recognizer.stop_continuous_recognition_async()
        self._push_stream.close()
