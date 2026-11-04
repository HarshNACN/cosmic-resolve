"""Human-checkpoint support: proposal fingerprint and the stateless decision flow.

The fingerprint is an integrity identifier, not a credential. It binds a human decision to one exact
proposal for one case, so a decision made against a stale or different proposal is refused. It covers only
deterministic proposal content: no timestamps, trace state, or approval metadata.

Decisions are stateless. The decision endpoint never trusts a proposal supplied by the client. It reloads
the case, rebuilds the proposal with the offline provider, and compares fingerprints. Replay protection
below is in-process only; durable replay protection requires shared storage and is a production requirement.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading

from . import config
from .model_provider import RuleBasedModelProvider
from .models import (
    ApprovalDecision,
    CheckpointAction,
    Decision,
    DecisionRequest,
    DecisionResult,
    ExecutedAction,
    ResolutionProposal,
)
from .tools import DomainLookupError, get_case, get_customer, get_policy
from .validators import validate_proposal
from .workflow import AWAITING_APPROVAL, CaseRun, apply_approval, propose_resolution

DISABLED_MESSAGE = "Checkpoint decisions are disabled in this environment. The recommendation is read-only here."
MESSAGE_SENT_ONLY_FOR_NON_ESCALATIONS = (
    "Escalations do not send a customer message, so the message cannot be edited for this case."
)

# Decisions already made in this process. Shared storage would be required to make this durable across
# serverless instances or restarts; see the module docstring.
_decided: set[str] = set()
_decided_lock = threading.Lock()
# Runs awaiting a human decision under the live provider, keyed by (case_id, fingerprint). Guarded by _decided_lock.
# Bounded: only the newest MAX_REMEMBERED_RUNS are kept, so a long-running demo cannot grow without limit.
MAX_REMEMBERED_RUNS = 50
_runs: dict[tuple[str, str], CaseRun] = {}


class CheckpointError(Exception):
    """A controlled decision failure. The API maps it to the status code and detail."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def proposal_fingerprint(proposal: ResolutionProposal) -> str:
    """SHA-256 over canonical JSON of the deterministic proposal content."""
    canonical = {
        "case_id": proposal.case_id,
        "decision": proposal.decision.value,
        "amount": proposal.amount,
        "policy_clause_ids": list(proposal.policy_clause_ids),
        "escalation_reasons": list(proposal.escalation_reasons),
        "customer_message_draft": proposal.customer_message_draft,
        "root_cause": {"category": proposal.root_cause.category, "detail": proposal.root_cause.detail},
        "evidence": list(proposal.evidence),
        "confidence": proposal.confidence,
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _approval_token(case_id: str, fingerprint: str, action: CheckpointAction) -> str:
    # The approval record requires a non-empty token. This is derived from public inputs and is not a secret.
    return hashlib.sha256(f"{case_id}|{fingerprint}|{action.value}".encode("ascii")).hexdigest()[:32]


def _mark_decided(key: str) -> None:
    with _decided_lock:
        _decided.add(key)


def reset_decided_for_tests() -> None:
    with _decided_lock:
        _decided.clear()
        _runs.clear()


def remember_run(run: CaseRun) -> None:
    """Keep the server-generated run a human is about to decide on (live provider only).

    A live model may word the same case differently on a second call, so /decision cannot rebuild and compare.
    It looks up this run by (case, fingerprint) instead. The client still sends only a fingerprint; the server
    only ever acts on a proposal it generated and validated itself. In-process only, like the replay set.
    """
    if run.status != AWAITING_APPROVAL or run.proposal is None:
        return
    key = (run.case.case_id, proposal_fingerprint(run.proposal))
    with _decided_lock:
        # Re-remembering a key moves it to the newest position, so pop before inserting.
        _runs.pop(key, None)
        _runs[key] = copy.deepcopy(run)
        while len(_runs) > MAX_REMEMBERED_RUNS:
            del _runs[next(iter(_runs))]  # dicts keep insertion order: the first key is the oldest


def _recall_run(case_id: str, fingerprint: str) -> CaseRun | None:
    with _decided_lock:
        run = _runs.get((case_id, fingerprint))
    return copy.deepcopy(run) if run is not None else None


def decide(case_id: str, request: DecisionRequest) -> DecisionResult:
    """Execute a human decision against the server-side rebuilt proposal, or refuse it with a CheckpointError.

    Steps: capability check, case load, rebuild with the offline provider, fingerprint comparison, replay check,
    message-only edit, revalidation, approval record, then the existing gated write path in apply_approval.
    """
    if not config.checkpoint_writes_enabled():
        raise CheckpointError(403, DISABLED_MESSAGE)

    case = get_case(case_id)  # raises DomainLookupError for an unknown case; the API maps that to 404

    key = f"{case_id}:{request.proposal_fingerprint}"
    with _decided_lock:
        if key in _decided:
            raise CheckpointError(409, "This proposal has already been decided in this process. Regenerate the recommendation.")

    # Never trust a proposal from the client. Offline: rebuild the deterministic proposal from the case.
    # Live: a model is not repeatable, so use the run this server generated and remembered at /propose.
    if config.live_provider_enabled():
        run = _recall_run(case_id, request.proposal_fingerprint)
        if run is None:
            raise CheckpointError(409, "No matching recommendation is pending for this case. Regenerate the recommendation before deciding.")
    else:
        run = propose_resolution(case_id, RuleBasedModelProvider())
    if run.status != AWAITING_APPROVAL or run.proposal is None:
        raise CheckpointError(409, f"No proposal is awaiting a decision for this case (status {run.status}).")

    current = run.proposal
    fingerprint = proposal_fingerprint(current)
    if fingerprint != request.proposal_fingerprint:
        raise CheckpointError(409, "The proposal has changed since it was generated. Regenerate the recommendation before deciding.")

    token = _approval_token(case_id, fingerprint, request.action)

    if request.action == CheckpointAction.REJECT:
        approval = ApprovalDecision(
            approved=False,
            approved_by=request.reviewer,
            approval_token=token,
            decision=None,
            notes=request.note or "",
        )
        run = apply_approval(run, approval, action=request.action.value)
        _mark_decided(key)
        return DecisionResult(
            case_id=case_id,
            action=request.action,
            status=run.status,
            decision=current.decision,
            executed_actions=[],
            outcome="No resolution action was executed. The case requires manual handling.",
        )

    final = current
    if request.action == CheckpointAction.EDIT_AND_APPROVE:
        if current.decision == Decision.ESCALATE:
            raise CheckpointError(422, MESSAGE_SENT_ONLY_FOR_NON_ESCALATIONS)
        final = current.model_copy(update={"customer_message_draft": request.edited_message})

    # Revalidate the final proposal before any write, whether or not it was edited. The policy and customer
    # (tier and caps) are read again now, not taken from the stored run, so a change since proposal time is caught.
    try:
        fresh_policy = get_policy(case.market, case.category, case.case_type)
        fresh_customer = get_customer(case.customer_id)
    except DomainLookupError as exc:
        raise CheckpointError(422, f"The proposal failed validation: {exc}") from exc
    try:
        validate_proposal(final, run.case, fresh_policy, fresh_customer)
    except ValueError as exc:
        raise CheckpointError(422, f"The proposal failed validation: {exc}") from exc

    run.proposal = final
    approval = ApprovalDecision(
        approved=True,
        approved_by=request.reviewer,
        approval_token=token,
        decision=final.decision,
        notes=request.note or "",
    )
    try:
        run = apply_approval(run, approval, action=request.action.value)
    except ValueError as exc:
        raise CheckpointError(409, str(exc)) from exc
    _mark_decided(key)

    executed = []
    for action in run.actions:
        item = {"action": action["action"]}
        if "amount" in action:
            item["amount"] = action["amount"]
        executed.append(ExecutedAction(**item))
    return DecisionResult(
        case_id=case_id,
        action=request.action,
        status=run.status,
        decision=final.decision,
        executed_actions=executed,
        outcome="Mock actions executed. No live system was changed.",
    )
