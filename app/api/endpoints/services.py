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

from asyncio import Queue

from fastapi import WebSocket, WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect

from app.providers.llm import generate_reply
from app.providers.stt import AzureSTTSession
from app.providers.tts import synthesize_to_frames


logger = logging.getLogger("services")


def build_voice_twiml(stream_url: str) -> VoiceResponse:
    """Return the TwiML instructing Twilio to open a media stream."""
    resp = VoiceResponse()
    resp.say("Hello, Welcome to SpeakBank!")
    resp.say("I'm your customer care AI agent.")
    resp.say("You can speak to us in English, Igbo, Hausa and Yoruba.")
    resp.say("Kindly wait...")

    connect = Connect()
    connect.stream(url=stream_url)
    resp.append(connect)

    return resp


class CallSession:
    """
    Holds all per-call state and processes one call's media stream.
    One instance is created per WebSocket connection, on the Twilio
    "start" event (see task_processor below).
    """

    def __init__(self, call_sid: str, caller_number: str = "default"):
        self.call_sid = call_sid
        self.caller_number = caller_number
        self.stream_sid: str | None = None
        self.history: list[dict] = []
        self.stt = AzureSTTSession(call_sid)

    def handle_start(self, start_data: dict) -> None:
        self.stream_sid = start_data.get("streamSid")
        self.caller_number = start_data.get("customParameters", {}).get(
            "caller", self.caller_number
        )
        logger.info("Call started: sid=%s stream=%s", self.call_sid, self.stream_sid)

    def handle_media(self, payload_b64: str) -> str | None:
        """
        Process one inbound audio frame (base64 mu-law from Twilio).
        Azure STT recognition is callback-driven, so we feed the audio
        in, then poll for whatever transcript (if any) has finalized
        so far. Returns the assistant's reply text if a full turn was
        just completed, else None.
        """
        audio_chunk = base64.b64decode(payload_b64)
        self.stt.feed_audio(audio_chunk)

        chunk = self.stt.poll_transcript()
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
        return [
            {
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {"payload": frame_b64},
            }
            for frame_b64 in audio_frames
        ]

    def handle_stop(self) -> None:
        logger.info("Call ended: sid=%s", self.call_sid)
        self.stt.close()


def parse_twilio_ws_message(raw_message: str) -> dict:
    """Parse a raw Twilio Media Streams WebSocket text frame into a dict."""
    return json.loads(raw_message)


class SessionHolder:
    """
    A mutable box for the current call's CallSession.

    The session doesn't exist until the "start" event arrives, and it's
    created inside task_processor. incoming_processor and
    outgoing_processor run as separate concurrent tasks, so they can't
    just receive `session` as a plain argument — reassigning a local
    variable in one coroutine doesn't change what another coroutine
    sees. All three tasks share one SessionHolder instance instead, so
    once task_processor sets `holder.session`, the others see it too.
    """

    def __init__(self):
        self.session: CallSession | None = None


async def incoming_processor(websocket: WebSocket, in_queue: Queue, holder: SessionHolder):
    """
    Maintains the inbound side of the connection: receives raw text
    frames from Twilio, parses them to JSON, and queues them for
    task_processor.
    """
    try:
        while True:
            raw_message = await websocket.receive_text()
            data = parse_twilio_ws_message(raw_message)
            await in_queue.put(data)

    except WebSocketDisconnect:
        logger.info("Twilio websocket disconnected")

    finally:
        if holder.session:
            holder.session.handle_stop()


async def task_processor(in_queue: Queue, out_queue: Queue, holder: SessionHolder):
    """
    Pulls parsed Twilio events off in_queue and dispatches by event
    type ("start", "media", "stop"). For "media" it runs audio through
    STT -> LLM and queues any completed reply onto out_queue.
    """
    while True:
        data = await in_queue.get()
        event = data.get("event")

        if event == "start":
            start_data = data["start"]
            logger.debug("start data: %s", start_data)
            holder.session = CallSession(call_sid=start_data.get("callSid", "unknown"))
            holder.session.handle_start(start_data)

        elif event == "media" and holder.session is not None:
            reply_text = holder.session.handle_media(data["media"]["payload"])
            if reply_text:
                await out_queue.put(reply_text)

        elif event == "stop" and holder.session is not None:
            logger.debug("stop data: %s", data.get("stop"))
            holder.session.handle_stop()
            break


async def outgoing_processor(websocket: WebSocket, out_queue: Queue, holder: SessionHolder):
    """
    Pulls completed replies off out_queue, turns each into outbound
    Twilio media frames, and streams them back over the websocket.
    Runs for the lifetime of the call, not just one reply.
    """
    while True:
        reply_text = await out_queue.get()
        if reply_text and holder.session:
            for frame_message in holder.session.build_outbound_frames(reply_text):
                await websocket.send_json(frame_message)
