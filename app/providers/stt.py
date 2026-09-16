"""
Speech-to-Text provider: Azure Cognitive Services Speech SDK.

Twilio media streams send inbound audio as base64-encoded 8kHz/16-bit
mu-law mono frames. The Azure Speech SDK wants raw PCM, so each chunk
is decoded from mu-law -> 16-bit linear PCM (via `audioop`) before
being pushed into a `PushAudioInputStream`.

Recognition is continuous and callback-driven (that's how the Azure
SDK works), so `feed_audio()` itself never returns a transcript. Call
`poll_transcript()` (non-blocking) after each `feed_audio` call to
drain any finals that arrived — see CallSession.handle_media in
services.py for the calling pattern.

Install: pip install azure-cognitiveservices-speech
"""

import audioop
import queue
from dataclasses import dataclass

import azure.cognitiveservices.speech as speechsdk

from app.config import AZURE_SPEECH_KEY, AZURE_SPEECH_LANGUAGE, AZURE_SPEECH_REGION

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
        self._recognizer.session_stopped.connect(lambda _evt: self._push_stream.close())
        self._recognizer.canceled.connect(lambda _evt: self._push_stream.close())

        self._recognizer.start_continuous_recognition_async()

    def _on_recognized(self, evt: speechsdk.SpeechRecognitionEventArgs) -> None:
        text = evt.result.text.strip()
        if text:
            self._results.put(TranscriptChunk(text=text, is_final=True))

    def feed_audio(self, audio_chunk: bytes) -> None:
        """
        Feed one inbound mu-law audio chunk from Twilio (already
        base64-decoded by the caller). Converts to 16-bit linear PCM
        and pushes it to Azure. Never blocks on a transcript — poll
        `poll_transcript()` separately.
        """
        if self._closed:
            return
        pcm16 = audioop.ulaw2lin(audio_chunk, TWILIO_SAMPLE_WIDTH)
        self._push_stream.write(pcm16)

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
        self._recognizer.stop_continuous_recognition_async()
        self._push_stream.close()
