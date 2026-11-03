"""The conversation state machine for the voice intake agent.

Code owns the facts and the flow; the model helps with understanding and with one empathetic sentence.
    PICK_ORDER -> DESCRIBE -> CONFIRM -> SUBMITTED -> CLOSED
Every sentence spoken at a decision point (which order, the read-back, the outcome) is a fixed template filled
from validated data, never model-written. The customer's words are untrusted: they only ever become the complaint
text of a case, and they reach the model inside delimiters, never as instructions.

run_turn() is a generator of small event dicts so the HTTP layer can stream audio as soon as a sentence exists:
    customer_text, stage, agent_sentence, case_created, state
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Iterable, Iterator, Protocol

from ..tracing import append_trace_event, read_trace_events
from . import agent_config as cfg
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
_DOUBLE_NEGATIVE = re.compile(r"\bnot\s+(wrong|incorrect)\b", re.I)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_NEGATIVE = re.compile(r"\b(no|nope|nah|not|wrong|incorrect|change|different|actually)\b|n't\b", re.I)
_POSITIVE = re.compile(
    r"\b(yes|yeah|yep|yup|correct|right|exactly|sure|ok|okay|absolutely|please|confirm|confirmed|go ahead)\b", re.I
)
_KEYWORDS = (
    (
        "DAMAGED_ON_ARRIVAL",
        re.compile(r"crack|broke|broken|damag|shatter|dent|smash|defect|scratch|doesn.t work|not working|dead on arrival", re.I),
    ),
    (
        "LATE_DELIVERY",
        re.compile(
            r"\blate\b|never (arrived|showed|came)|not arrived|hasn.t arrived|\blost\b|missing|delay|still waiting|"
            r"where is|tracking|didn.t (arrive|show)",
            re.I,
        ),
    ),
    (
        "RETURN_REQUEST",
        re.compile(r"\breturn|\brefund|send (it )?back|don.t want|changed my mind|doesn.t fit|not what i expected", re.I),
    ),
)


_DASHES = re.compile(r"\s*[–—]\s*")
_MARKUP = re.compile(r"[*_`#>]+")


def speakable(text: str) -> str:
    """Make model-written text natural to read aloud: dashes become pauses, markdown marks and extra spaces go."""
    return _WHITESPACE.sub(" ", _MARKUP.sub("", _DASHES.sub(", ", text))).strip()


def clean_utterance(text: str) -> str:
    """Drop control characters, collapse whitespace and cap the length."""
    return _WHITESPACE.sub(" ", _CONTROL.sub(" ", text)).strip()[: cfg.MAX_UTTERANCE_CHARS].strip()


def interpret_yes_no(text: str) -> bool | None:
    """True for yes, False for no, None when it is unclear, mixed ("that's not right") or a double negative."""
    if _DOUBLE_NEGATIVE.search(text):  # "that's not wrong" means yes; leave it to the model rather than guess
        return None
    negative, positive = bool(_NEGATIVE.search(text)), bool(_POSITIVE.search(text))
    if negative and not positive:
        return False
    if positive and not negative:
        return True
    return None


def keyword_case_type(text: str) -> str | None:
    """Fallback classifier used when the model is unavailable or unsure."""
    for case_type, pattern in _KEYWORDS:
        if pattern.search(text):
            return case_type
    return None


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


def _view(session: VoiceSession, expecting: str) -> dict[str, Any]:
    """What the model may see: order IDs, titles and status. Never the customer's name or any account detail."""
    selected = session.selected_order()
    return {
        "expecting": expecting,
        "orders": [
            {"order_id": o["order_id"], "title": o["title"], "delivery_status": o["delivery_status"]}
            for o in session.orders
        ],
        "selected_order": {"order_id": selected["order_id"], "title": selected["title"]} if selected else None,
    }


def _trace(session: VoiceSession, event_type: str, message: str, **details: Any) -> None:
    extra = {"case_id": session.case_id} if session.case_id else {}
    append_trace_event(event_type, message, {"session_id": session.session_id, **extra, **details})


def _agent(session: VoiceSession, text: str) -> Event:
    session.add("agent", text)
    _trace(session, "voice_turn", "Agent spoke", role="agent", text=text)
    return {"type": "agent_sentence", "text": text}


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


# --- Turns ---------------------------------------------------------------------------------------------------------

def greeting(session: VoiceSession) -> Iterator[Event]:
    """The opening line, spoken once when the call starts."""
    yield _agent(session, cfg.GREETING.format(first_name=session.first_name))
    yield _state(session)


def didnt_catch(session: VoiceSession) -> Iterator[Event]:
    """The recording held no usable speech (silence or noise): ask again without touching the conversation state."""
    yield _agent(session, cfg.DIDNT_CATCH)
    yield _state(session)


