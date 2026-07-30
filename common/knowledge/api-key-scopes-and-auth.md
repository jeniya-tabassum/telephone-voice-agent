---
id: api-key-scopes-and-auth
title: What API key or scope do I need for a web-based (browser) voice agent, and how should browser apps authenticate?
category: product/authentication
tags: [api key, scope, scopes, member, roles, permissions, authentication, auth, token, temporary token, short-lived token, jwt, auth grant, browser, web, client-side, voice agent, websocket, security]
answer_kind: fact
sources:
  - https://developers.deepgram.com/guides/fundamentals/token-based-authentication
  - https://developers.deepgram.com/guides/deep-dives/working-with-roles
  - https://developers.deepgram.com/guides/fundamentals/authenticating
owner: jeniya.tabassum@deepgram.com
valid_as_of: "2026-07-24"
review_cadence: weekly
last_reviewed: "2026-07-24"
status: active
confidence: high
---

For a web-based or browser voice agent, never put a long-lived Deepgram API key in the browser. Instead, your server mints a short-lived temporary token and hands that to the browser, which uses it to open the Voice Agent WebSocket directly.

How it works: your server calls POST https://api.deepgram.com/v1/auth/grant with your API key to get a temporary JSON Web Token. The token has a 30 second time-to-live by default, and you can extend it up to 3600 seconds (1 hour) by passing ttl_seconds in the request body. The browser then connects to Deepgram using that token, so the real API key never leaves your server.

Key scope requirement: the API key you use to call the auth grant endpoint must have at least Member permissions. A default key or a key limited to usage-only scopes is not sufficient to mint temporary tokens. So when creating the key in the Deepgram Console for this purpose, choose the Member role for it.

Project roles in brief: Member keys can read and write projects, manage the keys they created, and read and write usage (this includes making transcription, text-to-speech, and voice agent requests, and minting temporary tokens). Admin adds team member management. Owner adds billing and full project control including deletion. For a plain server-side app that only makes speech requests and never mints tokens, a key with the usage write scope is enough; the Member role is what you need once the browser token flow is involved.

The Deepgram SDKs support passing a temporary token in place of an API key when connecting, using bearer token authentication instead of the key header.
