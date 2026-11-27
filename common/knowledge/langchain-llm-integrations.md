---
title: Deepgram Integrations — LangChain, LLM Pipelines, and AI Frameworks
sources:
  - https://developers.deepgram.com/docs/getting-started-with-pre-recorded-audio
  - https://developers.deepgram.com
status: current
valid_as_of: 2026-06
---

# Deepgram with LangChain and LLM Pipelines

## Using Deepgram with LangChain

Deepgram integrates with LangChain as an audio transcription step in LLM pipelines. Use Deepgram's Python or JavaScript SDK to transcribe audio, then pass the transcript to LangChain agents, chains, or RAG pipelines.

### LangChain Integration Pattern (Python)

```python
from deepgram import DeepgramClient
from langchain.schema import Document

# Step 1: Transcribe audio with Deepgram
dg = DeepgramClient(api_key="YOUR_API_KEY")
response = dg.listen.rest.v("1").transcribe_url(
    {"url": "https://your-audio.mp3"},
    {"model": "nova-3", "smart_format": True}
)
transcript = response.results.channels[0].alternatives[0].transcript

# Step 2: Pass to LangChain as a document
doc = Document(page_content=transcript, metadata={"source": "audio"})
# Then use doc in your LangChain chain, retriever, or agent
```

## Using Deepgram as LLM Pipeline Input

The typical pattern for using Deepgram as input to an LLM pipeline:

1. **Transcribe audio** with Deepgram STT (Nova-3 for accuracy, Flux for real-time/streaming)
2. **Process transcript** with your LLM (OpenAI GPT-4o, Claude, Gemini, etc.)
3. **Optionally synthesize response** with Deepgram Aura-2 TTS

For real-time voice pipelines, use the Deepgram Voice Agent API which handles STT + LLM + TTS orchestration in a single WebSocket connection.

## Supported AI Frameworks

Deepgram works with all major AI/LLM frameworks:
- **LangChain** — via Python/JS SDK or direct REST API
- **LlamaIndex** — for audio RAG pipelines
- **OpenAI SDK-compatible** — Deepgram follows standard REST patterns
- **Pipecat** — native Deepgram integration for voice agent pipelines
- **LiveKit Agents** — native Deepgram STT/TTS plugin

## Getting Started

Install the Deepgram Python SDK: `pip install deepgram-sdk`
Install the Node.js SDK: `npm install @deepgram/sdk`
