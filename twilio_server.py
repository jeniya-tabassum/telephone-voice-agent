"""
Twilio Phone Integration for Deepgram Voice Agent.
Bridges incoming Twilio phone calls to Deepgram Voice Agent API,
reusing the dg-token-relay knowledge stack (hybrid search, expert
escalation, live pricing) plus voice switching and end call functions.

Session/lifecycle/security patterns follow the
deepgram-voice-agent-inbound-telephony reference implementation:
  - VoiceAgentSession: one object per call, [SESSION:<call_sid>] log prefixes
  - Caller audio is held until Deepgram acks SettingsApplied (audio sent
    before the ack is silently dropped server-side)
  - end_call hangs up via the Twilio REST API when credentials are set
  - Optional webhook hardening: Twilio signature validation
    (TWILIO_AUTH_TOKEN) and a secret path token (WEBHOOK_SECRET)

Usage:
    python twilio_server.py

Runs on port 8001 by default. Configure Twilio webhook to POST to
/twilio/voice (or /twilio/voice/<WEBHOOK_SECRET> when the token is set).
"""

import asyncio
import base64
import json
import logging
import os
import random
import time
import uuid
from logging.handlers import RotatingFileHandler

import websockets
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response

from common.agent_functions import FUNCTION_MAP, create_voice_state
from common.agent_templates import AgentTemplates, build_listen_settings
from common.config import (
    FILLER_MESSAGES, FILLER_THRESHOLD_SECONDS, TWILIO_PORT, VOICE_AGENT_URL,
    TWILIO_STT_MODEL, TWILIO_AUDIO_ENCODING, TWILIO_AUDIO_SAMPLE_RATE,
    SERVER_EXTERNAL_URL, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, WEBHOOK_SECRET,
)

load_dotenv(override=True)

# Configure logging
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        # logs/ is a bind mount on a small box - cap it.
        RotatingFileHandler(
            "logs/twilio_server.log", maxBytes=10 * 1024 * 1024, backupCount=3
        ),
    ],
)
logger = logging.getLogger("twilio_server")

app = FastAPI(title="Deepgram Voice Agent - Twilio Phone Integration")

if TWILIO_AUTH_TOKEN:
    from twilio.request_validator import RequestValidator
    _twilio_validator = RequestValidator(TWILIO_AUTH_TOKEN)
    logger.info("Twilio signature validation ENABLED")
else:
    _twilio_validator = None
    logger.warning("TWILIO_AUTH_TOKEN not set - webhook signature validation disabled")

# Active sessions keyed by session_key, for monitoring and debugging.
active_sessions: dict[str, "VoiceAgentSession"] = {}


# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------

def _check_webhook_secret(token: str | None) -> bool:
    """If WEBHOOK_SECRET is unset all requests pass (local dev mode);
    otherwise the path token must match exactly."""
    if not WEBHOOK_SECRET:
        return True
    return token == WEBHOOK_SECRET


async def _check_twilio_signature(request: Request) -> bool:
    """Validate X-Twilio-Signature against the URL Twilio actually signed.

    Behind nginx the request arrives as http://127.0.0.1:8001/..., so the
    signed URL is rebuilt from SERVER_EXTERNAL_URL + path (+ query).
    """
    if not _twilio_validator:
        return True
    url = SERVER_EXTERNAL_URL.rstrip("/") + request.url.path
    if request.url.query:
        url += "?" + request.url.query
    form = await request.form()
    signature = request.headers.get("X-Twilio-Signature", "")
    if _twilio_validator.validate(url, dict(form), signature):
        return True
    logger.warning(
        f"Invalid Twilio signature for {url} "
        f"(signature {'present' if signature else 'MISSING'}) - rejecting"
    )
    return False


# ---------------------------------------------------------------------------
# Per-call session
# ---------------------------------------------------------------------------

