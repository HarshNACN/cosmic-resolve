"""In-memory voice sessions and the runtime cases they create.

Voice is local-only (the Vercel build never imports Piper or Groq), so process memory is enough: a backend restart
ends open calls. Imports are limited to models so tools.get_case can look cases up here without a cycle.
"""
from __future__ import annotations

import itertools
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator

from ..models import SupportCase

_lock = threading.RLock()
_case_numbers: Iterator[int] | None = None
_VOICE_CASE_ID = re.compile(r"^V-(\d+)$")


def _next_case_number() -> int:
    """Case numbers continue after any voice case already in the trace.

    The trace file outlives the backend. If numbering restarted at 1, a new call's case would share an ID with an
    earlier run's case and inherit that run's logged decision. Caller holds _lock.
    """
    global _case_numbers
    if _case_numbers is None:
        from ..tracing import read_trace_events  # local import: keeps this module's import light

        highest = 0
        try:
            for event in read_trace_events():
                found = _VOICE_CASE_ID.match(str(event.details.get("case_id", "")))
                if found:
                    highest = max(highest, int(found.group(1)))
        except Exception:  # noqa: BLE001 - an unreadable trace just means numbering starts at 1
            pass
        _case_numbers = itertools.count(highest + 1)
    return next(_case_numbers)

STATE_PICK_ORDER = "PICK_ORDER"
STATE_DESCRIBE = "DESCRIBE"
STATE_CONFIRM = "CONFIRM"
STATE_SUBMITTED = "SUBMITTED"
STATE_CLOSED = "CLOSED"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


ENV_CASE_CLOCK = "VOICE_CASE_CLOCK"


def case_timestamp() -> str:
    """The created_at stamped on a new voice case.

    The rule engine counts policy windows (10 days late, 30 days to return) from the case's own date, never from
    today, so a case always gets the same answer. The synthetic orders and fixture cases are frozen in early November,
    so a case stamped with the real clock slides out of those windows as days pass: the demo's lost smart plug
    stopped being a replacement and became an escalation one day later. By default a voice case therefore takes the
    dataset's own date (the newest fixture case). Set VOICE_CASE_CLOCK=real to stamp the real time instead.
    """
    if os.environ.get(ENV_CASE_CLOCK, "dataset").strip().lower() == "real":
        return utc_now()
    try:
        from ..tools import _load_json_list  # local import: tools imports this module lazily too

        stamps = [c["created_at"] for c in _load_json_list("cases.json") if c.get("created_at")]
    except Exception:  # noqa: BLE001 - without fixtures there is no dataset date; use the real clock
        stamps = []
    return max(stamps) if stamps else utc_now()


@dataclass
class VoiceSession:
    session_id: str
    customer_id: str
    first_name: str
    orders: list[dict[str, Any]]
    state: str = STATE_PICK_ORDER
    order_id: str | None = None
    case_type: str | None = None
    complaint_parts: list[str] = field(default_factory=list)
    transcript: list[dict[str, str]] = field(default_factory=list)
    case_id: str | None = None
    submitted_at: str | None = None
    outcome: dict[str, str] | None = None
    outcome_raw: dict[str, Any] | None = None  # the verified facts behind the outcome, kept server-side for localizing
    language: str = "en"
    created_at: str = field(default_factory=utc_now)
    order_misses: int = 0
    clarifications: int = 0
    yes_no_misses: int = 0

    def add(self, role: str, text: str, note: bool = False) -> None:
        """note marks a line that is shown but not spoken (the associate's approved message in its original wording)."""
        self.transcript.append({"role": role, "text": text, "at": utc_now(), **({"note": True} if note else {})})

    def selected_order(self) -> dict[str, Any] | None:
        return next((o for o in self.orders if o["order_id"] == self.order_id), None)

    def snapshot(self) -> dict[str, Any]:
        """What the browser is allowed to see. No internal counters, no complaint text beyond the transcript."""
        return {
            "session_id": self.session_id,
            "customer": {"customer_id": self.customer_id, "first_name": self.first_name},
            "state": self.state,
            "orders": [{k: v for k, v in order.items() if k != "tracking_id"} for order in self.orders],
            "selected_order_id": self.order_id,
            "case_id": self.case_id,
            "transcript": list(self.transcript),
            "outcome": self.outcome,
            "language": self.language,
        }


SESSIONS: dict[str, VoiceSession] = {}
CASES: dict[str, SupportCase] = {}


def new_session(customer_id: str, first_name: str, orders: list[dict[str, Any]]) -> VoiceSession:
    session = VoiceSession(
        session_id=uuid.uuid4().hex[:12], customer_id=customer_id, first_name=first_name, orders=orders
    )
    with _lock:
        SESSIONS[session.session_id] = session
    return session


def get_session(session_id: str) -> VoiceSession | None:
    with _lock:
        return SESSIONS.get(session_id)


def register_case(
    *, order_id: str, customer_id: str, tracking_id: str, case_type: str, complaint_text: str
) -> SupportCase:
    """Create a voice case. It becomes visible to get_case, GET /cases and the whole checkpoint flow."""
    with _lock:
        case_id = f"V-{_next_case_number():04d}"
        case = SupportCase(
            case_id=case_id,
            order_id=order_id,
            customer_id=customer_id,
            tracking_id=tracking_id,
            case_type=case_type,
            market="US",
            category="GADGETS",
            complaint_text=complaint_text,
            channel="VOICE",
            created_at=case_timestamp(),
        )
        CASES[case_id] = case
    return case


def get_case_record(case_id: str) -> SupportCase | None:
    with _lock:
        return CASES.get(case_id)


def list_cases() -> list[SupportCase]:
    with _lock:
        return list(CASES.values())


def reset() -> None:
    """Forget every session and voice case. Used by tests so they never leak into each other."""
    global _case_numbers
    with _lock:
        SESSIONS.clear()
        CASES.clear()
        _case_numbers = None  # numbering is re-read from the trace on the next case
