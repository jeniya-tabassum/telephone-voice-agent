import json
import os
import httpx
import asyncio
import time
import logging

from common.config import (
    RELAY_BASE, DEFAULT_VOICE_MODEL, DEFAULT_LANGUAGE, build_speak_provider,
    voice_name_from_model, WEB_STT_MODEL, STT_EOT_THRESHOLD, STT_KEYTERMS,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# dg-token-relay RAG functions
#
# All knowledge lookups go through the relay (RELAY_BASE), which runs hybrid
# search: a fast in-process MiniLM index + curated KB first, merging in Kapa
# only when local confidence is low. Results come back already spoken-ready
# (markdown stripped, prices in cents, bare URLs removed), shaped
# [{score, source_url, title, content}, ...].
# ---------------------------------------------------------------------------

_RELAY_TIMEOUT = httpx.Timeout(30.0, connect=5.0)
_relay_client = None


def _get_relay_client():
    """Shared AsyncClient so repeat calls reuse the TLS connection."""
    global _relay_client
    if _relay_client is None or _relay_client.is_closed:
        _relay_client = httpx.AsyncClient(base_url=RELAY_BASE, timeout=_RELAY_TIMEOUT)
    return _relay_client


async def _relay_post(path, payload):
    t0 = time.time()
    r = await _get_relay_client().post(path, json=payload)
    r.raise_for_status()
    return r.json(), time.time() - t0


def _format_chunks(chunks, max_chunks=8, max_chars=1500):
    return [
        {
            "source_url": c.get("source_url", ""),
            "title": c.get("title", ""),
            "content": (c.get("content") or "")[:max_chars],
        }
        for c in chunks
        if c.get("content") or c.get("title")
    ][:max_chunks]


async def search_deepgram_docs(params):
    """Hybrid docs search via the relay: local index fast path, Kapa merge fallback."""
    query = params.get("query") or params.get("question", "")
    if not query:
        return {"error": "query is required", "results": []}
    try:
        chunks, elapsed = await _relay_post("/search-hybrid", {"query": query})
        results = _format_chunks(chunks if isinstance(chunks, list) else [])
        logger.info(f"search_deepgram_docs: {len(results)} chunks in {elapsed:.3f}s")
        return {"results": results, "latency_seconds": round(elapsed, 3)}
    except Exception as e:
        logger.error(f"search_deepgram_docs failed: {e}")
        return {"error": str(e), "results": []}


async def ask_deepgram_expert(params):
    """Kapa-chat escalation via the relay — ~10s, only after search_deepgram_docs missed."""
    query = params.get("query") or params.get("question", "")
    if not query:
        return {"error": "query is required", "results": []}
    try:
        chunks, elapsed = await _relay_post("/search-expert", {"query": query})
        # First chunk is the generated answer; its title flags low confidence.
        results = _format_chunks(chunks if isinstance(chunks, list) else [], max_chars=3000)
        logger.info(f"ask_deepgram_expert: {len(results)} chunks in {elapsed:.3f}s")
        return {"results": results, "latency_seconds": round(elapsed, 3)}
    except Exception as e:
        logger.error(f"ask_deepgram_expert failed: {e}")
        return {"error": str(e), "results": []}


async def get_deepgram_pricing(params):
    """Live, speech-phrased price for one product via the relay."""
    product = params.get("product", "")
    try:
        chunks, elapsed = await _relay_post("/pricing", {"product": product})
        results = _format_chunks(chunks if isinstance(chunks, list) else [])
        logger.info(f"get_deepgram_pricing({product}): {elapsed:.3f}s")
        return {"results": results, "latency_seconds": round(elapsed, 3)}
    except Exception as e:
        logger.error(f"get_deepgram_pricing failed: {e}")
        return {"error": str(e), "results": []}


def create_voice_state():
    """Create a fresh per-session voice state. Each call gets its own instance."""
    return {
        "gender": "female",
        "accent": "american",
        "model": DEFAULT_VOICE_MODEL,
        # STT language currently configured on the session, not the requested one.
        "language": DEFAULT_LANGUAGE,
    }

# Voice options by gender and accent. ("female", "american") is the voice the
# call starts with, so an accent round-trip lands back on the default.
VOICE_OPTIONS = {
    # English voices
    ("female", "american"): DEFAULT_VOICE_MODEL,
    ("female", "british"): "aura-2-pandora-en",
    ("female", "australian"): "aura-2-theia-en",
    ("male", "american"): "aura-2-orion-en",
    ("male", "british"): "aura-2-draco-en",
    ("male", "australian"): "aura-2-hyperion-en",
    # Spanish voices
    ("female", "spanish"): "aura-2-estrella-es",
    ("male", "spanish"): "aura-2-nestor-es",
    # French voices
    ("female", "french"): "aura-2-agathe-fr",
    ("male", "french"): "aura-2-hector-fr",
    # German voices
    ("female", "german"): "aura-2-viktoria-de",
    ("male", "german"): "aura-2-julius-de",
    # Italian voices
    ("female", "italian"): "aura-2-livia-it",
    ("male", "italian"): "aura-2-dionisio-it",
    # Dutch voices
    ("female", "dutch"): "aura-2-rhea-nl",
    ("male", "dutch"): "aura-2-sander-nl",
    # Japanese voices
    ("female", "japanese"): "aura-2-izanami-ja",
    ("male", "japanese"): "aura-2-fujin-ja",
}

# Map voice names to models for direct requests
VOICE_NAME_MAP = {
    # English - Featured
    "thalia": "aura-2-thalia-en",
    "andromeda": "aura-2-andromeda-en",
    "helena": "aura-2-helena-en",
    "apollo": "aura-2-apollo-en",
    "arcas": "aura-2-arcas-en",
    "aries": "aura-2-aries-en",
    # English - British/Australian
    "draco": "aura-2-draco-en",
    "pandora": "aura-2-pandora-en",
    "hyperion": "aura-2-hyperion-en",
    "theia": "aura-2-theia-en",
    # English - Other popular
    "luna": "aura-2-luna-en",
    "orion": "aura-2-orion-en",
    "athena": "aura-2-athena-en",
    "zeus": "aura-2-zeus-en",
    "aurora": "aura-2-aurora-en",
    "iris": "aura-2-iris-en",
    # Spanish
    "estrella": "aura-2-estrella-es",
    "celeste": "aura-2-celeste-es",
    "nestor": "aura-2-nestor-es",
    # French
    "agathe": "aura-2-agathe-fr",
    "hector": "aura-2-hector-fr",
    # German
    "viktoria": "aura-2-viktoria-de",
    "julius": "aura-2-julius-de",
    # Italian
    "livia": "aura-2-livia-it",
    "dionisio": "aura-2-dionisio-it",
    # Dutch
    "rhea": "aura-2-rhea-nl",
    "sander": "aura-2-sander-nl",
    # Japanese
    "izanami": "aura-2-izanami-ja",
    "fujin": "aura-2-fujin-ja",
}

# The starting voice must be reachable by name too. VOICE_MODEL is
# env-overridable, so register whatever name it resolves to.
DEFAULT_VOICE_NAME_KEY = voice_name_from_model(DEFAULT_VOICE_MODEL).lower()
VOICE_NAME_MAP[DEFAULT_VOICE_NAME_KEY] = DEFAULT_VOICE_MODEL

FEMININE_VOICE_NAMES = {
    "haley", "thalia", "andromeda", "helena", "pandora", "theia", "luna",
    "athena", "aurora", "iris", "estrella", "celeste", "agathe",
    "viktoria", "livia", "rhea", "izanami",
}

# Phrases that mean "go back to the voice the call started with"
DEFAULT_VOICE_PHRASES = (
    "default", "original", "first voice", "starting voice", "usual voice",
    "normal voice", "back to normal", "voice you started",
)

# Map accent/language to Deepgram language codes for STT
ACCENT_TO_LANGUAGE_CODE = {
    "american": "en",
    "british": "en",
    "australian": "en",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "italian": "it",
    "dutch": "nl",
    "japanese": "ja",
}

LANGUAGE_CODE_TO_ACCENT = {
    "es": "spanish",
    "fr": "french",
    "de": "german",
    "it": "italian",
    "nl": "dutch",
    "ja": "japanese",
}

LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "nl": "Dutch",
    "ja": "Japanese",
}

