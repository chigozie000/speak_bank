import logging

import asyncio

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response


from app.config import PUBLIC_HOSTNAME
from .services import CallSession, build_voice_twiml, incoming_procerssor, task_procerssor, outgoing_procerssor, parse_twilio_ws_message


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







##############################stream endpoint####################################################################
@router.websocket("/media")
async def media_stream(websocket: WebSocket):
    """
    Twilio's Media Streams WebSocket. This function only handles
    transport (accept, receive, send, disconnect) - all processing is
    delegated to a CallSession in services.py.
    """
    await websocket.accept()
    session: CallSession | None = None

    in_queue= asyncio.Queue()
    out_queue= asyncio.Queue()

    incomming_task= asyncio.create_task(incoming_procerssor(websocket, in_queue, session))
    processiong_task= asyncio.create_task(task_procerssor(in_queue, out_queue, session))
    outgoing_task= asyncio.create_task(outgoing_procerssor(websocket, out_queue, session))

    try:
        gathered=asyncio.gather(incomming_task,processiong_task, outgoing_task)
    finally:
        gathered.cancel()

