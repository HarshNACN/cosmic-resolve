"""The conversation state machine for the voice intake agent.

Code owns the facts and the flow; the model helps with understanding and with one empathetic sentence.
    PICK_ORDER -> DESCRIBE -> CONFIRM -> SUBMITTED -> CLOSED
Every sentence spoken at a decision point (which order, the read-back, the outcome) is a fixed template filled
from validated data, never model-written. The customer's words are untrusted: they only ever become the complaint
text of a case, and they reach the model inside delimiters, never as instructions.

With VOICE_MULTILINGUAL on, the call can be held in English, Spanish or Portuguese. The language is session state:
changing it never creates a case, resets the flow or executes anything, it only changes which template and voice
are used from then on. With the flag off, the language is always English and nothing here behaves differently.

run_turn() is a generator of small event dicts so the HTTP layer can stream audio as soon as a sentence exists:
    customer_text, language, stage, agent_sentence, agent_text, case_created, state
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Iterable, Iterator, Protocol

from ..tracing import append_trace_event, read_trace_events
from . import agent_config as cfg
from .languages import (
    explicit_language_request,
    fold,
    interpret_yes_no,
    keyword_case_type,
    resolve_language,
)
from .orders import match_order, spoken_options
from .store import (
    STATE_CLOSED,
    STATE_CONFIRM,
    STATE_DESCRIBE,
    STATE_PICK_ORDER,
    STATE_SUBMITTED,
    VoiceSession,
    register_case,
    utc_now,
)

Event = dict[str, Any]
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="voice")


class DialogueLLM(Protocol):
    """The two model calls the agent needs. Implementations: llm.BedrockDialogueLLM, and fakes in tests."""

    def extract(self, view: dict[str, Any], utterance: str) -> dict[str, Any]:
        """Understand the utterance. May return order_id, case_type, confirmation ('yes'|'no'|'unclear'), off_topic."""

    def speak(self, view: dict[str, Any], utterance: str) -> Iterator[str]:
        """Stream the text of one short empathetic sentence."""


# --- Small deterministic helpers ---------------------------------------------------------------------------------

_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
_WHITESPACE = re.compile(r"\s+")
_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")  # । is the Hindi danda
_DASHES = re.compile(r"\s*[–—]\s*")
_MARKUP = re.compile(r"[*_`#>]+")
# The empathy sentence must never promise anything or name an amount, in any language. Checked on accent-stripped text.
_PROMISE = re.compile(
    r"refund|replac|credit|reimburs|reembols|reemplaz|reposic|devol|estorn|substitu|ressarc|compens|gratis|\bfree\b|"
    r"guarant|garant|promis|promet|approv|aprob|\d|\$|"
    # Hindi (Devanagari): refund, return/back, money, replacement, change, credit, guarantee, promise, approved, free, payment
    + fold(r"रिफंड|वापस|पैसे|पैसा|रिप्लेसमेंट|बदल|क्रेडिट|गारंटी|वादा|वायदा|मंज़ूर|मंजूर|मुफ़्त|मुफ्त|भुगतान|मुआवज़ा|मुआवजा|लौटा|डॉलर|रुपय")
)


def speakable(text: str) -> str:
    """Make model-written text natural to read aloud: dashes become pauses, markdown marks and extra spaces go."""
    return _WHITESPACE.sub(" ", _MARKUP.sub("", _DASHES.sub(", ", text))).strip()


def clean_utterance(text: str) -> str:
    """Drop control characters, collapse whitespace and cap the length."""
    return _WHITESPACE.sub(" ", _CONTROL.sub(" ", text)).strip()[: cfg.MAX_UTTERANCE_CHARS].strip()


def safe_empathy(sentence: str) -> str:
    """The model's sentence, or "" if it contains a promise, a number or a currency sign (the caller then uses a template)."""
    return "" if _PROMISE.search(fold(sentence)) else sentence


