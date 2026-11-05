"""Trace events written exactly as the approval checkpoint and the mock write tools write them.

Tests of what a case has actually done (voice/outcome.py) need realistic event sequences, because the rule is that an
approval alone is not a result: the tools' own records and the closing summary have to agree. test_voice_outcome.py
checks this helper against the real checkpoint, so it cannot drift from what the code really writes.
"""
from __future__ import annotations

from typing import Any

from cosmic_resolve.tracing import append_case_event, append_trace_event


def approve(case_id: str, approved: bool = True, by: str = "Jordan") -> None:
    append_case_event(case_id, "human_decision", "Approved" if approved else "Rejected", approved_by=by, approved=approved, notes="", action="APPROVE")


def _tool(action: str, fields: dict[str, Any]) -> dict[str, Any]:
    return {"action": action, **fields, "approved_by": "Jordan"}


def _steps(case_id: str, order_id: str, customer_id: str, decision: str, message: str, amount: float | None, recorded_amount: float | None):
    shown = amount if recorded_amount is None else recorded_amount
    if decision == "REPLACE":
        primary = _tool("create_replacement", {"order_id": order_id, "sku": "SKU-X"})
    elif decision == "REFUND":
        primary = _tool("issue_refund", {"order_id": order_id, "amount": shown, "reason": "LATE_DELIVERY"})
    elif decision in ("STORE_CREDIT", "GOODWILL_CREDIT"):
        primary = _tool("issue_store_credit", {"customer_id": customer_id, "amount": shown, "reason": decision})
    else:
        primary = _tool("escalate", {"case_id": case_id, "reasons": ["Needs a person"], "recommended_action": "Manual review required"})
    steps = [primary]
    if decision != "ESCALATE":
        steps.append(_tool("send_customer_message", {"case_id": case_id, "text": message}))
    steps.append(_tool("tag_root_cause", {"case_id": case_id, "root_cause": {"category": "CARRIER", "detail": "x"}}))
    return steps


def run_actions(
    case_id: str,
    order_id: str,
    customer_id: str,
    decision: str,
    message: str = "Thanks for waiting.",
    amount: float | None = None,
    *,
    approved: bool = True,
    unrecorded: tuple[str, ...] = (),
    recorded_amount: float | None = None,
    stop_before_summary: bool = False,
) -> None:
    """An approval followed by its write tools and the closing summary, as the checkpoint writes them.

    Defaults write a complete, successful execution. The keyword arguments write the ways it can go wrong:
    `unrecorded` names tools whose own record is missing although the summary lists them; `recorded_amount` makes a tool's
    record disagree with the summary; `stop_before_summary` stops after the tools (a failure part-way writes no summary).
    """
    approve(case_id, approved)
    if not approved:
        return
    steps = _steps(case_id, order_id, customer_id, decision, message, amount, recorded_amount)
    summary = []
    for step in steps:
        if step["action"] not in unrecorded:
            append_trace_event("mock_action", step["action"], {"payload": step})
        summary.append({"action": step["action"], **({"amount": amount} if "amount" in step else {})})
    if not stop_before_summary:
        append_case_event(case_id, "actions_executed", "Gated write actions executed", decision=decision, actions=summary)
