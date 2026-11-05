"""HTTP routes for the voice call, mounted by api.py under /voice.

A turn streams newline-delimited JSON events so audio can start before the turn finishes:
    customer_text, stage, agent_sentence, audio, case_created, state, error, done
and, only when multilingual calls are on: language, agent_text, voice_unavailable
This module imports no optional dependency at import time, so the Vercel build (which has none) loads it safely.
Voice endpoints are meant for the local demo; they hold sessions in process memory.
"""
from __future__ import annotations

import base64
import json
import threading
from typing import Any, Iterator

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import UploadFile

from .. import customer
from ..tools import DomainLookupError, get_customer
from . import agent_config as cfg
from . import debug
from .dialogue import DialogueLLM, change_language, check_outcome, didnt_catch, greeting, run_turn, speak_outcome
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
    status: dict[str, Any] = {
        "llm": llm is not None,
        "stt": stt is not None,
        "tts": tts is not None,
        "problems": [_problems[name] for name in ("stt", "llm", "tts") if name in _problems],
        "agent": cfg.AGENT_NAME,
    }
    if cfg.multilingual_enabled():
        status["multilingual"] = True
        status["languages"] = _voice_languages(tts)
        status["language_labels"] = cfg.LANGUAGE_LABELS
        status["browser_locales"] = cfg.BROWSER_LOCALES
        status["problems"] += list(getattr(tts, "problems", {}).values())
    else:
        status["multilingual"] = False
    return status


def _voice_languages(tts: Any) -> dict[str, bool]:
    """Which languages Cosmo can speak with a loaded voice (text works in all of them regardless)."""
    if tts is None:
        return {language: False for language in cfg.LANGUAGES}
    if hasattr(tts, "languages"):
        return tts.languages()
    return {language: language == cfg.DEFAULT_LANGUAGE for language in cfg.LANGUAGES}


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
                language = event.get("lang", cfg.DEFAULT_LANGUAGE)
                if language != cfg.DEFAULT_LANGUAGE and not _can_speak(speaker, language):
                    # Text is already on screen; tell the page so it can say the voice is missing (or read it in the browser).
                    yield _line({"type": "voice_unavailable", "language": language, "label": cfg.LANGUAGE_LABELS[language]})
                    continue
                try:
                    for pcm, rate in _synthesize(speaker, event["text"], language):
                        yield _line({"type": "audio", "rate": rate, "pcm": base64.b64encode(pcm).decode("ascii")})
                except Exception:  # noqa: BLE001 - the text is already on screen; the browser can read it aloud instead
                    yield _line({"type": "error", "message": "Could not speak that line."})
    except Exception:  # noqa: BLE001 - never leak internals mid-call
        yield _line({"type": "error", "message": "Something went wrong during the call."})
    finally:
        lock.release()
    yield _line({"type": "done"})


def _can_speak(speaker: Any, language: str) -> bool:
    return speaker.available(language) if hasattr(speaker, "available") else language == cfg.DEFAULT_LANGUAGE


def _synthesize(speaker: Any, text: str, language: str) -> Iterator[tuple[bytes, int]]:
    # English keeps the original one-argument call, so a speaker written before multilingual support still works.
    return speaker.synthesize(text) if language == cfg.DEFAULT_LANGUAGE else speaker.synthesize(text, language)


def _ndjson(chunks: Iterator[bytes]) -> StreamingResponse:
    return StreamingResponse(chunks, media_type="application/x-ndjson", headers={"Cache-Control": "no-store"})


# --- Routes -------------------------------------------------------------------------------------------------------
class CreateSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The internal workbench opens a call for a chosen caller (customer_id). The customer page sends no id at all: it signs
    # in with the demo sign-in and opens the call with its session token in the Authorization header.
    customer_id: str | None = Field(default=None, min_length=1, max_length=20)
    language: str | None = Field(default=None, pattern="^(en|es|pt|hi)$")


class SetLanguage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str = Field(pattern="^(en|es|pt|hi)$")


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