def stream_sentences(deltas: Iterable[str]) -> Iterator[str]:
    """Group streamed text into whole sentences, yielding each as soon as it is complete."""
    buffer = ""
    for delta in deltas:
        buffer += delta
        while True:
            match = _SENTENCE_END.search(buffer)
            if not match:
                break
            sentence, buffer = buffer[: match.start()].strip(), buffer[match.end():]
            if sentence:
                yield sentence
    tail = buffer.strip()
    if tail:
        yield tail


def _lang(session: VoiceSession) -> str:
    """The language this session speaks in. Always English unless multilingual calls are switched on."""
    if cfg.multilingual_enabled() and session.language in cfg.LANGUAGES:
        return session.language
    return cfg.DEFAULT_LANGUAGE


def _t(session: VoiceSession, key: str, **fields: Any) -> str:
    return cfg.text(key, _lang(session)).format(**fields)


def _view(session: VoiceSession, expecting: str) -> dict[str, Any]:
    """What the model may see: order IDs, titles and status. Never the customer's name or any account detail."""
    selected = session.selected_order()
    view: dict[str, Any] = {
        "expecting": expecting,
        "orders": [
            {"order_id": o["order_id"], "title": o["title"], "delivery_status": o["delivery_status"]}
            for o in session.orders
        ],
        "selected_order": {"order_id": selected["order_id"], "title": selected["title"]} if selected else None,
    }
    if cfg.multilingual_enabled():
        view["language"] = _lang(session)
    return view


def _trace(session: VoiceSession, event_type: str, message: str, **details: Any) -> None:
    extra = {"case_id": session.case_id} if session.case_id else {}
    append_trace_event(event_type, message, {"session_id": session.session_id, **extra, **details})


def _agent(session: VoiceSession, text: str) -> Event:
    session.add("agent", text)
    _trace(session, "voice_turn", "Agent spoke", role="agent", text=text)
    return {"type": "agent_sentence", "text": text, "lang": _lang(session)}


def _note(session: VoiceSession, text: str, language: str) -> Event:
    """A line shown in the transcript but not spoken: the human-approved message in its original wording."""
    session.add("agent", text, note=True)
    _trace(session, "voice_turn", "Approved message shown", role="agent", text=text, spoken=False)
    return {"type": "agent_text", "text": text, "lang": language}


def _safe_extract(llm: DialogueLLM | None, view: dict[str, Any], utterance: str) -> dict[str, Any]:
    """Run the extraction call; any failure just means "nothing understood", never a crash mid-call."""
    if llm is None:
        return {}
    try:
        data = llm.extract(view, utterance)
    except Exception:  # noqa: BLE001 - network, throttling, malformed output: fall back to deterministic rules
        return {}
    return data if isinstance(data, dict) else {}


def _state(session: VoiceSession) -> Event:
    return {"type": "state", "session": session.snapshot()}


# --- Language ------------------------------------------------------------------------------------------------------

def switch_language(session: VoiceSession, language: str, source: str) -> Event | None:
    """Change the call's language. Returns the event to send, or None when nothing changed (or the feature is off)."""
    if not cfg.multilingual_enabled() or language not in cfg.LANGUAGES or language == session.language:
        return None
    previous, session.language = session.language, language
    _trace(session, "voice_language_changed", "Conversation language changed", **{"from": previous, "to": language, "source": source})
    return {"type": "language", "language": language, "previous": previous, "source": source}


def _confirm_line(session: VoiceSession) -> str:
    order = session.selected_order() or {"title": "order"}
    lang = _lang(session)
    issue = cfg.issue_phrase(session.case_type or "", lang).format(title=order["title"]) if session.case_type else ""
    return cfg.text("CONFIRM", lang).format(title=order["title"], issue=issue)


def _repeat_prompt(session: VoiceSession) -> Iterator[Event]:
    """Ask the current step again, in the (new) language. Used right after a language change."""
    lang = _lang(session)
    if session.state == STATE_PICK_ORDER:
        yield _agent(session, _t(session, "PROMPT_ORDER", options=spoken_options(session.orders, lang)))
    elif session.state == STATE_DESCRIBE:
        order = session.selected_order() or {"title": ""}
        yield _agent(session, _t(session, "PROMPT_DESCRIBE", title=order["title"]))
    elif session.state == STATE_CONFIRM:
        yield _agent(session, _confirm_line(session))
    elif session.state == STATE_SUBMITTED:
        yield _agent(session, _t(session, "STILL_WAITING"))


