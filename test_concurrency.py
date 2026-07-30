#!/usr/bin/env python3
"""
Concurrency regression tests — two simultaneous users on each path.

Every defect the expert review confirmed involved a second user, a hangup at
the wrong moment, or hostile input; single-caller probes missed all of them.

Usage:
    ./venv/bin/python test_concurrency.py                  # local servers
    ./venv/bin/python test_concurrency.py --host voice.deepgram.com --tls

Exit 0 = all pass.
"""
import argparse
import asyncio
import base64
import json
import sys
import uuid

import websockets

CHUNK_MS = 20
SILENCE = b"\xff" * int(8000 * CHUNK_MS / 1000)  # mulaw silence, one Twilio frame


async def phone_caller(ws_url, label, seconds):
    """One simulated Twilio media stream. Returns bytes of agent audio received."""
    suffix = uuid.uuid4().hex
    stream_sid, call_sid = f"MZ{suffix}", f"CA{suffix}"
    audio_bytes = 0
    transcript = []

    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({"event": "connected", "protocol": "Call"}))
        await ws.send(json.dumps({
            "event": "start",
            "start": {"streamSid": stream_sid, "callSid": call_sid},
        }))

        async def send_silence():
            while True:
                await ws.send(json.dumps({
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": base64.b64encode(SILENCE).decode()},
                }))
                await asyncio.sleep(CHUNK_MS / 1000)

        async def receive():
            nonlocal audio_bytes
            async for message in ws:
                data = json.loads(message)
                if data.get("event") == "media":
                    audio_bytes += len(base64.b64decode(data["media"]["payload"]))
                    # Every frame must carry OUR streamSid, never the other call's.
                    if data.get("streamSid") not in (stream_sid, None):
                        transcript.append(f"CROSS-TALK: got streamSid {data['streamSid']}")

        sender = asyncio.create_task(send_silence())
        receiver = asyncio.create_task(receive())
        await asyncio.sleep(seconds)
        for t in (sender, receiver):
            t.cancel()

    return {"label": label, "call_sid": call_sid, "audio_bytes": audio_bytes,
            "problems": transcript}


async def test_two_concurrent_calls(ws_url, seconds):
    """Both simultaneous callers must independently hear their own greeting."""
    a, b = await asyncio.gather(
        phone_caller(ws_url, "caller-A", seconds),
        phone_caller(ws_url, "caller-B", seconds),
    )
    ok = True
    for r in (a, b):
        got = r["audio_bytes"] > 0
        print(f"  {r['label']}: {r['audio_bytes']:>6} bytes agent audio  "
              f"{'PASS' if got else 'FAIL (heard nothing)'}")
        ok = ok and got
        for p in r["problems"]:
            print(f"    {p}")
            ok = False
    if a["call_sid"] == b["call_sid"]:
        print("  FAIL: both calls shared a call_sid")
        ok = False
    return ok


async def test_hangup_midcall(ws_url):
    """Abandoning a call mid-greeting must not wedge the server for the next one."""
    victim = asyncio.create_task(phone_caller(ws_url, "abandoned", 1.0))
    await victim
    print("  abandoned call closed after 1s")
    follow = await phone_caller(ws_url, "next-caller", 6.0)
    ok = follow["audio_bytes"] > 0
    print(f"  next-caller: {follow['audio_bytes']:>6} bytes  "
          f"{'PASS' if ok else 'FAIL (server wedged after abandoned call)'}")
    return ok


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost:8001")
    ap.add_argument("--tls", action="store_true", help="use wss:// instead of ws://")
    ap.add_argument("--token", default=None, help="WEBHOOK_SECRET path token")
    ap.add_argument("--seconds", type=float, default=8.0)
    args = ap.parse_args()

    scheme = "wss" if args.tls else "ws"
    ws_url = f"{scheme}://{args.host}/twilio/media"
    if args.token:
        ws_url += f"/{args.token}"

    print(f"Target: {ws_url}\n")
    results = {}

    print("TEST two concurrent phone calls (per-call isolation)")
    results["concurrent_calls"] = await test_two_concurrent_calls(ws_url, args.seconds)

    print("\nTEST hangup mid-call then a fresh call (no wedging / task strand)")
    results["hangup_recovery"] = await test_hangup_midcall(ws_url)

    print("\n" + "=" * 52)
    for name, ok in results.items():
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    failed = [n for n, ok in results.items() if not ok]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
