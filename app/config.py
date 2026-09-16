import os

# --- Twilio ---
# Used later if you add signature validation / outbound calls.
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")

# --- Public URL of this server (for TwiML <Stream> wss:// url) ---
# e.g. "your-app.ngrok-free.app" (no scheme, no trailing slash)
PUBLIC_HOSTNAME = os.getenv("PUBLIC_HOSTNAME", "localhost:8000")

# --- Speech-to-Text provider: Azure Speech ---
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY", "")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "")
AZURE_SPEECH_LANGUAGE = os.getenv("AZURE_SPEECH_LANGUAGE", "en-US")

# --- LLM provider ---
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-4-6")

# --- Text-to-Speech provider: OpenAI TTS ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
OPENAI_TTS_VOICE = os.getenv("OPENAI_TTS_VOICE", "alloy")