class VoiceAgentSession:
    """Bridges one Twilio media stream to one Deepgram Voice Agent session."""

    SETTINGS_TIMEOUT_SECONDS = 5.0
    FAREWELL_TIMEOUT_SECONDS = 12.0
    # How long to let the model produce its own goodbye before falling back to
    # the scripted one. Only a silent model should ever hit this.
    FAREWELL_GRACE_SECONDS = 2.5
    # Audio idle gap that means the goodbye finished generating.
    FAREWELL_IDLE_SECONDS = 1.0
    # Twilio echoes a mark back only once it has finished PLAYING everything
    # queued ahead of it, which is the only real signal that the caller heard
    # the goodbye.
    FAREWELL_MARK = "farewell-played"

    def __init__(self, twilio_ws: WebSocket, stream_sid: str, call_sid: str):
        self.twilio_ws = twilio_ws
        self.stream_sid = stream_sid
        self.call_sid = call_sid or "unknown"
        # Must be unique per stream: without a callSid two concurrent calls
        # would otherwise share the "unknown" key in active_sessions.
        self.session_key = call_sid or stream_sid or uuid.uuid4().hex
        self.dg_ws = None
        self.call_active = True
        self.voice_state = create_voice_state()
        self.settings_applied = asyncio.Event()
        self.filler_complete = asyncio.Event()
        self.filler_complete.set()
        # Only one filler may be spoken at a time, so filler_complete always
        # refers to the injection whose owner holds this lock.
        self.filler_lock = asyncio.Lock()
        self._farewell_pending = False
        self._farewell_audio_seen = False
        self._farewell_last_audio = None
        self._tasks: set[asyncio.Task] = set()
        self._cleanup_done = False

    def _log(self, msg: str, level: int = logging.INFO):
        logger.log(level, f"[SESSION:{self.session_key}] {msg}")

    def _track(self, coro, name: str | None = None) -> asyncio.Task:
        """Create a background task we keep a reference to, so it can be
        cancelled at teardown instead of being reaped by the cycle GC."""
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    # -- lifecycle ----------------------------------------------------------

    async def start(self):
        """Connect to Deepgram, send Settings, and wait for the ack.

        Caller audio buffers in the Twilio websocket until run() starts
        reading it, so nothing said during setup is lost.
        """
        agent_templates = AgentTemplates()
        agent_config = agent_templates.settings["agent"]
        agent_config["listen"] = build_listen_settings(TWILIO_STT_MODEL)
        settings = {
            "type": "Settings",
            "audio": {
                "input": {"encoding": TWILIO_AUDIO_ENCODING, "sample_rate": TWILIO_AUDIO_SAMPLE_RATE},
                "output": {"encoding": TWILIO_AUDIO_ENCODING, "sample_rate": TWILIO_AUDIO_SAMPLE_RATE, "container": "none"},
            },
            "agent": agent_config,
        }

        self.dg_ws = await websockets.connect(
            VOICE_AGENT_URL,
            extra_headers={"Authorization": f"Token {os.environ['DEEPGRAM_API_KEY']}"},
        )
        await self.dg_ws.send(json.dumps(settings))
        self._log("Connected to Deepgram Voice Agent, waiting for SettingsApplied")

    async def run(self):
        """Pump audio both directions until the call ends."""
        tasks = [
            asyncio.create_task(self._twilio_to_deepgram(), name="twilio->dg"),
            asyncio.create_task(self._deepgram_to_twilio(), name="dg->twilio"),
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._log("Call ended")

    async def cleanup(self):
        """Release resources; safe to call multiple times."""
        if self._cleanup_done:
            return
        self._cleanup_done = True
        if active_sessions.get(self.session_key) is self:
            del active_sessions[self.session_key]
        # Unblock anyone parked on a filler that will never finish, then stop
        # the function tasks before the Deepgram socket goes away.
        self.filler_complete.set()
        pending = list(self._tasks)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if self.dg_ws and self.dg_ws.open:
            await self.dg_ws.close()
        self._log("Cleanup complete")

    async def _hang_up(self):
        """End the Twilio call for real.

        With REST credentials the call is completed server-side (the caller
        hears the line end); otherwise we just close the websocket and Twilio
        drops the stream.
        """
        if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and self.call_sid != "unknown":
            try:
                from twilio.rest import Client
                client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
                await asyncio.to_thread(
                    client.calls(self.call_sid).update, status="completed"
                )
                self._log("Call completed via Twilio REST API")
                return
            except Exception as e:
                self._log(f"REST hangup failed, closing websocket instead: {e}", logging.ERROR)
        try:
            await self.twilio_ws.close()
        except Exception:
            pass

    async def _finish_farewell(self):
        """Hang up now that the goodbye has been heard."""
        if not self._farewell_pending:
            return
        self._farewell_pending = False
        await self._hang_up()
        self.call_active = False

    async def _farewell_timeout(self):
        """Fallback hangup so a lost AgentAudioDone can't leave the call open."""
        await asyncio.sleep(self.FAREWELL_TIMEOUT_SECONDS)
        if self._farewell_pending:
            self._log("Farewell timed out - hanging up", logging.WARNING)
            await self._finish_farewell()

    async def _farewell_watcher(self):
        """Mark the end of the goodbye once its audio stops arriving.

        AgentAudioDone is not reliably delivered for the closing utterance, so
        generation-finished is inferred from the audio going idle. The mark is
        what Twilio echoes back after playing everything queued, which is the
        only real signal the caller heard the goodbye.
        """
        while self._farewell_pending:
            await asyncio.sleep(0.25)
            idle_since = self._farewell_last_audio
            if not idle_since:
                continue
            if time.monotonic() - idle_since >= self.FAREWELL_IDLE_SECONDS:
                self._log("Goodbye finished generating - waiting for Twilio playback")
                try:
                    await self.twilio_ws.send_json({
                        "event": "mark",
                        "streamSid": self.stream_sid,
                        "mark": {"name": self.FAREWELL_MARK},
                    })
                except Exception as e:
                    self._log(f"Could not mark farewell: {e}", logging.ERROR)
                    await self._finish_farewell()
                return

    async def _farewell_grace(self, fallback_message):
        """Speak the scripted goodbye only if the model produced none.

        The model answers the end_call function result with its own goodbye, so
        injecting one unconditionally made the caller hear two. This keeps the
        scripted line purely as insurance against hanging up on silence.
        """
        await asyncio.sleep(self.FAREWELL_GRACE_SECONDS)
        if self._farewell_pending and not self._farewell_audio_seen:
            self._log("No goodbye from the model - injecting scripted farewell")
            try:
                await self.dg_ws.send(json.dumps(fallback_message))
            except Exception as e:
                self._log(f"Farewell injection failed: {e}", logging.ERROR)

    # -- twilio -> deepgram -------------------------------------------------

    async def _twilio_to_deepgram(self):
        """Forward caller audio to Deepgram, gated on SettingsApplied."""
        try:
            await asyncio.wait_for(
                self.settings_applied.wait(), timeout=self.SETTINGS_TIMEOUT_SECONDS
            )
            self._log("Settings applied - forwarding caller audio")
        except asyncio.TimeoutError:
            self._log("Timeout waiting for SettingsApplied - aborting call", logging.ERROR)
            self.call_active = False
            return

        try:
            while self.call_active:
                message = await self.twilio_ws.receive_text()
                data = json.loads(message)
                event = data.get("event")

                if event == "media":
                    audio = base64.b64decode(data["media"]["payload"])
                    if self.dg_ws and self.dg_ws.open:
                        await self.dg_ws.send(audio)
                elif event == "mark":
                    # Twilio finished playing everything queued before this
                    # mark, so the goodbye has actually been heard.
                    if data.get("mark", {}).get("name") == self.FAREWELL_MARK:
                        self._log("Farewell playback confirmed - hanging up")
                        await self._finish_farewell()
                        break
                elif event == "stop":
                    self._log("Twilio stream stopped (caller hung up)")
                    self.call_active = False
                    break
        except WebSocketDisconnect:
            self._log("Twilio disconnected")
            self.call_active = False
        except Exception as e:
            self._log(f"Twilio receiver error: {e}", logging.ERROR)
            self.call_active = False

    # -- deepgram -> twilio -------------------------------------------------

    async def _run_with_smart_filler(self, func, params, call_id, call_name):
        """Run a function; only speak a filler if it's still going after
        FILLER_THRESHOLD_SECONDS (mirrors the relay widget). Fast hybrid
        searches respond immediately with no spoken detour."""
        started = time.time()
        task = self._track(func(params), name=f"fn:{call_name}")
        done, _ = await asyncio.wait({task}, timeout=FILLER_THRESHOLD_SECONDS)

        used_filler = False
        if not done:
            if self.filler_lock.locked():
                # Another slow call is already speaking; a second injection
                # would just be rejected and talk over it.
                self._log(f"Filler skipped ({call_name}): one already in flight")
            else:
                await self.filler_lock.acquire()
                filler = random.choice(FILLER_MESSAGES)
                self.filler_complete.clear()
                used_filler = True
                try:
                    await self.dg_ws.send(json.dumps({
                        "type": "InjectAgentMessage",
                        "message": filler,
                    }))
                    self._log(f"Filler injected ({call_name} > {FILLER_THRESHOLD_SECONDS}s): {filler}")
                except Exception as e:
                    self._log(f"Filler injection failed: {e}", logging.ERROR)
                    self.filler_complete.set()

        try:
            result = await task
        except asyncio.CancelledError:
            if used_filler:
                self.filler_complete.set()
                self.filler_lock.release()
            raise
        except Exception as e:
            self._log(f"Error in function {call_name}: {e}", logging.ERROR)
            result = {"error": str(e)}

        elapsed = time.time() - started
        self._log(f"Function {call_name} took {elapsed:.3f}s (filler={'yes' if used_filler else 'no'})")

        if used_filler:
            # Don't talk over our own filler; the receive loop sets the
            # event on AgentAudioDone / barge-in / inject rejection.
            try:
                await self.filler_complete.wait()
            finally:
                self.filler_complete.set()
                self.filler_lock.release()

        try:
            await self.dg_ws.send(json.dumps({
                "type": "FunctionCallResponse",
                "id": call_id,
                "name": call_name,
                "content": json.dumps(result),
            }))
            self._log(f"FunctionCallResponse sent for {call_name}")
        except Exception as e:
            self._log(f"Failed to send FunctionCallResponse for {call_name}: {e}", logging.ERROR)

    async def _handle_function_call(self, msg):
        for func_call in msg.get("functions", []):
            function_name = func_call.get("name")
            function_call_id = func_call.get("id")
            parameters = json.loads(func_call.get("arguments", "{}"))
            self._log(f"Function call: {function_name}({parameters})")

            func = FUNCTION_MAP.get(function_name)
            if not func:
                self._log(f"Unknown function: {function_name}", logging.ERROR)
                continue

            start_time = time.time()

            if function_name == "end_call":
                result = await func(self.dg_ws, parameters)
                await self.dg_ws.send(json.dumps({
                    "type": "FunctionCallResponse",
                    "id": function_call_id,
                    "name": function_name,
                    "content": json.dumps(result["function_response"]),
                }))
                # Return to the receive loop so the goodbye audio keeps flowing
                # to Twilio; the hangup happens once Twilio confirms playback
                # (or on the timeout below). The model speaks its own goodbye in
                # reply to the function result, so nothing is injected here -
                # doing both made the caller hear two farewells.
                self._farewell_pending = True
                self._farewell_audio_seen = False
                self._farewell_last_audio = None
                self._track(self._farewell_watcher(), name="farewell-watcher")
                self._track(
                    self._farewell_grace(result["inject_message"]),
                    name="farewell-grace",
                )
                self._track(self._farewell_timeout(), name="farewell-timeout")
                return

            elif function_name == "switch_voice":
                result = await func(
                    self.dg_ws, parameters,
                    voice_state=self.voice_state, update_listen=False,
                )
                self._log(f"Voice switched to: {result.get('new_voice_name')}")
                elapsed = time.time() - start_time
                self._log(f"Function {function_name} took {elapsed:.3f}s")
                await self.dg_ws.send(json.dumps({
                    "type": "FunctionCallResponse",
                    "id": function_call_id,
                    "name": function_name,
                    "content": json.dumps(result),
                }))
                self._log(f"FunctionCallResponse sent for {function_name}")

            # All other functions (search, expert, pricing):
            # run concurrently, filler only if slow.
            else:
                self._track(
                    self._run_with_smart_filler(
                        func, parameters, function_call_id, function_name,
                    ),
                    name=f"filler:{function_name}",
                )

    async def _deepgram_to_twilio(self):
        """Forward agent audio to Twilio; handle control messages."""
        try:
            async for message in self.dg_ws:
                if not self.call_active:
                    break

                if isinstance(message, bytes):
                    payload = base64.b64encode(message).decode("utf-8")
                    await self.twilio_ws.send_json({
                        "event": "media",
                        "streamSid": self.stream_sid,
                        "media": {"payload": payload},
                    })
                    if self._farewell_pending:
                        self._farewell_audio_seen = True
                        self._farewell_last_audio = time.monotonic()
                    continue

                msg = json.loads(message)
                msg_type = msg.get("type", "")

                if msg_type == "SettingsApplied":
                    self.settings_applied.set()

                # Clear Twilio audio buffer on barge-in
                elif msg_type == "UserStartedSpeaking":
                    await self.twilio_ws.send_json({
                        "event": "clear",
                        "streamSid": self.stream_sid,
                    })
                    self._log("Barge-in: cleared Twilio audio buffer")
                    if not self.filler_complete.is_set():
                        self.filler_complete.set()

                elif msg_type == "AgentAudioDone":
                    # Ignore a stale done for speech that preceded the
                    # farewell injection - the caller must hear the goodbye.
                    if self._farewell_pending:
                        # _farewell_watcher owns the hangup; it infers the end
                        # of the goodbye from the audio going idle, because this
                        # event is not reliably sent for the closing utterance.
                        continue
                    if not self.filler_complete.is_set():
                        self.filler_complete.set()
                        self._log("Filler message finished")

                elif msg_type == "Warning":
                    self._log(f"DG warning: {msg}", logging.WARNING)
                    if msg.get("code") == "INJECT_AGENT_MESSAGE_DURING_AGENT_SPEECH":
                        if not self.filler_complete.is_set():
                            self.filler_complete.set()
                            self._log("Filler rejected (agent speaking), unblocking response")

                elif msg_type == "ConversationText":
                    self._log(f"[{msg.get('role', '')}] {msg.get('content', '')}")

                elif msg_type == "FunctionCallRequest":
                    await self._handle_function_call(msg)
                    if not self.call_active:
                        break

                elif msg_type == "Welcome":
                    self._log(f"Deepgram session: {msg.get('session_id')}")

                elif msg_type == "Error":
                    self._log(f"DG error: {msg.get('description')}", logging.ERROR)

                else:
                    self._log(f"DG message: {msg_type}", logging.DEBUG)

        except (
            websockets.exceptions.ConnectionClosedError,
            websockets.exceptions.ConnectionClosedOK,
        ):
            self._log("Deepgram connection closed")
            self.call_active = False
        except Exception as e:
            self._log(f"Deepgram receiver error: {e}", logging.ERROR)
            self.call_active = False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/twilio/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "twilio-voice-agent",
        "active_calls": len(active_sessions),
        "signature_validation": bool(_twilio_validator),
        "webhook_secret": bool(WEBHOOK_SECRET),
    }


