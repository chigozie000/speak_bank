"""
Speech-to-Text provider.

Prototype stub: does NOT actually transcribe audio. It just proves the
pipeline works end to end. Swap this out for a real streaming STT
(Deepgram, AssemblyAI, Whisper streaming, etc.) when you're ready.

Real integration sketch (Deepgram streaming, for example):
  - Open a Deepgram websocket per call when the Twilio stream starts.
  - Forward each inbound base64 mu-law audio chunk to Deepgram as-is
    (Deepgram accepts mulaw/8000 directly).
  - Deepgram sends back partial/final transcripts on its own websocket;
    push finals into the same turn-handling logic used below.
"""

from dataclasses import dataclass


@dataclass
class TranscriptChunk:
    text: str
    is_final: bool


class StubSTTSession:
    """Per-call STT session. Accumulates audio chunks and fakes a transcript."""

    def __init__(self, call_sid: str):
        self.call_sid = call_sid
        self._chunk_count = 0

    def feed_audio(self, audio_chunk: bytes) -> TranscriptChunk | None:
        """
        Feed one inbound audio frame from Twilio.
        Returns a TranscriptChunk when a "turn" is detected (stubbed here
        as every N chunks), or None otherwise.
        """
        self._chunk_count += 1

        # Stub heuristic: pretend the caller finished speaking every
        # ~100 frames (~2s at 20ms/frame). Replace with real VAD /
        # provider-driven endpointing.
        if self._chunk_count % 100 == 0:
            return TranscriptChunk(text="What's my account balance?", is_final=True)

        return None
