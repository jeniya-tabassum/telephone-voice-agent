#!/usr/bin/env python3
"""
End-to-end conversation test over the real Twilio media-stream protocol.

Synthesizes each utterance with Deepgram TTS as 8kHz mulaw, streams it in at
realtime cadence, and plays Twilio's side of the protocol faithfully — including
echoing `mark` events back only after the buffered audio would have finished
playing, which is what the farewell hangup depends on.

The bridge does not send transcripts to Twilio, so the agent's side is read
from the server log afterwards.

Usage:
    ./venv/bin/python test_conversation.py --token <WEBHOOK_SECRET>
    ./venv/bin/python test_conversation.py --host localhost:8001   # local
"""
import argparse
import asyncio
import base64
import json
import os
import sys
import time
import uuid

import httpx
import websockets

TTS_URL = "https://api.deepgram.com/v1/speak"
FRAME_MS = 20
FRAME_BYTES = int(8000 * FRAME_MS / 1000)  # mulaw: 1 byte per sample
SILENCE = b"\xff" * FRAME_BYTES

# A caller's turns. The last one must trigger end_call so the farewell path runs.
UTTERANCES = [
    ("What is Deepgram?", 12),
    ("How much does Nova three cost per minute?", 14),
    ("That's all I needed, goodbye!", 14),
]


async def synth(text, api_key):
    """Deepgram TTS -> raw 8kHz mulaw, the exact encoding Twilio carries."""
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(
            TTS_URL,
            params={"model": "aura-2-thalia-en", "encoding": "mulaw", "sample_rate": "8000"},
            headers={"Authorization": f"Token {api_key}"},
            json={"text": text},
        )
        r.raise_for_status()
        return r.content


class TwilioEmulator:
    """Speaks Twilio's half of the media-stream protocol."""

    def __init__(self, ws, stream_sid):
        self.ws = ws
        self.stream_sid = stream_sid
        self.audio_bytes = 0
        self.playback_ends_at = time.monotonic()
        self.marks_echoed = []
        self.clears = 0
        self.closed = False

    async def _send_frame(self, frame):
        """Returns False once the server has hung up."""
        if self.closed:
            return False
        try:
            await self.ws.send(json.dumps({
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {"payload": base64.b64encode(frame).decode()},
            }))
        except websockets.exceptions.ConnectionClosed:
            self.closed = True
            return False
        return True

    async def send_audio(self, mulaw):
        """Stream one utterance in at realtime pace, like a live caller."""
        for i in range(0, len(mulaw), FRAME_BYTES):
            frame = mulaw[i:i + FRAME_BYTES].ljust(FRAME_BYTES, b"\xff")
            if not await self._send_frame(frame):
                return
            await asyncio.sleep(FRAME_MS / 1000)

    async def send_silence(self, seconds):
        for _ in range(int(seconds * 1000 / FRAME_MS)):
            if not await self._send_frame(SILENCE):
                return
            await asyncio.sleep(FRAME_MS / 1000)

    async def receive_loop(self):
        """Consume agent audio; echo marks after simulated playback completes."""
        try:
            async for message in self.ws:
                data = json.loads(message)
                event = data.get("event")

                if event == "media":
                    n = len(base64.b64decode(data["media"]["payload"]))
                    self.audio_bytes += n
                    # Twilio plays at realtime; track when the queue drains.
                    now = time.monotonic()
                    start = max(now, self.playback_ends_at)
                    self.playback_ends_at = start + n / 8000.0

                elif event == "clear":
                    self.clears += 1
                    self.playback_ends_at = time.monotonic()

                elif event == "mark":
                    name = data.get("mark", {}).get("name", "")
                    delay = max(0.0, self.playback_ends_at - time.monotonic())
                    print(f"    server marked {name!r}; echoing in {delay:.1f}s "
                          f"(simulated playback)")
                    await asyncio.sleep(delay)
                    await self.ws.send(json.dumps({
                        "event": "mark",
                        "streamSid": self.stream_sid,
                        "mark": {"name": name},
                    }))
                    self.marks_echoed.append(name)
        except websockets.exceptions.ConnectionClosed:
            self.closed = True


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="voice.deepgram.com")
    ap.add_argument("--token", default=None)
    ap.add_argument("--no-tls", action="store_true")
    args = ap.parse_args()

    api_key = os.environ.get("DEEPGRAM_API_KEY")
    if not api_key:
        print("DEEPGRAM_API_KEY not set")
        return 1

    scheme = "ws" if args.no_tls else "wss"
    url = f"{scheme}://{args.host}/twilio/media"
    if args.token:
        url += f"/{args.token}"

    print(f"Synthesizing {len(UTTERANCES)} caller utterances as 8kHz mulaw...")
    clips = [(t, await synth(t, api_key), wait) for t, wait in UTTERANCES]
    for text, audio, _ in clips:
        print(f"  {len(audio)/8000:.1f}s  {text!r}")

    suffix = uuid.uuid4().hex
    stream_sid, call_sid = f"MZ{suffix}", f"CA{suffix}"
    print(f"\nCalling {url}\n  callSid {call_sid}")

    async with websockets.connect(url) as ws:
        emu = TwilioEmulator(ws, stream_sid)
        await ws.send(json.dumps({"event": "connected", "protocol": "Call"}))
        await ws.send(json.dumps({
            "event": "start",
            "start": {"streamSid": stream_sid, "callSid": call_sid},
        }))
        receiver = asyncio.create_task(emu.receive_loop())

        # Let the greeting play before the caller speaks.
        await emu.send_silence(7)

        for text, audio, wait in clips:
            if emu.closed:
                break
            print(f"\n  caller says: {text!r}")
            before = emu.audio_bytes
            await emu.send_audio(audio)
            await emu.send_silence(wait)
            got = (emu.audio_bytes - before) / 8000.0
            print(f"    agent replied with {got:.1f}s of audio")

        # Give the farewell + hangup time to complete.
        for _ in range(60):
            if emu.closed:
                break
            await asyncio.sleep(0.25)
        receiver.cancel()

    print("\n" + "=" * 58)
    print(f"total agent audio : {emu.audio_bytes/8000:.1f}s")
    print(f"barge-in clears   : {emu.clears}")
    print(f"marks echoed      : {emu.marks_echoed or 'none'}")
    print(f"server closed call: {emu.closed}")

    ok = emu.audio_bytes > 0 and emu.closed and "farewell-played" in emu.marks_echoed
    print("\nRESULT:", "PASS" if ok else "CHECK — see above")
    if not emu.closed:
        print("  server did not hang up after goodbye")
    if "farewell-played" not in emu.marks_echoed:
        print("  farewell mark never arrived (end_call may not have fired)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
