"""
Shared configuration for Deepgram Voice Agent.
"""

import os

# Deepgram Voice Agent API
VOICE_AGENT_URL = "wss://agent.deepgram.com/v1/agent/converse"

# dg-token-relay — hybrid RAG (/search-hybrid), expert escalation (/search-expert),
# live pricing (/pricing). Staging: https://deepgram-token-relay.fly.dev
RELAY_BASE = os.environ.get("RELAY_BASE", "https://token-relay.deepgram.com").rstrip("/")

# STT models
WEB_STT_MODEL = "flux-general-en"
TWILIO_STT_MODEL = "flux-general-en"

# STT tuning (mirrors dg-token-relay agent-config.js)
STT_EOT_THRESHOLD = 0.7  # 0.5-0.9; raise for fewer premature turn-ends
STT_KEYTERMS = [
    "Deepgram", "Nova-3", "Nova", "Aura-2", "Aura", "Flux", "Saga",
    "diarization", "smart formatting", "endpointing", "Voice Agent",
    "speech-to-text", "text-to-speech", "word error rate",
]

# TTS defaults — Flux TTS (EA; GA 2026-08-12) needs speak provider version "v2",
# which build_speak_provider adds for any flux-* model.
# Set VOICE_MODEL=aura-2-thalia-en to fall back to Aura-2.
DEFAULT_VOICE_MODEL = os.environ.get("VOICE_MODEL", "flux-haley-en")


def build_speak_provider(model):
    provider = {
        "type": "deepgram",
        "model": model,
    }
    if model.startswith("flux-"):
        provider["version"] = "v2"
    return provider


def voice_name_from_model(model):
    return (
        model.replace("flux-", "")
        .replace("aura-2-", "")
        .replace("aura-", "")
        .split("-")[0]
        .capitalize()
    )


DEFAULT_VOICE_NAME = voice_name_from_model(DEFAULT_VOICE_MODEL)
DEFAULT_LANGUAGE = "en"

# LLM settings (match dg-token-relay: gpt-4o, provider-default temperature)
LLM_PROVIDER = "open_ai"
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o")

# Audio settings — Web (linear16, 16kHz)
WEB_AUDIO_ENCODING = "linear16"
WEB_AUDIO_SAMPLE_RATE = 16000
WEB_AUDIO_SECS_PER_CHUNK = 0.05

# Audio settings — Twilio (mulaw, 8kHz)
TWILIO_AUDIO_ENCODING = "mulaw"
TWILIO_AUDIO_SAMPLE_RATE = 8000

# Only speak a filler when a function is still running after this long
# (mirrors the relay widget's 500ms threshold). Hybrid search usually finishes
# under it, so most turns skip the filler entirely.
FILLER_THRESHOLD_SECONDS = 0.5

FILLER_MESSAGES = [
    "Let me look that up for you.",
    "One moment while I check.",
    "Sure, let me find that information.",
    "Give me a second to check on that.",
    "Let me pull up that information.",
    "One moment, please.",
    "Sure, let me check on that.",
    "Hang on, let me look into that.",
]

# Telephony — (415) 301-3720; the number's Voice webhook in the Twilio console
# points at POST https://voice.deepgram.com/twilio/voice
TWILIO_PHONE_NUMBER = "+14153013720"

# External URL Twilio reaches us at (behind nginx). Used to rebuild the exact
# URL Twilio signed when validating webhook signatures, and for the TwiML
# stream host.
SERVER_EXTERNAL_URL = os.environ.get("SERVER_EXTERNAL_URL", "https://voice.deepgram.com")

# Webhook security — both dormant until set in the environment.
# TWILIO_AUTH_TOKEN (Twilio console > Account Info) enables request-signature
# validation on /twilio/voice and REST hangup on end_call (with ACCOUNT_SID).
# WEBHOOK_SECRET adds a path token: point the Twilio webhook at
# /twilio/voice/<secret>; requests without it get a 404.
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")

# Server ports
WEB_PORT = 8000
TWILIO_PORT = 8001

# CORS origins
CORS_ALLOWED_ORIGINS = [
    "https://voice.deepgram.com",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