async def _twilio_voice(request: Request, token: str | None) -> Response:
    """Webhook for incoming Twilio calls. Returns TwiML to start a media stream."""
    if not _check_webhook_secret(token):
        return Response(status_code=404)
    if not await _check_twilio_signature(request):
        return Response(status_code=404)

    host = SERVER_EXTERNAL_URL.replace("https://", "").replace("http://", "").rstrip("/")
    media_path = f"/twilio/media/{WEBHOOK_SECRET}" if WEBHOOK_SECRET else "/twilio/media"
    stream_url = f"wss://{host}{media_path}"
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{stream_url}" />
    </Connect>
</Response>"""
    logger.info(f"Incoming call - streaming to {stream_url}")
    return Response(content=twiml, media_type="text/xml")


@app.api_route("/twilio/voice", methods=["GET", "POST"])
async def twilio_voice(request: Request):
    return await _twilio_voice(request, token=None)


@app.api_route("/twilio/voice/{token}", methods=["GET", "POST"])
async def twilio_voice_token(request: Request, token: str):
    return await _twilio_voice(request, token=token)


async def _twilio_media(websocket: WebSocket, token: str | None):
    """Handle Twilio Media Stream and bridge to Deepgram Voice Agent."""
    if not _check_webhook_secret(token):
        # Reject before accepting the websocket handshake.
        await websocket.close(code=4404)
        return

    await websocket.accept()
    logger.info("Twilio media stream connected")

    if not os.environ.get("DEEPGRAM_API_KEY"):
        logger.error("DEEPGRAM_API_KEY not set")
        await websocket.close()
        return

    # Twilio sends "connected" then "start" before any media; wait for start
    # so the session has its stream/call SIDs from the beginning.
    stream_sid = call_sid = None
    try:
        while stream_sid is None:
            data = json.loads(await websocket.receive_text())
            if data.get("event") == "start":
                stream_sid = data["start"]["streamSid"]
                call_sid = data["start"].get("callSid")
    except (WebSocketDisconnect, Exception) as e:
        logger.info(f"Stream closed before start event: {e}")
        return

    session = VoiceAgentSession(websocket, stream_sid, call_sid)
    active_sessions[session.session_key] = session
    session._log(f"Stream started: {stream_sid}")

    try:
        await session.start()
        await session.run()
    except Exception as e:
        session._log(f"Call error: {e}", logging.ERROR)
    finally:
        await session.cleanup()


@app.websocket("/twilio/media")
async def twilio_media(websocket: WebSocket):
    await _twilio_media(websocket, token=None)


@app.websocket("/twilio/media/{token}")
async def twilio_media_token(websocket: WebSocket, token: str):
    await _twilio_media(websocket, token=token)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("TWILIO_PORT", TWILIO_PORT))
    logger.info(f"Starting Twilio server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