def change_language(session: VoiceSession, language: str, source: str = "manual", acknowledge: bool = True) -> Iterator[Event]:
    """An explicit language change (a spoken request or the selector). It never creates a case or changes the flow."""
    event = switch_language(session, language, source)
    if event:
        yield event
    if event or (acknowledge and cfg.multilingual_enabled()):
        yield _agent(session, _t(session, "LANGUAGE_SWITCHED"))
        yield from _repeat_prompt(session)
    yield _state(session)


# --- Turns ---------------------------------------------------------------------------------------------------------

def greeting(session: VoiceSession) -> Iterator[Event]:
    """The opening line, spoken once when the call starts."""
    yield _agent(session, _t(session, "GREETING", first_name=session.first_name))
    yield _state(session)


def didnt_catch(session: VoiceSession) -> Iterator[Event]:
    """The recording held no usable speech (silence or noise): ask again without touching the conversation state."""
    yield _agent(session, _t(session, "DIDNT_CATCH"))
    yield _state(session)


def run_turn(
    session: VoiceSession,
    utterance: str,
    llm: DialogueLLM | None,
    *,
    chosen_order_id: str | None = None,
    detected_language: str | None = None,
) -> Iterator[Event]:
    """Handle one customer turn.

    chosen_order_id is an explicit tap on an order card (no guessing needed). detected_language is speech
    recognition's guess for a spoken turn (None for typed text); it only matters with multilingual calls on.
    """
    chosen = next((o for o in session.orders if o["order_id"] == chosen_order_id), None) if chosen_order_id else None
    text = _t(session, "ORDER_TAP", title=chosen["title"]) if chosen else clean_utterance(utterance)
    if not text:
        yield _agent(session, _t(session, "DIDNT_CATCH"))
        yield _state(session)
        return

    multilingual = cfg.multilingual_enabled() and not chosen
    requested = explicit_language_request(text) if multilingual else None

    session.add("customer", text)
    _trace(session, "voice_turn", "Customer spoke", role="customer", text=text)
    yield {"type": "customer_text", "text": text}

    if requested:
        # "Habla español, por favor": switch and re-ask the current step. Never advances the conversation.
        yield from change_language(session, requested, source="request")
        return
    if multilingual:
        event = switch_language(
            session, resolve_language(text, detected_language, session.language), "speech" if detected_language else "text"
        )
        if event:
            yield event

    if session.state == STATE_CLOSED:
        yield _agent(session, _t(session, "CLOSED_LINE"))
    elif session.state == STATE_SUBMITTED:
        yield _agent(session, _t(session, "STILL_WAITING"))
    elif session.state == STATE_PICK_ORDER:
        yield from _pick_order(session, text, llm, chosen)
    elif session.state == STATE_DESCRIBE:
        yield from _describe(session, text, llm)
    elif session.state == STATE_CONFIRM:
        yield from _confirm(session, text, llm)
    yield _state(session)


def _pick_order(
    session: VoiceSession, text: str, llm: DialogueLLM | None, chosen: dict[str, Any] | None
) -> Iterator[Event]:
    order = chosen or match_order(text, session.orders)
    if order is None and llm is not None:
        yield {"type": "stage", "stage": "thinking"}
        wanted = _safe_extract(llm, _view(session, "ORDER"), text).get("order_id")
        order = next((o for o in session.orders if o["order_id"] == wanted), None)  # never trust the model's ID blindly
    if order is None:
        session.order_misses += 1
        key = "ASK_ORDER" if session.order_misses < cfg.MAX_ORDER_MISSES else "ASK_ORDER_AGAIN"
        yield _agent(session, _t(session, key, options=spoken_options(session.orders, _lang(session))))
        return
    session.order_id = order["order_id"]
    session.state = STATE_DESCRIBE
    yield _agent(session, _t(session, "ORDER_PICKED", title=order["title"]))


