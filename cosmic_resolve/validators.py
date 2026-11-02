from __future__ import annotations

from typing import Sequence

from .models import ApprovalDecision, Decision, PolicyClause, ResolutionProposal, SupportCase


def validate_approval(approval: ApprovalDecision | None) -> None:
    if approval is None:
        raise ValueError("Write action requires an approval record.")
    if not isinstance(approval, ApprovalDecision):
        raise TypeError("Approval must be an ApprovalDecision instance.")
    if not approval.approved:
        raise ValueError("Write action was rejected or not approved.")
    if not approval.approval_token:
        raise ValueError("Approval token is required.")


def validate_proposal(
    proposal: ResolutionProposal,
    active_case: SupportCase,
    applicable_policy: Sequence[PolicyClause],
) -> bool:
    if proposal.case_id != active_case.case_id:
        raise ValueError("Proposal case ID does not match the active case.")
    if proposal.decision not in Decision:
        raise ValueError("Decision value is not allowed.")
    if proposal.amount < 0:
        raise ValueError("Amount cannot be negative.")
    if not 0 <= proposal.confidence <= 1:
        raise ValueError("Confidence must be between 0 and 1.")
    if not proposal.policy_clause_ids:
        raise ValueError("Resolution proposal must cite at least one policy clause.")

    valid_clause_ids = {clause.clause_id for clause in applicable_policy}
    missing_clause_ids = [clause_id for clause_id in proposal.policy_clause_ids if clause_id not in valid_clause_ids]
    if missing_clause_ids:
        raise ValueError(f"Proposal cites unknown policy clauses: {missing_clause_ids}")

    if proposal.amount > 200 and not proposal.escalation_reasons:
        raise ValueError("Cases over $200 require a documented escalation reason.")
    if proposal.decision == Decision.ESCALATE and not proposal.escalation_reasons:
        raise ValueError("ESCALATE decisions require at least one escalation reason.")
    if proposal.decision != Decision.ESCALATE and not proposal.evidence:
        raise ValueError("Non-ESCALATE decisions require supporting evidence.")

    return True
