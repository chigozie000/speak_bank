import asyncio
import logging

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from app.config import PUBLIC_HOSTNAME
from .services import (
    SessionHolder,
    build_voice_twiml,
    incoming_processor,
    outgoing_processor,
    parse_twilio_ws_message,
    task_processor,
)


logger = logging.getLogger("routes")
router = APIRouter()


############################ Twilio voice webhook endpoint #########################################
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
    return Response(content=str(twiml), media_type="application/xml")


############################## stream endpoint ###################################################
@router.websocket("/media")
async def media_stream(websocket: WebSocket):
    """
    Twilio's Media Streams WebSocket. This function only handles
    transport (accept, receive, send, disconnect) - all processing is
    delegated to a CallSession in services.py.
    """
    await websocket.accept()

    in_queue: asyncio.Queue = asyncio.Queue()
    out_queue: asyncio.Queue = asyncio.Queue()

    # Shared across all three tasks so that task_processor creating the
    # CallSession on the "start" event is visible to the others too.
    holder = SessionHolder()

    incoming_task = asyncio.create_task(incoming_processor(websocket, in_queue, holder))
    processing_task = asyncio.create_task(task_processor(in_queue, out_queue, holder))
    outgoing_task = asyncio.create_task(outgoing_processor(websocket, out_queue, holder))

    try:
        await incoming_task

    finally:
        processing_task.cancel()
        outgoing_task.cancel()
        await asyncio.gather(processing_task, outgoing_task, return_exceptions=True)
