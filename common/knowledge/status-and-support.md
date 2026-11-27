---
title: Deepgram Status Page and Support Resources
sources:
  - https://status.deepgram.com
  - https://deepgram.com/contact-us
status: current
valid_as_of: 2026-06
---

# Deepgram Status Page

The Deepgram status page is at **status.deepgram.com** (not deepgram.com/status). It shows real-time operational status for all Deepgram services.

## Services monitored on status.deepgram.com

- **Public API (api.deepgram.com)** — Batch API, Streaming API, TTS API, Voice Agent API, Voice Agent API Downstream Providers
- **DG Whisper Cloud**
- **On-Premise / License Validation**
- **Usage API**
- **Developer Console** — Developer Console UI, Management APIs
- **API Playground**
- **Documentation** (developers.deepgram.com)
- **Deepgram Website** (deepgram.com)

## Navigation

To navigate to the status page, use navigate_to_page with URL: https://status.deepgram.com

The status page is on a different domain (status.deepgram.com) — it is NOT at deepgram.com/status or developers.deepgram.com/status.

## What the status indicators mean

- **Operational** — service is running normally
- **Degraded Performance** — service is up but slower than normal
- **Partial Outage** — some requests are failing
- **Major Outage** — service is broadly unavailable
- **Maintenance** — planned downtime

## Checking for incidents

The status page also shows past incident history going back 90 days. If you're experiencing issues with the Deepgram API, check status.deepgram.com first to see if there is a known incident.