def _first_sentence(llm: DialogueLLM, view: dict[str, Any], text: str) -> str | None:
    """One empathetic sentence from the model, closing the stream as soon as we have it."""
    deltas = llm.speak(view, text)
    sentences = stream_sentences(deltas)
    try:
        return next(sentences, None)
    finally:
        sentences.close()
        close = getattr(deltas, "close", None)
        if close:
            close()


def _describe(session: VoiceSession, text: str, llm: DialogueLLM | None) -> Iterator[Event]:
    session.complaint_parts.append(text)
    view = _view(session, "DESCRIBE")
    understanding = _POOL.submit(_safe_extract, llm, view, text) if llm is not None else None
    yield {"type": "stage", "stage": "thinking"}

    # The empathetic sentence streams while the extraction call runs in parallel, so speech starts at once.
    sentence = None
    if llm is not None:
        try:
            sentence = _first_sentence(llm, view, text)
        except Exception:  # noqa: BLE001
            sentence = None
    yield _agent(session, safe_empathy(speakable(sentence or "")) or _t(session, "EMPATHY_FALLBACK"))

    data: dict[str, Any] = {}
    if understanding is not None:
        try:
            data = understanding.result(timeout=cfg.EXTRACT_TIMEOUT_SECONDS) or {}
        except Exception:  # noqa: BLE001
            data = {}

    said = data.get("case_type")
    case_type = said if said in cfg.CASE_TYPES else keyword_case_type(" ".join(session.complaint_parts))
    if case_type is None and (said == "OTHER" or data.get("off_topic") is True):
        session.state = STATE_CLOSED
        yield _agent(session, _t(session, "OUT_OF_SCOPE"))
        return
    if case_type is None:
        if session.clarifications < cfg.MAX_CLARIFICATIONS:
            session.clarifications += 1
            yield _agent(session, _t(session, "ASK_DETAIL"))
        else:
            session.state = STATE_CLOSED
            yield _agent(session, _t(session, "OUT_OF_SCOPE"))
        return

    session.case_type = case_type
    session.state = STATE_CONFIRM
    yield _agent(session, _confirm_line(session))


def _confirm(session: VoiceSession, text: str, llm: DialogueLLM | None) -> Iterator[Event]:
    answer = interpret_yes_no(text)
    if answer is None and llm is not None:
        yield {"type": "stage", "stage": "thinking"}
        answer = {"yes": True, "no": False}.get(_safe_extract(llm, _view(session, "CONFIRM"), text).get("confirmation"))
    if answer is None:
        session.yes_no_misses += 1
        yield _agent(session, _t(session, "ASK_YES_NO"))
        return
    if not answer:
        session.order_id = None
        session.case_type = None
        session.complaint_parts.clear()
        session.clarifications = 0
        session.state = STATE_PICK_ORDER
        yield _agent(session, _t(session, "RESTART", options=spoken_options(session.orders, _lang(session))))
        return

    order = session.selected_order()
    if order is None or session.case_type is None:  # defensive: confirm is only reachable with both set
        session.state = STATE_PICK_ORDER
        yield _agent(session, _t(session, "ASK_ORDER", options=spoken_options(session.orders, _lang(session))))
        return
    case = register_case(
        order_id=order["order_id"],
        customer_id=session.customer_id,
        tracking_id=order["tracking_id"],
        case_type=session.case_type,
        complaint_text=" ".join(session.complaint_parts)[:1000],
    )
    session.case_id = case.case_id
    session.state = STATE_SUBMITTED
    session.submitted_at = utc_now()
    line = _agent(session, _t(session, "SUBMITTED"))
    _trace(session, "voice_case_created", "Voice call created a case", transcript=list(session.transcript))
    yield {"type": "case_created", "case_id": case.case_id}
    yield line


# --- Outcome -------------------------------------------------------------------------------------------------------

def _spoken(text: Any) -> str:
    return clean_utterance(text) if isinstance(text, str) else ""


def _case_events(case_id: str, since: str | None) -> list[Any]:
    """Trace events for the case logged after the call submitted it.

    Write actions (mock_action) keep the case ID inside their payload. The time bound is a second guard against
    events left in the trace by an earlier run that happened to use the same case ID.
    """
    start = datetime.fromisoformat(since) if since else None
    return [
        event
        for event in read_trace_events()
        if (event.details.get("case_id") == case_id or (event.details.get("payload") or {}).get("case_id") == case_id)
        and (start is None or datetime.fromisoformat(event.timestamp) >= start)
    ]


