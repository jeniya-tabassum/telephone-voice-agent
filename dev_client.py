#!/usr/bin/env python3
"""
dev_client.py - Local development client for testing the phone path without Twilio.

Connects to twilio_server.py's /twilio/media WebSocket and pretends to be a
Twilio media stream (pattern from deepgram-voice-agent-inbound-telephony):
  - Captures audio from your microphone
  - Resamples to 8kHz mono, encodes to mulaw
  - Wraps it in Twilio-format JSON messages
  - Receives agent audio, decodes, plays through your speakers
  - Honors "clear" events (barge-in) by dropping buffered playback

The server can't tell the difference between this and a real Twilio stream.

Usage:
  pip install -r requirements-dev.txt
  python dev_client.py                                # talk to local server
  python dev_client.py --url wss://voice.deepgram.com/twilio/media   # prod
  python dev_client.py --token <WEBHOOK_SECRET>       # append secret path token
  python dev_client.py --probe                        # headless smoke test:
                                                      # no mic needed; sends
                                                      # silence, verifies the
                                                      # greeting audio arrives
"""
import argparse
import asyncio
import base64
import json
import sys
import time
import uuid

try:
    import audioop  # stdlib < 3.13
except ImportError:
    try:
        import audioop_lts as audioop  # pip install audioop-lts
    except ImportError:
        print("ERROR: audioop is required. On Python 3.13+: pip install audioop-lts")
        sys.exit(1)

try:
    import websockets
except ImportError:
    print("ERROR: websockets is required: pip install websockets")
    sys.exit(1)

TWILIO_SAMPLE_RATE = 8000   # Twilio uses 8kHz mulaw
MIC_SAMPLE_RATE = 16000     # capture higher, downsample before encoding
CHANNELS = 1
CHUNK_DURATION_MS = 20      # Twilio's frame cadence
MIC_CHUNK_SIZE = int(MIC_SAMPLE_RATE * CHUNK_DURATION_MS / 1000)
SILENCE_FRAME = b"\xff" * int(TWILIO_SAMPLE_RATE * CHUNK_DURATION_MS / 1000)  # mulaw silence


def start_message() -> dict:
    """A Twilio-shaped start event with fake (but well-formed) SIDs."""
    suffix = uuid.uuid4().hex
    return {
        "event": "start",
        "start": {
            "streamSid": f"MZ{suffix}",
            "callSid": f"CA{suffix}",
        },
    }


async def send_mic_audio(ws, stream_sid: str):
    """Capture mic audio and stream it as Twilio media events."""
    import queue

    import numpy as np
    import sounddevice as sd

    q: "queue.Queue[bytes]" = queue.Queue()

    def on_audio(indata, frames, time_info, status):
        q.put(bytes(indata))

    stream = sd.RawInputStream(
        samplerate=MIC_SAMPLE_RATE,
        blocksize=MIC_CHUNK_SIZE,
        channels=CHANNELS,
        dtype="int16",
        callback=on_audio,
    )
    stream.start()
    print("Microphone live - start talking (Ctrl+C to stop)")
    try:
        loop = asyncio.get_running_loop()
        while True:
            pcm = await loop.run_in_executor(None, q.get)
            pcm8k, _ = audioop.ratecv(pcm, 2, CHANNELS, MIC_SAMPLE_RATE, TWILIO_SAMPLE_RATE, None)
            mulaw = audioop.lin2ulaw(pcm8k, 2)
            await ws.send(json.dumps({
                "event": "media",
                "streamSid": stream_sid,
                "media": {"payload": base64.b64encode(mulaw).decode()},
            }))
    finally:
        stream.stop()
        stream.close()


async def send_silence(ws, stream_sid: str):
    """Probe mode: stream mulaw silence at the Twilio cadence."""
    while True:
        await ws.send(json.dumps({
            "event": "media",
            "streamSid": stream_sid,
            "media": {"payload": base64.b64encode(SILENCE_FRAME).decode()},
        }))
        await asyncio.sleep(CHUNK_DURATION_MS / 1000)


async def receive_audio(ws, play: bool, probe_result: dict):
    """Receive agent audio; play it (mic mode) or just count it (probe mode)."""
    output = None
    if play:
        import numpy as np
        import sounddevice as sd
        output = sd.OutputStream(
            samplerate=TWILIO_SAMPLE_RATE, channels=CHANNELS, dtype="int16"
        )
        output.start()

    t0 = time.time()
    try:
        async for message in ws:
            data = json.loads(message)
            event = data.get("event")

            if event == "media":
                mulaw = base64.b64decode(data["media"]["payload"])
                probe_result["audio_bytes"] += len(mulaw)
                if probe_result["first_audio_s"] is None:
                    probe_result["first_audio_s"] = time.time() - t0
                if output is not None:
                    import numpy as np
                    pcm = audioop.ulaw2lin(mulaw, 2)
                    output.write(np.frombuffer(pcm, dtype="int16"))

            elif event == "clear":
                probe_result["clears"] += 1
                if output is not None:
                    output.abort()
                    output.start()
                    print("(barge-in: playback cleared)")
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if output is not None:
            output.stop()
            output.close()


async def run_client(url: str, probe: bool, probe_seconds: float) -> int:
    probe_result = {"audio_bytes": 0, "first_audio_s": None, "clears": 0}

    async with websockets.connect(url) as ws:
        start = start_message()
        stream_sid = start["start"]["streamSid"]
        await ws.send(json.dumps({"event": "connected", "protocol": "Call"}))
        await ws.send(json.dumps(start))
        print(f"Connected to {url} (callSid {start['start']['callSid']})")

        sender = asyncio.create_task(
            send_silence(ws, stream_sid) if probe else send_mic_audio(ws, stream_sid)
        )
        receiver = asyncio.create_task(receive_audio(ws, play=not probe, probe_result=probe_result))

        try:
            if probe:
                await asyncio.sleep(probe_seconds)
            else:
                await asyncio.gather(sender, receiver)
        except KeyboardInterrupt:
            pass
        finally:
            for task in (sender, receiver):
                task.cancel()
            try:
                await ws.send(json.dumps({"event": "stop", "streamSid": stream_sid}))
            except Exception:
                pass

    if probe:
        secs = probe_result["audio_bytes"] / TWILIO_SAMPLE_RATE  # mulaw: 1 byte/sample
        first = probe_result["first_audio_s"]
        print(f"PROBE: first_audio={f'{first:.2f}s' if first else 'NONE'} "
              f"agent_audio={secs:.1f}s clears={probe_result['clears']}")
        if probe_result["audio_bytes"] > 0:
            print("PROBE PASS: greeting audio received through the media websocket")
            return 0
        print("PROBE FAIL: no agent audio received")
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description="Test the voice agent phone path without Twilio")
    parser.add_argument("--url", default="ws://localhost:8001/twilio/media",
                        help="Media websocket URL (default: ws://localhost:8001/twilio/media)")
    parser.add_argument("--token", default=None,
                        help="WEBHOOK_SECRET path token, appended to the URL")
    parser.add_argument("--probe", action="store_true",
                        help="Headless smoke test: send silence, verify greeting audio arrives")
    parser.add_argument("--probe-seconds", type=float, default=8.0,
                        help="How long to run in probe mode (default: 8)")
    args = parser.parse_args()

    url = args.url.rstrip("/")
    if args.token:
        url += f"/{args.token}"

    print("Deepgram Voice Agent dev client - Ctrl+C to stop")
    try:
        sys.exit(asyncio.run(run_client(url, args.probe, args.probe_seconds)))
    except KeyboardInterrupt:
        print("\nGoodbye!")


if __name__ == "__main__":
    main()
