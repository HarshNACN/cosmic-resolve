"""HTTP routes for the voice call, mounted by api.py under /voice.

A turn streams newline-delimited JSON events so audio can start before the turn finishes:
    customer_text, stage, agent_sentence, audio, case_created, state, error, done
This module imports no optional dependency at import time, so the Vercel build (which has none) loads it safely.
Voice endpoints are meant for the local demo; they hold sessions in process memory.
"""
from __future__ import annotations

import base64
import json
import threading
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import UploadFile

from ..tools import DomainLookupError, get_customer
from . import agent_config as cfg
from .dialogue import DialogueLLM, check_outcome, didnt_catch, greeting, run_turn, speak_outcome
from .llm import BedrockDialogueLLM, VoiceConfigError
from .orders import customer_first_name, recent_orders
from .store import VoiceSession, get_session, new_session
from .stt import GroqTranscriber, TranscriptionError, is_probably_noise
from .tts import PiperSpeaker

# --- Lazily built, cached services (tests replace them through configure_services) ---------------------------------
_services: dict[str, Any] = {}
_problems: dict[str, str] = {}
_build_lock = threading.Lock()
_BUILDERS = {"llm": BedrockDialogueLLM, "stt": GroqTranscriber, "tts": PiperSpeaker}


def configure_services(**services: Any) -> None:
    """Install ready-made services ("llm", "stt", "tts"). Used by tests; None marks one as not configured."""
    with _build_lock:
        for name, service in services.items():
            _services[name] = service
            _problems.pop(name, None)


def reset_services() -> None:
    with _build_lock:
        _services.clear()
        _problems.clear()


def _service(name: str) -> Any | None:
    """The cached service, or None (with the reason remembered) when it is not configured."""
    with _build_lock:
        if name in _services:
            return _services[name]
        try:
            _services[name] = _BUILDERS[name]()
        except VoiceConfigError as exc:
            _services[name] = None
            _problems[name] = str(exc)
        return _services[name]


def _status() -> dict[str, Any]:
    llm, stt, tts = _service("llm"), _service("stt"), _service("tts")
    return {
        "llm": llm is not None,
        "stt": stt is not None,
        "tts": tts is not None,
        "problems": [_problems[name] for name in ("stt", "llm", "tts") if name in _problems],
        "agent": cfg.AGENT_NAME,
    }


# --- Helpers ------------------------------------------------------------------------------------------------------
_turn_locks: dict[str, threading.Lock] = {}


