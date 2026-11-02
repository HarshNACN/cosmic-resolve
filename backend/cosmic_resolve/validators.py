from __future__ import annotations

from typing import Sequence

from .config import ESCALATION_THRESHOLD_USD, GOODWILL_CAPS_USD
from .models import ApprovalDecision, Customer, Decision, PolicyClause, ResolutionProposal, SupportCase


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
    customer: Customer | None = None,
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

    out_of_scope = [
        clause.clause_id
        for clause in applicable_policy
        if clause.clause_id in proposal.policy_clause_ids
        and (clause.market, clause.category, clause.case_type)
        != (active_case.market, active_case.category, active_case.case_type)
    ]
    if out_of_scope:
        raise ValueError(f"Proposal cites clauses that do not apply to this case: {out_of_scope}")

    if proposal.amount > ESCALATION_THRESHOLD_USD and proposal.decision != Decision.ESCALATE:
        raise ValueError(f"Amounts over ${ESCALATION_THRESHOLD_USD:.0f} must be ESCALATE decisions.")
    if proposal.decision == Decision.ESCALATE and not proposal.escalation_reasons:
        raise ValueError("ESCALATE decisions require at least one escalation reason.")
    if proposal.decision != Decision.ESCALATE and not proposal.evidence:
        raise ValueError("Non-ESCALATE decisions require supporting evidence.")

    if proposal.decision == Decision.GOODWILL_CREDIT:
        _validate_goodwill_cap(proposal, active_case, customer)

    return True


def _validate_goodwill_cap(proposal: ResolutionProposal, active_case: SupportCase, customer: Customer | None) -> None:
    if customer is None:
        raise ValueError("GOODWILL_CREDIT proposals require the customer record to check the tier cap.")
    if customer.customer_id != active_case.customer_id:
        raise ValueError("Customer record does not match the active case.")
    cap = GOODWILL_CAPS_USD.get(customer.loyalty_tier)
    if cap is None:
        raise ValueError(f"No goodwill cap defined for loyalty tier '{customer.loyalty_tier}'.")
    if proposal.amount > cap:
        raise ValueError(f"Goodwill credit ${proposal.amount:.2f} exceeds the {customer.loyalty_tier} cap of ${cap:.2f}.")
