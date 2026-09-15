import logging

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from app.config import PUBLIC_HOSTNAME
from app.services import CallSession, build_voice_twiml, parse_twilio_ws_message

logger = logging.getLogger("routes")
router = APIRouter()


@router.post("/voice")
async def voice_webhook(request: Request):
    """
    Twilio calls this when a call comes in. We just return TwiML
    telling it to open a Media Stream WebSocket back to us.
    """
    form = await request.form()
    caller_number = form.get("From", "default")
    logger.info("Incoming call from %s", caller_number)

    stream_url = f"wss://{PUBLIC_HOSTNAME}/media"
    twiml = build_voice_twiml(stream_url)
    return Response(content=twiml, media_type="application/xml")


@router.websocket("/media")
async def media_stream(websocket: WebSocket):
    """
    Twilio's Media Streams WebSocket. This function only handles
    transport (accept, receive, send, disconnect) - all processing is
    delegated to a CallSession in services.py.
    """
    await websocket.accept()
    session: CallSession | None = None

    try:
        while True:
            raw_message = await websocket.receive_text()
            data = parse_twilio_ws_message(raw_message)
            event = data.get("event")

            if event == "start":
                start_data = data["start"]
                session = CallSession(call_sid=start_data.get("callSid", "unknown"))
                session.handle_start(start_data)

            elif event == "media" and session is not None:
                reply_text = session.handle_media(data["media"]["payload"])
                if reply_text:
                    for frame_message in session.build_outbound_frames(reply_text):
                        await websocket.send_json(frame_message)

            elif event == "stop" and session is not None:
                session.handle_stop()
                break

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    finally:
        if session:
            session.handle_stop()
