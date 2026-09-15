"""
Text-to-Speech provider.

Prototype stub: does NOT synthesize real speech. It generates silent
mu-law audio frames of a plausible length so the Twilio media-stream
loop (and your frame-sending code) can be tested end to end before you
wire in a real TTS engine.

Real integration sketch (ElevenLabs streaming, for example):
  - POST to ElevenLabs streaming endpoint requesting mulaw_8000 output
    (or resample from whatever format it returns).
  - Chunk the returned audio into ~20ms frames, base64-encode each,
    and send them as Twilio "media" websocket messages.
"""

import base64

MULAW_SILENCE_BYTE = b"\xff"  # mu-law encoded silence
FRAME_MS = 20
SAMPLE_RATE = 8000
BYTES_PER_FRAME = int(SAMPLE_RATE * FRAME_MS / 1000)  # 160 bytes/frame


def synthesize_to_frames(text: str) -> list[str]:
    """
    Return a list of base64-encoded mu-law audio frames representing the
    spoken `text`. Stub: silent audio, duration scaled to text length so
    timing feels roughly plausible.
    """
    approx_ms = max(500, len(text) * 60)  # crude "reading speed" estimate
    frame_count = approx_ms // FRAME_MS

    silent_frame = MULAW_SILENCE_BYTE * BYTES_PER_FRAME
    encoded_frame = base64.b64encode(silent_frame).decode("ascii")

    return [encoded_frame for _ in range(frame_count)]
