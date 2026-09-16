"""
Text-to-Speech provider: OpenAI TTS.

OpenAI's TTS endpoint returns 24kHz/16-bit linear PCM audio when asked
for `response_format="pcm"`. Twilio media streams want 8kHz/16-bit
mu-law mono, 20ms frames, base64-encoded. So the pipeline here is:

  OpenAI PCM (24kHz, 16-bit) -> resample to 8kHz -> mu-law encode
  -> split into 160-byte (20ms) frames -> base64 each frame

Install: pip install openai
"""

import audioop
import base64

from openai import OpenAI

from app.config import OPENAI_API_KEY, OPENAI_TTS_MODEL, OPENAI_TTS_VOICE

OPENAI_PCM_SAMPLE_RATE = 24000
TWILIO_SAMPLE_RATE = 8000
SAMPLE_WIDTH = 2  # bytes per sample (16-bit)

FRAME_MS = 20
BYTES_PER_FRAME = int(TWILIO_SAMPLE_RATE * FRAME_MS / 1000)  # 160 bytes/frame (mu-law, 1 byte/sample)

_client = OpenAI(api_key=OPENAI_API_KEY)


def _pcm24k_to_mulaw8k(pcm_bytes: bytes) -> bytes:
    """Resample 24kHz/16-bit PCM down to 8kHz, then mu-law encode it."""
    pcm_8k, _ = audioop.ratecv(
        pcm_bytes, SAMPLE_WIDTH, 1, OPENAI_PCM_SAMPLE_RATE, TWILIO_SAMPLE_RATE, None
    )
    return audioop.lin2ulaw(pcm_8k, SAMPLE_WIDTH)


def synthesize_to_frames(text: str) -> list[str]:
    """
    Synthesize `text` with OpenAI TTS and return a list of
    base64-encoded mu-law/8kHz/20ms frames, ready to send as Twilio
    "media" websocket messages.
    """
    with _client.audio.speech.with_streaming_response.create(
        model=OPENAI_TTS_MODEL,
        voice=OPENAI_TTS_VOICE,
        input=text,
        response_format="pcm",
    ) as response:
        pcm_bytes = b"".join(response.iter_bytes())

    mulaw_bytes = _pcm24k_to_mulaw8k(pcm_bytes)

    frames = []
    for i in range(0, len(mulaw_bytes), BYTES_PER_FRAME):
        chunk = mulaw_bytes[i : i + BYTES_PER_FRAME]
        if len(chunk) < BYTES_PER_FRAME:
            # Pad the final short frame with mu-law silence so Twilio
            # always receives full 20ms frames.
            chunk += b"\xff" * (BYTES_PER_FRAME - len(chunk))
        frames.append(base64.b64encode(chunk).decode("ascii"))

    return frames
