"""What actually happened to a case, read from the trace the approval checkpoint writes.

One source of truth for Cosmo (what a caller on hold is told) and for the customer's status tracker. It only reports what
the records prove:

    RECEIVED      the case exists; nothing has been looked at yet
    UNDER_REVIEW  a recommendation has been generated for a person to review
    APPROVED      a person approved it, but the actions are NOT confirmed done (still running, or one failed part-way)
    RESOLVED      approved AND the actions are confirmed done (see below)
    FOLLOW_UP     a person has to act: rejected, escalated, or no policy applies

An approval is not an execution. The checkpoint logs `human_decision` first, then runs the write tools (each logs a
`mock_action` record of what it did), and logs `actions_executed` last. If a tool fails part-way there is an approval and
no `actions_executed`. So RESOLVED needs more than the closing event: the right action for the decision must appear in
the summary AND in the tools' own records between the approval and the summary, with the same positive amount for a
refund or credit, plus the customer message and root-cause tag. Anything less stays APPROVED. (The tools in this
prototype are mock write tools: "resolved" means they completed, not that real money moved.)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..tracing import read_trace_events

RECEIVED = "RECEIVED"
UNDER_REVIEW = "UNDER_REVIEW"
APPROVED = "APPROVED"
RESOLVED = "RESOLVED"
FOLLOW_UP = "FOLLOW_UP"

# The action that carries out each decision. Escalation is not a resolution, so it is handled separately.
_PRIMARY = {
    "REPLACE": "create_replacement",
    "REFUND": "issue_refund",
    "STORE_CREDIT": "issue_store_credit",
    "GOODWILL_CREDIT": "issue_store_credit",
}
_MONEY_ACTIONS = ("issue_refund", "issue_store_credit")
_COMPANIONS = ("send_customer_message", "tag_root_cause")
_CREATED = ("support_case_created", "voice_case_created")


@dataclass(frozen=True)
class CaseOutcome:
    state: str
    decision: str = ""  # REPLACE, REFUND, STORE_CREDIT, GOODWILL_CREDIT or ESCALATE, once a person has approved one
    reason: str = ""  # REJECTED, ESCALATED, NO_POLICY (FOLLOW_UP) or NOT_CONFIRMED (APPROVED)
    amount: float | None = None  # the confirmed refund or credit amount
    message: str = ""  # the customer message the associate approved (possibly edited), only when RESOLVED
    executed: tuple[dict[str, Any], ...] = ()  # the confirmed action summaries: name and amount only


def _is_for_case(event: Any, case_id: str) -> bool:
    details = event.details
    return details.get("case_id") == case_id or (details.get("payload") or {}).get("case_id") == case_id


def _positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def case_outcome(case_id: str, since: str | None = None) -> CaseOutcome:
    """The case's verified state. `since` is a second guard against events an earlier run left under the same case id."""
    events = read_trace_events()  # oldest first
    mine = [i for i, event in enumerate(events) if _is_for_case(event, case_id)]
    created = [i for i in mine if events[i].event_type in _CREATED]
    if created:
        mine = [i for i in mine if i > created[-1]]  # only what happened after this case was created
    elif since:
        start = datetime.fromisoformat(since)
        mine = [i for i in mine if datetime.fromisoformat(events[i].timestamp) >= start]

    decisions = [i for i in mine if events[i].event_type == "human_decision"]
    if not decisions:
        if any(events[i].event_type == "no_policy" for i in mine):
            return CaseOutcome(FOLLOW_UP, reason="NO_POLICY")
        if any(events[i].event_type == "proposal_generated" for i in mine):
            return CaseOutcome(UNDER_REVIEW)
        return CaseOutcome(RECEIVED)

    approval = decisions[-1]
    if not events[approval].details.get("approved"):
        return CaseOutcome(FOLLOW_UP, reason="REJECTED")

    closing = next((i for i in mine if i > approval and events[i].event_type == "actions_executed"), None)
    if closing is None:
        return CaseOutcome(APPROVED, reason="NOT_CONFIRMED")

    summary = events[closing].details
    decision = str(summary.get("decision") or "")
    actions = tuple(a for a in (summary.get("actions") or []) if isinstance(a, dict) and isinstance(a.get("action"), str))
    names = [a["action"] for a in actions]
    # What the write tools themselves recorded while this approval ran (by position in the trace, between approval and summary).
    records = [(e.details.get("payload") or {}) for e in events[approval + 1 : closing] if e.event_type == "mock_action"]
    recorded = [r.get("action") for r in records]
    not_confirmed = CaseOutcome(APPROVED, decision=decision, reason="NOT_CONFIRMED")

    if decision == "ESCALATE":
        if all(name in names and name in recorded for name in ("escalate", "tag_root_cause")):
            return CaseOutcome(FOLLOW_UP, decision=decision, reason="ESCALATED", executed=actions)
        return not_confirmed

    primary = _PRIMARY.get(decision)
    if primary is None or not all(name in names and name in recorded for name in (primary, *_COMPANIONS)):
        return not_confirmed

    amount: float | None = None
    if primary in _MONEY_ACTIONS:
        said = next((a.get("amount") for a in actions if a["action"] == primary), None)
        did = next((r.get("amount") for r in records if r.get("action") == primary), None)
        if not (_positive(said) and _positive(did) and float(said) == float(did)):
            return not_confirmed  # the summary and the tool's own record must agree on a real amount
        amount = float(did)

    message = next((str(r.get("text") or "") for r in records if r.get("action") == "send_customer_message" and r.get("case_id") == case_id), "")
    return CaseOutcome(RESOLVED, decision=decision, amount=amount, message=message, executed=actions)