def _line(event: dict[str, Any]) -> bytes:
    return (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")


def _require_session(session_id: str) -> VoiceSession:
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown voice session.")
    return session


def _stream(session: VoiceSession, events: Iterator[dict[str, Any]]) -> Iterator[bytes]:
    """Serialize events, speaking each agent sentence with Piper as soon as it exists. One turn at a time per call."""
    lock = _turn_locks.setdefault(session.session_id, threading.Lock())
    if not lock.acquire(blocking=False):
        yield _line({"type": "error", "message": "The agent is still talking. Please wait a moment."})
        yield _line({"type": "done"})
        return
    speaker = _service("tts")
    try:
        for event in events:
            yield _line(event)
            if event["type"] == "agent_sentence" and speaker is not None:
                try:
                    for pcm, rate in speaker.synthesize(event["text"]):
                        yield _line({"type": "audio", "rate": rate, "pcm": base64.b64encode(pcm).decode("ascii")})
                except Exception:  # noqa: BLE001 - the text is already on screen; the browser can read it aloud instead
                    yield _line({"type": "error", "message": "Could not speak that line."})
    except Exception:  # noqa: BLE001 - never leak internals mid-call
        yield _line({"type": "error", "message": "Something went wrong during the call."})
    finally:
        lock.release()
    yield _line({"type": "done"})


def _ndjson(chunks: Iterator[bytes]) -> StreamingResponse:
    return StreamingResponse(chunks, media_type="application/x-ndjson", headers={"Cache-Control": "no-store"})


# --- Routes -------------------------------------------------------------------------------------------------------
class CreateSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str = Field(min_length=1, max_length=20)


class SpeakRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(pattern="^(greeting|outcome)$")


def warmup() -> dict[str, Any]:
    """Report what is configured and open the slow connections before the first turn (Piper load, Bedrock TLS)."""
    status = _status()
    llm = _service("llm")
    if llm is not None and hasattr(llm, "warmup"):
        llm.warmup()
    return status


def callers() -> dict[str, list[dict[str, Any]]]:
    """The demo cast the presenter can call as. Names are synthetic."""
    cast = []
    for customer_id in cfg.DEMO_CALLERS:
        try:
            customer = get_customer(customer_id)
        except DomainLookupError:
            continue
        cast.append(
            {
                "customer_id": customer_id,
                "name": customer.name,
                "tier": customer.loyalty_tier,
                "orders": len(recent_orders(customer_id)),
            }
        )
    return {"callers": cast}


def create_session(body: CreateSession) -> dict[str, Any]:
    try:
        first_name = customer_first_name(body.customer_id)
    except DomainLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    orders = recent_orders(body.customer_id)
    if not orders:
        raise HTTPException(status_code=409, detail="This customer has no orders to talk about.")
    return new_session(body.customer_id, first_name, orders).snapshot()


def read_session(session_id: str) -> dict[str, Any]:
    """The call's current state. Polling this also notices when a human has decided the case."""
    session = _require_session(session_id)
    check_outcome(session)
    return session.snapshot()


def speak(session_id: str, body: SpeakRequest) -> StreamingResponse:
    session = _require_session(session_id)
    if body.kind == "greeting":
        if session.transcript:
            raise HTTPException(status_code=409, detail="The greeting has already been spoken.")
        return _ndjson(_stream(session, greeting(session)))
    if check_outcome(session) is None:
        raise HTTPException(status_code=409, detail="No decision has been made on this case yet.")
    return _ndjson(_stream(session, speak_outcome(session)))


async def turn(session_id: str, request: Request) -> StreamingResponse:
    """One customer turn: spoken audio, typed text, or a tapped order card (exactly one of the three)."""
    session = _require_session(session_id)
    try:
        form = await request.form()
    except Exception as exc:  # noqa: BLE001 - includes a missing python-multipart install
        raise HTTPException(status_code=400, detail="Send the turn as a multipart form.") from exc
    text, order_id, audio = form.get("text"), form.get("order_id"), form.get("audio")
    given = [value for value in (text, order_id, audio) if value not in (None, "")]
    if len(given) != 1:
        raise HTTPException(status_code=422, detail="Send exactly one of: audio, text, order_id.")

    audio_bytes: bytes | None = None
    filename, content_type = "speech.webm", "audio/webm"
    if isinstance(audio, UploadFile):
        audio_bytes = await audio.read(cfg.MAX_AUDIO_BYTES + 1)
        if len(audio_bytes) > cfg.MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="That recording is too long. Please say it in a shorter turn.")
        filename, content_type = audio.filename or filename, audio.content_type or content_type
        if _service("stt") is None:
            raise HTTPException(status_code=503, detail=_problems.get("stt", "Speech to text is not configured."))
    elif audio not in (None, ""):
        raise HTTPException(status_code=422, detail="audio must be a file upload.")

    llm: DialogueLLM | None = _service("llm")
    typed = text if isinstance(text, str) else ""
    chosen = order_id if isinstance(order_id, str) else None

    def events() -> Iterator[dict[str, Any]]:
        heard = typed
        if audio_bytes is not None:
            yield {"type": "stage", "stage": "transcribing"}
            try:
                heard = _service("stt").transcribe(audio_bytes, filename, content_type)
            except TranscriptionError as exc:
                yield {"type": "error", "message": str(exc)}
                return
            if is_probably_noise(heard):
                yield from didnt_catch(session)
                return
        yield from run_turn(session, heard, llm, chosen_order_id=chosen)

    return _ndjson(_stream(session, events()))


def register(app: FastAPI) -> None:
    """Mount the voice endpoints directly on the app as flat routes (no router wrapper), so app.routes stays a plain list."""
    app.add_api_route("/voice/warmup", warmup, methods=["POST"], tags=["voice"])
    app.add_api_route("/voice/callers", callers, methods=["GET"], tags=["voice"])
    app.add_api_route("/voice/sessions", create_session, methods=["POST"], tags=["voice"])
    app.add_api_route("/voice/sessions/{session_id}", read_session, methods=["GET"], tags=["voice"])
    app.add_api_route("/voice/sessions/{session_id}/speak", speak, methods=["POST"], tags=["voice"])
    app.add_api_route("/voice/sessions/{session_id}/turn", turn, methods=["POST"], tags=["voice"])