def run_turn(
    session: VoiceSession,
    utterance: str,
    llm: DialogueLLM | None,
    *,
    chosen_order_id: str | None = None,
) -> Iterator[Event]:
    """Handle one customer turn. chosen_order_id is an explicit tap on an order card (no guessing needed)."""
    chosen = next((o for o in session.orders if o["order_id"] == chosen_order_id), None) if chosen_order_id else None
    text = f"I would like help with my {chosen['title']}." if chosen else clean_utterance(utterance)
    if not text:
        yield _agent(session, cfg.DIDNT_CATCH)
        yield _state(session)
        return

    session.add("customer", text)
    _trace(session, "voice_turn", "Customer spoke", role="customer", text=text)
    yield {"type": "customer_text", "text": text}

    if session.state == STATE_CLOSED:
        yield _agent(session, cfg.CLOSED_LINE)
    elif session.state == STATE_SUBMITTED:
        yield _agent(session, cfg.STILL_WAITING)
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
        line = cfg.ASK_ORDER if session.order_misses < cfg.MAX_ORDER_MISSES else cfg.ASK_ORDER_AGAIN
        yield _agent(session, line.format(options=spoken_options(session.orders)))
        return
    session.order_id = order["order_id"]
    session.state = STATE_DESCRIBE
    yield _agent(session, cfg.ORDER_PICKED.format(title=order["title"]))


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
    yield _agent(session, speakable(sentence or "") or cfg.EMPATHY_FALLBACK)

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
        yield _agent(session, cfg.OUT_OF_SCOPE)
        return
    if case_type is None:
        if session.clarifications < cfg.MAX_CLARIFICATIONS:
            session.clarifications += 1
            yield _agent(session, cfg.ASK_DETAIL)
        else:
            session.state = STATE_CLOSED
            yield _agent(session, cfg.OUT_OF_SCOPE)
        return

    session.case_type = case_type
    session.state = STATE_CONFIRM
    order = session.selected_order() or {"title": "order"}
    yield _agent(session, cfg.CONFIRM.format(title=order["title"], issue=cfg.ISSUE_PHRASES[case_type]))


def _confirm(session: VoiceSession, text: str, llm: DialogueLLM | None) -> Iterator[Event]:
    answer = interpret_yes_no(text)
    if answer is None and llm is not None:
        yield {"type": "stage", "stage": "thinking"}
        answer = {"yes": True, "no": False}.get(_safe_extract(llm, _view(session, "CONFIRM"), text).get("confirmation"))
    if answer is None:
        session.yes_no_misses += 1
        yield _agent(session, cfg.ASK_YES_NO)
        return
    if not answer:
        session.order_id = None
        session.case_type = None
        session.complaint_parts.clear()
        session.clarifications = 0
        session.state = STATE_PICK_ORDER
        yield _agent(session, cfg.RESTART.format(options=spoken_options(session.orders)))
        return

    order = session.selected_order()
    if order is None or session.case_type is None:  # defensive: confirm is only reachable with both set
        session.state = STATE_PICK_ORDER
        yield _agent(session, cfg.ASK_ORDER.format(options=spoken_options(session.orders)))
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
    line = _agent(session, cfg.SUBMITTED)
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


def _amount_phrase(executed: Any) -> str:
    for action in executed if isinstance(executed, list) else []:
        amount = action.get("amount") if isinstance(action, dict) else None
        if isinstance(amount, (int, float)) and not isinstance(amount, bool):
            return f" of ${amount:,.2f}"
    return ""


def _approved_text(session: VoiceSession, decision: str, executed: list[Any], message: str) -> str:
    """A concrete opening from the decision that actually ran, then the associate-approved message."""
    if decision == "ESCALATE":
        return cfg.OUTCOME_ESCALATED
    order = session.selected_order()
    template = cfg.OUTCOME_LEADS.get(decision)
    lead = template.format(title=order["title"], amount=_amount_phrase(executed)) if template and order else ""
    return " ".join(part for part in (lead, message) if part) or cfg.OUTCOME_APPROVED_GENERIC


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
        outcome = {"status": "REJECTED", "decision": "", "text": cfg.OUTCOME_REJECTED}
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
        outcome = {"status": "APPROVED", "decision": decision, "text": _approved_text(session, decision, executed, message)}
    session.outcome = outcome
    session.state = STATE_CLOSED
    return outcome


def speak_outcome(session: VoiceSession) -> Iterator[Event]:
    """Say the outcome once it is known."""
    outcome = check_outcome(session)
    if outcome is None:
        yield _agent(session, cfg.STILL_WAITING)
    else:
        yield _agent(session, outcome["text"])
    yield _state(session)
