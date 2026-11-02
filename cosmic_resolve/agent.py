from __future__ import annotations

from .models import Decision, PolicyClause, ResolutionProposal, RootCause, SupportCase


class ResolutionAgent:
    """Minimal deterministic agent stub for the Day 1 starter. This does not call a live model."""

    def generate_proposal(
        self,
        case: SupportCase,
        policy: list[PolicyClause],
        amount: float,
        evidence: list[str],
        root_cause: RootCause,
    ) -> ResolutionProposal:
        if not policy:
            raise ValueError("A proposal requires at least one applicable policy clause.")

        decision = Decision.REPLACE if case.case_type == "DAMAGED_ON_ARRIVAL" else Decision.ESCALATE
        if case.case_type == "LATE_DELIVERY" and amount <= 100:
            decision = Decision.STORE_CREDIT
        if case.case_type == "RETURN_REQUEST" and amount <= 50:
            decision = Decision.REFUND

        if amount > 200:
            escalation_reasons = ["Value > $200 threshold"]
        else:
            escalation_reasons = []

        proposal = ResolutionProposal(
            case_id=case.case_id,
            decision=decision,
            amount=amount,
            policy_clause_ids=[clause.clause_id for clause in policy[:1]],
            evidence=evidence,
            confidence=0.86,
            escalation_reasons=escalation_reasons,
            customer_message_draft="We reviewed your order and are proceeding with a policy-approved resolution.",
            root_cause=root_cause,
        )
        return proposal
