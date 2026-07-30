## Deepgram Telephone Voice Agent

Answers phone calls to **(415) 301-3720** with a Deepgram Voice Agent, grounded on
the dg-token-relay knowledge stack (hybrid local search + curated KB + Kapa
escalation + live pricing) — the same backend that powers the web widget on
developers.deepgram.com.

## Project Structure

```
├── common/
│   ├── agent_functions.py    # Relay-backed RAG functions + voice switch / end call
│   ├── agent_templates.py    # Voice Agent Settings (listen/think/speak)
│   ├── prompt_templates.py   # System prompt (ported from dg-token-relay)
│   ├── config.py             # Configuration settings
│   ├── faq.json              # Zero-latency FAQ fast path (answered from prompt)
│   ├── log_formatter.py      # Logger setup
├── client.py                 # Local web client (Flask-SocketIO, mic)
├── twilio_server.py          # Twilio phone bridge (FastAPI, port 8001)
├── test_relay.py             # Relay endpoint smoke test + latency
├── test_latency.py           # Per-stage voice pipeline latency (mic)
```

## Sample .env
```
DEEPGRAM_API_KEY=xxx

# Knowledge relay (default: https://token-relay.deepgram.com)
# RELAY_BASE=https://deepgram-token-relay.fly.dev   # staging

# Legacy — only needed by test_kapa.py / debug_kapa.py (direct Kapa comparison)
# KAPA_PROJECT_ID=xx
# KAPA_API_KEY=xxx
```

## Application Usage

Web client:
```bash
python client.py            # http://localhost:8000
```

Phone bridge:
```bash
python twilio_server.py     # port 8001; Twilio webhook → POST /twilio/voice
```

Relay smoke test (no keys needed):
```bash
python test_relay.py
```

## Telephony setup

The number **(415) 301-3720** (+14153013720) is configured in the Twilio
console: Voice webhook → `POST https://voice.deepgram.com/twilio/voice`.
Twilio media streams require TLS — on the EC2 box, nginx terminates
`voice.deepgram.com` (Let's Encrypt) and proxies `/twilio/` to
`127.0.0.1:8001` with websocket upgrade.

## How answers stay fast and grounded

- `search_deepgram_docs` → relay `/search-hybrid`: local MiniLM index + curated
  KB answers most questions in well under a second; Kapa chunks are merged in
  only when local confidence is low.
- `ask_deepgram_expert` → relay `/search-expert`: ~10s Kapa-chat escalation,
  called at most once per question when search results lack the answer.
- `get_deepgram_pricing` → relay `/pricing`: live prices, already phrased for
  speech.
- Fillers ("One moment...") are only spoken when a lookup exceeds 500ms —
  fast searches answer directly with no spoken detour.
