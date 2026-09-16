# AI Phone Banking — Prototype

Minimal Twilio + FastAPI WebSocket prototype for an AI phone banking assistant.

## Architecture

```
Caller → Twilio number → POST /voice  (routes.py → services.build_voice_twiml)
                              ↓ returns TwiML <Connect><Stream>
                          Twilio opens WS → /media  (routes.py)
                              ↓ each frame delegated to
                          services.CallSession  (STT → LLM → TTS)
                              ↓ reply frames sent back over same WS
                          Twilio plays audio to caller
```

**Route split** (as requested):
- `app/api/endpoint/routes.py` — transport only. Accepts the Twilio webhook / WebSocket,
  parses messages, sends responses. No business logic.
- `app/api/endpoint/services.py` — all processing. `CallSession` owns per-call state and
  orchestrates STT → LLM → TTS.
- `app/providers/` — swappable stubs for `stt.py`, `llm.py`, `tts.py`. Each
  file has a comment showing how to wire in a real provider (Deepgram,
  Claude/GPT, ElevenLabs, etc.)

## Current state (prototype)

Everything runs with **stubbed** STT/TTS so you can prove the plumbing works
without any API keys:
- STT: fakes a transcript ("What's my account balance?") every ~2s of audio.
- LLM: simple keyword matching over mock account data (no real API call).
- TTS: generates silent audio frames of a plausible duration.

This lets you confirm the full loop — Twilio → FastAPI → reply → Twilio —
before wiring in real providers.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in values as you add real providers
```

## Run locally

```bash
uvicorn app.main:app --reload --port 8000
```

Expose it publicly (Twilio needs a public URL):

```bash
ngrok http 8000
```

Copy the ngrok hostname (no `https://`, no trailing slash) into `.env` as
`PUBLIC_HOSTNAME`.

## Wire up Twilio

1. Buy/use a Twilio phone number.
2. In the Twilio console, set the number's "A call comes in" webhook to:
   `https://<your-ngrok-hostname>/voice` (HTTP POST).
3. Call the number. You should see logs in your terminal:
   - "Incoming call from ..."
   - "Call started: sid=..."
   - "Caller said: What's my account balance?" (after ~2s, from the stub)
   - "Assistant reply: Your current balance is $1,245.30."
4. The caller will hear silence during the "reply" (stubbed TTS) — that's
   expected until you plug in a real TTS provider.

## Next steps to make it real

1. **STT**: replace `app/providers/stt.py` — open a Deepgram (or similar)
   streaming websocket per call, forward audio chunks directly (Twilio
   already sends mu-law 8kHz, which Deepgram accepts natively).
2. **LLM**: replace `app/providers/llm.py` — call your model API with the
   transcript + conversation history, return the text reply.
3. **TTS**: replace `app/providers/tts.py` — stream synthesized speech from
   ElevenLabs/etc., resample to mu-law 8kHz, chunk into 20ms frames.
4. **Barge-in**: let the caller interrupt playback (send a `clear` event to
   Twilio and stop the outbound frame loop).
5. **Auth**: look up the caller by phone number / PIN before allowing
   account actions instead of using mock data for everyone.
6. **Persistence**: log transcripts/calls to a DB instead of in-memory only.

## Project structure

```
app/
  main.py           FastAPI app + router registration
  config.py         env var loading
  api/
   | endpoint/
     | routes.py         /voice webhook, /media websocket (transport only)
     | services.py       CallSession — orchestrates STT → LLM → TTS
  providers/
    stt.py          speech-to-text (stub)
    llm.py          banking assistant logic (stub)
    tts.py          text-to-speech (stub)
requirements.txt
.env.example
```
