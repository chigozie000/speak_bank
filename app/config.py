import os

# --- Twilio ---
# Used later if you add signature validation / outbound calls.
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")

# --- Public URL of this server (for TwiML <Stream> wss:// url) ---
# e.g. "your-app.ngrok-free.app" (no scheme, no trailing slash)
PUBLIC_HOSTNAME = os.getenv("PUBLIC_HOSTNAME", "localhost:8000")

# --- Speech-to-Text provider (stub by default, plug in Deepgram/Whisper etc.) ---
STT_API_KEY = os.getenv("STT_API_KEY", "")

# --- LLM provider ---
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-4-6")

# --- Text-to-Speech provider (stub by default, plug in ElevenLabs/Deepgram etc.) ---
TTS_API_KEY = os.getenv("TTS_API_KEY", "")