# Flux is English-only, so a non-English session has to fall back to the
# multilingual Nova-3 model, which takes neither keyterms nor eot_threshold.
MULTILINGUAL_STT_MODEL = "nova-3"


def _language_from_model(model):
    """Language code a TTS model speaks, from its suffix (aura-2-nestor-es -> es)."""
    suffix = model.rsplit("-", 1)[-1]
    return suffix if suffix in LANGUAGE_NAMES else "en"


def _build_listen_provider(lang_code):
    """UpdateListen provider for a language, mirroring build_listen_settings.

    Only ever sent on the web path (update_listen=True), so the English case
    restores that path's Flux model together with its keyterm/turn-end tuning
    instead of leaving the session on the multilingual fallback.
    """
    if lang_code == "en":
        return {
            "type": "deepgram",
            "model": WEB_STT_MODEL,
            "eot_threshold": STT_EOT_THRESHOLD,
            "keyterms": list(STT_KEYTERMS),
        }
    return {
        "type": "deepgram",
        "model": MULTILINGUAL_STT_MODEL,
        "language": lang_code,
    }


async def switch_voice(websocket, params, voice_state=None, update_listen=True):
    """Switch the TTS voice based on user request, remembering previous gender/accent."""
    if voice_state is None:
        voice_state = create_voice_state()

    voice_type = params.get("voice_type", "").lower()
    selected_voice = None
    # Set when a language was asked for but this session cannot transcribe it.
    refused_language = None

    # "back to the original voice" / "default voice" returns to the start state
    if any(phrase in voice_type for phrase in DEFAULT_VOICE_PHRASES):
        selected_voice = DEFAULT_VOICE_MODEL
        voice_state["gender"] = (
            "female" if DEFAULT_VOICE_NAME_KEY in FEMININE_VOICE_NAMES else "male"
        )

    # Then check if user requested a specific voice name
    if not selected_voice:
        for name, model in VOICE_NAME_MAP.items():
            if name in voice_type:
                selected_voice = model
                voice_state["gender"] = "female" if name in FEMININE_VOICE_NAMES else "male"
                break

    if selected_voice:
        # A named voice implies its own language; keep the accent bucket in sync
        # so a later gender-only switch does not jump languages.
        named_lang = _language_from_model(selected_voice)
        if named_lang == "en":
            if ACCENT_TO_LANGUAGE_CODE.get(voice_state["accent"], "en") != "en":
                voice_state["accent"] = "american"
        else:
            voice_state["accent"] = LANGUAGE_CODE_TO_ACCENT[named_lang]

    if not selected_voice:
        requested_gender = voice_state["gender"]
        requested_accent = voice_state["accent"]

        if "male" in voice_type and "female" not in voice_type:
            requested_gender = "male"
        elif "female" in voice_type or "woman" in voice_type:
            requested_gender = "female"

        if "british" in voice_type or "uk" in voice_type or "english" in voice_type:
            requested_accent = "british"
        elif "australian" in voice_type or "aussie" in voice_type:
            requested_accent = "australian"
        elif "american" in voice_type or "us" in voice_type:
            requested_accent = "american"
        elif "spanish" in voice_type or "español" in voice_type:
            requested_accent = "spanish"
        elif "french" in voice_type or "français" in voice_type:
            requested_accent = "french"
        elif "german" in voice_type or "deutsch" in voice_type:
            requested_accent = "german"
        elif "italian" in voice_type or "italiano" in voice_type:
            requested_accent = "italian"
        elif "dutch" in voice_type or "netherlands" in voice_type:
            requested_accent = "dutch"
        elif "japanese" in voice_type or "日本語" in voice_type:
            requested_accent = "japanese"

        # A language this session cannot transcribe must be refused before
        # anything is committed: switching TTS to a foreign voice while STT
        # stays English leaves the agent speaking English through the wrong
        # model for the rest of the call, and a stuck foreign accent in
        # voice_state would re-trigger the refusal on later gender-only asks.
        if not update_listen:
            session_lang = voice_state.get("language", DEFAULT_LANGUAGE)
            if ACCENT_TO_LANGUAGE_CODE.get(requested_accent, "en") != session_lang:
                refused_language = ACCENT_TO_LANGUAGE_CODE.get(requested_accent, "en")
                requested_accent = voice_state["accent"]

        selected_voice = VOICE_OPTIONS.get(
            (requested_gender, requested_accent),
            DEFAULT_VOICE_MODEL
        )

        voice_state["gender"] = requested_gender
        voice_state["accent"] = requested_accent

    voice_state["model"] = selected_voice
    new_voice_name = voice_name_from_model(selected_voice)

    requested_lang = ACCENT_TO_LANGUAGE_CODE.get(voice_state["accent"], "en")
    session_lang = voice_state.get("language", DEFAULT_LANGUAGE)

    update_speak = {
        "type": "UpdateSpeak",
        "speak": {
            "provider": build_speak_provider(selected_voice)
        }
    }
    await websocket.send(json.dumps(update_speak))
    logger.info(f"TTS voice switched to: {selected_voice}")

    # Only touch STT when the language actually changes — an accent swap within
    # English must keep the session's tuned English model. Twilio/mulaw sessions
    # pass update_listen=False and cannot change STT at all, so there the agent
    # has to stay in the language STT is already transcribing.
    if requested_lang != session_lang and update_listen:
        update_listen_msg = {
            "type": "UpdateListen",
            "listen": {"provider": _build_listen_provider(requested_lang)},
        }
        await websocket.send(json.dumps(update_listen_msg))
        voice_state["language"] = requested_lang
        session_lang = requested_lang
        logger.info(f"STT language switched to: {requested_lang}")

    spoken_lang = session_lang
    # A refusal is recorded only for the request that actually asked for an
    # unreachable language, so a later gender-only switch is not treated as one.
    language_switched = requested_lang == spoken_lang and refused_language is None
    spoken_language_name = LANGUAGE_NAMES.get(spoken_lang, "English")
    if refused_language:
        requested_lang = refused_language

    if language_switched:
        message = (
            f"Voice switched. You are now {new_voice_name}. "
            f"Introduce yourself briefly in {spoken_language_name}."
        )
    else:
        # Truthfulness first: the voice changed but transcription did not, so the
        # LLM must not pretend the call switched language.
        message = (
            f"Voice switched to {new_voice_name}, but this line can only transcribe "
            f"{spoken_language_name}, so keep speaking {spoken_language_name}. In one short "
            f"sentence, say you can change your voice but have to keep speaking "
            f"{spoken_language_name} on this call. Do NOT answer in "
            f"{LANGUAGE_NAMES.get(requested_lang, 'another language')}."
        )
        logger.info(
            f"Language switch to {requested_lang} declined: STT stays on {spoken_lang}"
        )

    # Return info for LLM to respond naturally
    return {
        "success": True,
        "new_voice_name": new_voice_name,
        "language": spoken_lang,
        "requested_language": requested_lang,
        "language_switched": language_switched,
        "message": message,
    }


