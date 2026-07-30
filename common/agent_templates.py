from common.agent_functions import FUNCTION_DEFINITIONS
from common.prompt_templates import DEEPGRAM_PROMPT_TEMPLATE
from common.config import (
    DEFAULT_VOICE_MODEL, VOICE_AGENT_URL, voice_name_from_model, build_speak_provider,
    WEB_STT_MODEL, LLM_PROVIDER, LLM_MODEL,
    STT_KEYTERMS, STT_EOT_THRESHOLD,
    WEB_AUDIO_ENCODING, WEB_AUDIO_SAMPLE_RATE, WEB_AUDIO_SECS_PER_CHUNK,
)
from datetime import datetime
import os


VOICE = DEFAULT_VOICE_MODEL

# Audio settings (derived from config)
USER_AUDIO_SAMPLE_RATE = WEB_AUDIO_SAMPLE_RATE
USER_AUDIO_SECS_PER_CHUNK = WEB_AUDIO_SECS_PER_CHUNK
USER_AUDIO_SAMPLES_PER_CHUNK = round(USER_AUDIO_SAMPLE_RATE * USER_AUDIO_SECS_PER_CHUNK)

AGENT_AUDIO_SAMPLE_RATE = WEB_AUDIO_SAMPLE_RATE
AGENT_AUDIO_BYTES_PER_SEC = 2 * AGENT_AUDIO_SAMPLE_RATE

AUDIO_SETTINGS = {
    "input": {
        "encoding": WEB_AUDIO_ENCODING,
        "sample_rate": USER_AUDIO_SAMPLE_RATE,
    },
    "output": {
        "encoding": WEB_AUDIO_ENCODING,
        "sample_rate": AGENT_AUDIO_SAMPLE_RATE,
        "container": "none",
    },
}


def build_listen_settings(model):
    """Listen provider with keyterm boosting + turn-end tuning (matches dg-token-relay)."""
    return {
        "provider": {
            "type": "deepgram",
            "model": model,
            "eot_threshold": STT_EOT_THRESHOLD,
            "keyterms": list(STT_KEYTERMS),
        }
    }


LISTEN_SETTINGS = build_listen_settings(WEB_STT_MODEL)

THINK_SETTINGS = {
    "provider": {
        "type": LLM_PROVIDER,
        "model": LLM_MODEL,
    },
    "prompt": DEEPGRAM_PROMPT_TEMPLATE,
    "functions": FUNCTION_DEFINITIONS,
}

def build_speak_settings(model):
    """Speak provider; Flux TTS models require the v2 speak API."""
    return {"provider": build_speak_provider(model)}


SPEAK_SETTINGS = build_speak_settings(VOICE)

AGENT_SETTINGS = {
    "language": "en",
    "listen": LISTEN_SETTINGS,
    "think": THINK_SETTINGS,
    "speak": SPEAK_SETTINGS,
    "greeting": "",
}

SETTINGS = {"type": "Settings", "audio": AUDIO_SETTINGS, "agent": AGENT_SETTINGS}

# Welcome message templates (mirrors dg-token-relay websiteGreeting, with the
# voice's name kept so switch_voice re-introductions stay consistent)
WELCOME_MESSAGES = {
    "en": "Hey, I'm {voiceName} from {company}. {capabilities} What are you curious about?",
}

# Used when the caller's number matches a registration. Unverified, so it only
# ever affects the greeting - never what the agent is willing to disclose.
WELCOME_MESSAGES_KNOWN_CALLER = {
    "en": "Hey {callerName}, welcome back! It's {voiceName} from {company}. What can I help you with today?",
}


class AgentTemplates:
    def __init__(
        self,
        voiceModel=DEFAULT_VOICE_MODEL,
        voiceName="",
        language="en",
        callerName="",
    ):
        self.voiceModel = voiceModel
        if voiceName == "":
            self.voiceName = self.get_voice_name_from_model(self.voiceModel)
        else:
            self.voiceName = voiceName
        self.language = language
        self.company = "Deepgram"

        self.voice_agent_url = VOICE_AGENT_URL
        self.settings = SETTINGS.copy()
        self.settings["agent"] = AGENT_SETTINGS.copy()
        self.settings["agent"]["think"] = THINK_SETTINGS.copy()
        self.settings["agent"]["speak"] = build_speak_settings(self.voiceModel)

        self.user_audio_sample_rate = USER_AUDIO_SAMPLE_RATE
        self.user_audio_secs_per_chunk = USER_AUDIO_SECS_PER_CHUNK
        self.user_audio_samples_per_chunk = USER_AUDIO_SAMPLES_PER_CHUNK
        self.agent_audio_sample_rate = AGENT_AUDIO_SAMPLE_RATE
        self.agent_audio_bytes_per_sec = AGENT_AUDIO_BYTES_PER_SEC

        # Identity only — search/function behavior is governed by the FACTS /
        # GROUNDING / SCOPE sections of the prompt, same as dg-token-relay.
        self.personality = f"You are {self.voiceName} from Deepgram."
        self.capabilities = (
            "I can help with questions about speech-to-text, text-to-speech, "
            "voice agents, pricing, or getting started."
        )
        self.prompt = DEEPGRAM_PROMPT_TEMPLATE

        # Build welcome message
        lang_base = (self.language or "en").split("-")[0].lower()
        self.callerName = (callerName or "").strip()
        if self.callerName:
            templates = WELCOME_MESSAGES_KNOWN_CALLER
        else:
            templates = WELCOME_MESSAGES
        welcome_template = templates.get(lang_base, templates["en"])
        self.first_message = welcome_template.format(
            voiceName=self.voiceName,
            company=self.company,
            capabilities=self.capabilities,
            callerName=self.callerName,
        )

        # Update settings
        self.settings["agent"]["language"] = self.language
        self.settings["agent"]["think"]["prompt"] = self.personality + "\n\n" + self.prompt
        self.settings["agent"]["greeting"] = self.first_message

    def get_voice_name_from_model(self, model):
        return voice_name_from_model(model)
