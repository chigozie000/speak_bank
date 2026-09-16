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

from twilio.twiml.voice_response import VoiceResponse, Connect

from asyncio import Queue

from fastapi import WebSocket, WebSocketDisconnect

from app.providers.llm import generate_reply
from app.providers.stt import StubSTTSession
from app.providers.tts import synthesize_to_frames


logger = logging.getLogger("services")



def build_voice_twiml(stream_url: str) -> VoiceResponse:
    """Return the TwiML instructing Twilio to open a media stream."""
    resp=VoiceResponse()
    resp.say('Hello,  Welcome to SpeakBank!')
    resp.say('Am your customer care Ai agent.')
    resp.say("you can speak to us in English, Igbo, Hausa and Yoruba.")
    resp.say("kindly wait......")

    connect= Connect()
    connect.stream(url=stream_url)

    resp.append(connect)

    return resp



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




async def incoming_procerssor(websocket:WebSocket, in_queue:Queue, session:CallSession):
    """maintain connection, 
        recieves task fro the routes, 
        parses the test to json, and queue in in_queue.
    """
    try:
        while True:
            raw_message = await websocket.receive_text()
            data = parse_twilio_ws_message(raw_message)
            await in_queue.put(data)

    except WebSocketDisconnect:
        print("disconnected")

    finally:
        if session:
            session.handle_stop()



async def task_procerssor(in_queue:Queue, out_queue:Queue, session:CallSession):
    """
        get task from in queue and extract the event of the streamed data,
        processes individual events---start, media and stop
        for media it takes our audio to STT and  to LLM and finally to Bank backend --> LLM
        queues the responds of bank in out_queue
    """
    while True:
        data= await in_queue.get()
        event = data.get("event")

        if event == "start":
            start_data = data["start"]
            session = CallSession(call_sid=start_data.get("callSid", "unknown"))
            session.handle_start(start_data)

        elif event == "media" and session is not None:
            reply_text = session.handle_media(data["media"]["payload"])
            await out_queue.put(reply_text)
    
        elif event == "stop" and session is not None:
            session.handle_stop()
            break



async def outgoing_procerssor(websocket:WebSocket, out_queue, session:CallSession):
    """
        takes reply from out_que and build and outbound frame,
        then stream back to twilio.
    """
    reply_text= out_queue.get()
    if reply_text:
        for frame_message in session.build_outbound_frames(reply_text):
            await websocket.send_json(frame_message)