def _amount_phrase(executed: Any, language: str) -> str:
    for action in executed if isinstance(executed, list) else []:
        amount = action.get("amount") if isinstance(action, dict) else None
        if isinstance(amount, (int, float)) and not isinstance(amount, bool):
            return cfg.amount_phrase(amount, language)
    return ""


def _approved_text(session: VoiceSession, decision: str, executed: list[Any], message: str, language: str) -> str:
    """A concrete opening from the decision that actually ran, then (in English) the associate-approved message.

    In other languages the approved message is never translated or altered: a localized summary of the verified
    decision is spoken, and the message itself is shown unchanged on screen (see speak_outcome).
    """
    if decision == "ESCALATE":
        return cfg.text("OUTCOME_ESCALATED", language)
    order = session.selected_order()
    template = cfg.outcome_lead(decision, language)
    lead = template.format(title=order["title"], amount=_amount_phrase(executed, language)) if template and order else ""
    if language == cfg.DEFAULT_LANGUAGE:
        return " ".join(part for part in (lead, message) if part) or cfg.text("OUTCOME_APPROVED_GENERIC", language)
    parts = [lead or cfg.text("OUTCOME_APPROVED_GENERIC", language)]
    if message:
        parts.append(cfg.text("SEE_SCREEN", language))
    return " ".join(parts)


def _outcome_text(session: VoiceSession) -> str:
    """What is said for the decided case, in the call's language at the moment it is spoken."""
    raw = session.outcome_raw or {}
    language = _lang(session)
    if raw.get("status") == "REJECTED":
        return cfg.text("OUTCOME_REJECTED", language)
    return _approved_text(session, raw.get("decision", ""), raw.get("executed", []), raw.get("message", ""), language)


def check_outcome(session: VoiceSession) -> dict[str, str] | None:
    """Has a human decided this call's case? Read from the trace events the checkpoint already writes.

    The text spoken to the customer is the customer message the associate approved (possibly edited), taken from
    the send_customer_message write. Escalations send no message, so they get a fixed neutral line.
    """
    if session.outcome is not None or session.state != STATE_SUBMITTED or not session.case_id:
        return session.outcome
    events = _case_events(session.case_id, session.submitted_at)
    decisions = [e for e in events if e.event_type == "human_decision"]
    if not decisions:
        return None
    if not decisions[-1].details.get("approved"):
        session.outcome_raw = {"status": "REJECTED"}
        outcome = {"status": "REJECTED", "decision": "", "text": ""}
    else:
        message, decision, executed = "", "", []
        for event in events:
            if event.event_type == "mock_action":
                payload = event.details.get("payload") or {}
                if payload.get("action") == "send_customer_message":
                    message = _spoken(payload.get("text"))
            elif event.event_type == "actions_executed":
                decision = str(event.details.get("decision") or "")
                executed = event.details.get("actions") or []
        session.outcome_raw = {"status": "APPROVED", "decision": decision, "executed": executed, "message": message}
        outcome = {"status": "APPROVED", "decision": decision, "text": ""}
    outcome["text"] = _outcome_text(session)
    session.outcome = outcome
    session.state = STATE_CLOSED
    return outcome


def speak_outcome(session: VoiceSession) -> Iterator[Event]:
    """Say the outcome once it is known, in the call's current language."""
    outcome = check_outcome(session)
    if outcome is None:
        yield _agent(session, _t(session, "STILL_WAITING"))
    else:
        outcome["text"] = _outcome_text(session)  # the customer may have changed language while on hold
        yield _agent(session, outcome["text"])
        raw = session.outcome_raw or {}
        if raw.get("message") and raw.get("decision") != "ESCALATE" and _lang(session) != cfg.DEFAULT_LANGUAGE:
            yield _note(session, raw["message"], cfg.DEFAULT_LANGUAGE)
    yield _state(session)