async def end_call(websocket, params):
    """End the conversation with an appropriate farewell message."""
    farewell_type = params.get("farewell_type", "general")

    if farewell_type == "thanks":
        message = "Thank you for calling! Have a great day!"
    elif farewell_type == "help":
        message = "I'm glad I could help! Have a wonderful day!"
    else:
        message = "Goodbye! Have a nice day!"

    return {
        "function_response": {"status": "closing", "message": message},
        "inject_message": {"type": "InjectAgentMessage", "message": message},
        "close_message": {"type": "close"},
    }


# Function definitions for Voice Agent API (descriptions ported from
# dg-token-relay agent-config.js — battle-tested on the web widget).
FUNCTION_DEFINITIONS = [
    {
        "name": "search_deepgram_docs",
        "description": (
            "Search the Deepgram knowledge base for information about products, pricing, SDKs, "
            "API reference, and troubleshooting. Call this IMMEDIATELY and SILENTLY for any factual "
            "question about Deepgram — no preamble, no filler text; the system plays a waiting "
            "message for you when needed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The user's question, rephrased as a natural-language search query",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "ask_deepgram_expert",
        "description": (
            "Deep documentation lookup that returns a researched answer from the full Deepgram docs "
            "corpus. MUCH SLOWER than search_deepgram_docs (about ten seconds) — call it ONLY when "
            "search_deepgram_docs results did not clearly contain the answer, at most once per "
            "question, and never as the first search. Call it silently with no preamble; the system "
            "plays a waiting filler for you. If the result title says low confidence, do not state "
            "its content as fact."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The user's question, rephrased as one complete natural-language question",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_deepgram_pricing",
        "description": (
            "Get the exact, current Deepgram price for ONE product, already phrased for speech. "
            "Call this for ANY pricing or cost question (per-minute, per-hour, per-character) INSTEAD "
            "of search_deepgram_docs. Pass the product so it disambiguates — e.g. Nova-3 speech-to-text, "
            "Aura text-to-speech, or the Voice Agent API."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "product": {
                    "type": "string",
                    "description": "One of: nova-3, nova-3-multilingual, flux, flux-multilingual, aura-2, aura-1, voice-agent.",
                }
            },
            "required": ["product"],
        },
    },
    {
        "name": "switch_voice",
        "description": """Call this when user asks to change voice/accent/language/gender, OR when user speaks in a different language.

        Both male AND female voices are available for all accents/languages.
        Supported accents/languages: american, british, australian, spanish, french, german, italian, dutch, japanese
        To return to the voice the call started with, pass "default voice".

        IMPORTANT: Always include the requested gender (male/female) in voice_type. If the user says "female voice", "woman", or a specific female name, include "female". If they say "male voice", "man", include "male".

        IMPORTANT: If user speaks Spanish, French, German, etc., call this function FIRST.

        IMPORTANT: The result decides which language you may speak. If it reports language_switched false, this line can only transcribe the language named in the result: keep speaking that language even though the user asked for another one, and say so in one short sentence. Only answer in another language when the result reports language_switched true for it.

        After calling, introduce yourself briefly with the name the result gives you.
        """,
        "parameters": {
            "type": "object",
            "properties": {
                "voice_type": {
                    "type": "string",
                    "description": "MUST include gender AND accent/language. Examples: 'female american', 'male british', 'female australian', 'male spanish', 'female french'. Always specify both gender and accent.",
                }
            },
            "required": ["voice_type"],
        },
    },
    {
        "name": "end_call",
        "description": """End the conversation ONLY when the user explicitly says goodbye, bye, see you, or clearly states they want to hang up. Do NOT call this for voice/accent/language switch requests or any other commands. When in doubt, ask the user to clarify rather than ending the call.""",
        "parameters": {
            "type": "object",
            "properties": {
                "farewell_type": {
                    "type": "string",
                    "description": "Type of farewell",
                    "enum": ["thanks", "general", "help"],
                }
            },
            "required": ["farewell_type"],
        },
    },
]

# Map function names to implementations
FUNCTION_MAP = {
    "search_deepgram_docs": search_deepgram_docs,
    "ask_deepgram_expert": ask_deepgram_expert,
    "get_deepgram_pricing": get_deepgram_pricing,
    "switch_voice": switch_voice,
    "end_call": end_call,
}
