"""
Services layer.

routes.py owns the HTTP/WebSocket transport (Twilio-facing contract).
This module owns all the actual processing: turning inbound audio into
a transcript, turning the transcript into a reply, and turning the
reply into outbound audio. routes.py should stay thin and just call
into here.
"""

import base64
import json
import logging

from app.providers.llm import generate_reply
from app.providers.stt import StubSTTSession
from app.providers.tts import synthesize_to_frames

logger = logging.getLogger("services")


def build_voice_twiml(stream_url: str) -> str:
    """Return the TwiML instructing Twilio to open a media stream."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>Connecting you to your banking assistant.</Say>
    <Connect>
        <Stream url="{stream_url}" />
    </Connect>
</Response>"""


class CallSession:
    """
    Holds all per-call state and processes one call's media stream.
    One instance is created per WebSocket connection in routes.py.
    """

    def __init__(self, call_sid: str, caller_number: str = "default"):
        self.call_sid = call_sid
        self.caller_number = caller_number
        self.stream_sid: str | None = None
        self.history: list[dict] = []
        self.stt = StubSTTSession(call_sid)

    def handle_start(self, start_data: dict) -> None:
        self.stream_sid = start_data.get("streamSid")
        self.caller_number = start_data.get("customParameters", {}).get(
            "caller", self.caller_number
        )
        logger.info("Call started: sid=%s stream=%s", self.call_sid, self.stream_sid)

    def handle_media(self, payload_b64: str) -> str | None:
        """
        Process one inbound audio frame (base64 mu-law from Twilio).
        Returns the assistant's reply text if a full turn was just
        completed, else None.
        """
        audio_chunk = base64.b64decode(payload_b64)
        chunk = self.stt.feed_audio(audio_chunk)

        if chunk is None or not chunk.is_final:
            return None

        logger.info("Caller said: %s", chunk.text)
        self.history.append({"role": "user", "content": chunk.text})

        reply = generate_reply(self.caller_number, chunk.text, self.history)
        self.history.append({"role": "assistant", "content": reply})
        logger.info("Assistant reply: %s", reply)
        return reply

    def build_outbound_frames(self, reply_text: str) -> list[dict]:
        """
        Turn a reply string into the list of Twilio "media" WS messages
        ready to send back over the same connection.
        """
        audio_frames = synthesize_to_frames(reply_text)
        messages = []
        for frame_b64 in audio_frames:
            messages.append(
                {
                    "event": "media",
                    "streamSid": self.stream_sid,
                    "media": {"payload": frame_b64},
                }
            )
        return messages

    def handle_stop(self) -> None:
        logger.info("Call ended: sid=%s", self.call_sid)


def parse_twilio_ws_message(raw_message: str) -> dict:
    """Parse a raw Twilio Media Streams WebSocket text frame into a dict."""
    return json.loads(raw_message)