def languages() -> dict[str, Any]:
    """The languages the running voice system supports, for the pages that show a language selector.

    Read-only and cheap: it never builds the speech services. `voice` says whether a Piper voice is already loaded for
    the language (None when the voices have not been loaded yet), and text works in every listed language regardless.
    """
    enabled = cfg.multilingual_enabled()
    codes = cfg.LANGUAGES if enabled else (cfg.DEFAULT_LANGUAGE,)
    tts = _services.get("tts")
    voices = _voice_languages(tts) if tts is not None else {}
    return {
        "multilingual": enabled,
        "languages": [
            {"code": code, "label": cfg.LANGUAGE_LABELS[code], "locale": cfg.BROWSER_LOCALES[code], "voice": voices.get(code)}
            for code in codes
        ],
    }


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


def create_session(body: CreateSession, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if authorization is not None:
        # A signed-in customer: who they are comes from the session token, never from the request body.
        if body.customer_id is not None:
            raise HTTPException(status_code=422, detail="Send a session token or a caller, not both.")
        try:
            customer_id = customer.customer_for_token(authorization)
        except customer.CustomerError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    elif body.customer_id is not None:
        customer_id = body.customer_id  # the internal workbench's caller picker (and the existing tests)
    else:
        raise HTTPException(status_code=422, detail="Send a session token or a caller.")
    try:
        first_name = customer_first_name(customer_id)
    except DomainLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    orders = recent_orders(customer_id)
    if not orders:
        raise HTTPException(status_code=409, detail="This customer has no orders to talk about.")
    session = new_session(customer_id, first_name, orders)
    if body.language and cfg.multilingual_enabled():
        session.language = body.language  # the page's language for this call; speech can still change it later
    return session.snapshot()


def set_language(session_id: str, body: SetLanguage) -> StreamingResponse:
    """The manual language selector. Re-asks the current step in the new language; never creates a case or advances the call."""
    session = _require_session(session_id)
    if not cfg.multilingual_enabled():
        raise HTTPException(status_code=409, detail="Multilingual calls are switched off.")
    return _ndjson(_stream(session, change_language(session, body.language, source="manual")))


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


def _transcribe(audio: bytes, filename: str, content_type: str, session: VoiceSession) -> tuple[str, str | None]:
    """(text, detected language). Detection only happens with multilingual calls on; otherwise the call is English."""
    stt = _service("stt")
    if cfg.multilingual_enabled() and hasattr(stt, "transcribe_detailed"):
        result = stt.transcribe_detailed(audio, filename, content_type, hint=session.language)
        return result.text, result.language
    return stt.transcribe(audio, filename, content_type), None


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
        heard, detected = typed, None
        if audio_bytes is not None:
            yield {"type": "stage", "stage": "transcribing"}
            try:
                debug.log("turn_start", session=session.session_id, language=session.language)
                heard, detected = _transcribe(audio_bytes, filename, content_type, session)
                debug.log("transcript", text=heard, detected=detected)
            except TranscriptionError as exc:
                yield {"type": "error", "message": str(exc)}
                return
            if is_probably_noise(heard):
                yield from didnt_catch(session)
                return
        yield from run_turn(session, heard, llm, chosen_order_id=chosen, detected_language=detected)
        debug.log("turn_end", session=session.session_id, language=session.language)

    return _ndjson(_stream(session, events()))


def register(app: FastAPI) -> None:
    """Mount the voice endpoints directly on the app as flat routes (no router wrapper), so app.routes stays a plain list."""
    app.add_api_route("/voice/warmup", warmup, methods=["POST"], tags=["voice"])
    app.add_api_route("/voice/callers", callers, methods=["GET"], tags=["voice"])
    app.add_api_route("/voice/languages", languages, methods=["GET"], tags=["voice"])
    app.add_api_route("/voice/sessions", create_session, methods=["POST"], tags=["voice"])
    app.add_api_route("/voice/sessions/{session_id}", read_session, methods=["GET"], tags=["voice"])
    app.add_api_route("/voice/sessions/{session_id}/speak", speak, methods=["POST"], tags=["voice"])
    app.add_api_route("/voice/sessions/{session_id}/language", set_language, methods=["POST"], tags=["voice"])
    app.add_api_route("/voice/sessions/{session_id}/turn", turn, methods=["POST"], tags=["voice"])
