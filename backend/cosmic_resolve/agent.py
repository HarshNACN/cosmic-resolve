from __future__ import annotations

from datetime import date

from .config import ESCALATION_THRESHOLD_USD
from .models import (
    Customer,
    Decision,
    InventoryRecord,
    PolicyClause,
    ResolutionProposal,
    RootCause,
    Shipment,
    SupportCase,
)

# Windows and limits from the US policy book (data/policies.json).
DOA_WINDOW_DAYS = 30
LATE_WINDOW_DAYS = 10
RETURN_WINDOW_DAYS = 30
STORE_CREDIT_RETURN_DAYS = 60
CLAIMS_ESCALATION_THRESHOLD = 3
PROBLEM_STATUSES = {"LOST_IN_TRANSIT", "DELAYED", "RETURNED_TO_SENDER"}


def _days_between(start: str | None, end: str) -> int | None:
    if start is None:
        return None
    return (date.fromisoformat(end[:10]) - date.fromisoformat(start[:10])).days


class ResolutionAgent:
    """Deterministic offline stand-in for the model. Applies the policy book's rules in code.

    Day counts use the case's created_at date, never today's date, so the same case always gets the same answer.
    """

    def generate_proposal(
        self,
        case: SupportCase,
        policy: list[PolicyClause],
        amount: float,
        evidence: list[str],
        root_cause: RootCause,
        *,
        shipment: Shipment | None = None,
        customer: Customer | None = None,
        inventory: InventoryRecord | None = None,
    ) -> ResolutionProposal:
        if not policy:
            raise ValueError("A proposal requires at least one applicable policy clause.")

        decision, escalation_reasons = self._decide(case, amount, shipment, customer, inventory)

        return ResolutionProposal(
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

    def _decide(
        self,
        case: SupportCase,
        amount: float,
        shipment: Shipment | None,
        customer: Customer | None,
        inventory: InventoryRecord | None,
    ) -> tuple[Decision, list[str]]:
        reasons: list[str] = []
        if amount > ESCALATION_THRESHOLD_USD:
            reasons.append(f"Value > ${ESCALATION_THRESHOLD_USD:.0f} threshold")
        if customer is not None and customer.prior_claims_12m >= CLAIMS_ESCALATION_THRESHOLD:
            reasons.append(f"{customer.prior_claims_12m} claims in the prior 12 months (3 or more)")
        if shipment is None:
            return Decision.ESCALATE, reasons + ["No shipment record on file"]

        if case.case_type == "DAMAGED_ON_ARRIVAL":
            checks, remedy = self._damaged_on_arrival(case, shipment, inventory)
        elif case.case_type == "LATE_DELIVERY":
            checks, remedy = self._late_delivery(case, shipment, inventory)
        elif case.case_type == "RETURN_REQUEST":
            checks, remedy = self._return_request(case, shipment)
        else:
            return Decision.ESCALATE, reasons + [f"Unknown case type {case.case_type}"]

        reasons += checks
        if reasons:
            return Decision.ESCALATE, reasons
        return remedy, []

    @staticmethod
    def _damaged_on_arrival(
        case: SupportCase, shipment: Shipment, inventory: InventoryRecord | None
    ) -> tuple[list[str], Decision]:
        reasons: list[str] = []
        if not shipment.customer_photo_provided:
            reasons.append("No customer photo of the damage")
        days = _days_between(shipment.delivered_at, case.created_at)
        if days is None:
            reasons.append("No delivery date on record")
        elif days > DOA_WINDOW_DAYS:
            reasons.append(f"Delivered {days} days ago, outside the {DOA_WINDOW_DAYS}-day damaged-arrival window")
        if inventory is None or inventory.available_quantity == 0:
            reasons.append("No replacement stock available")
        return reasons, Decision.REPLACE

    @staticmethod
    def _late_delivery(
        case: SupportCase, shipment: Shipment, inventory: InventoryRecord | None
    ) -> tuple[list[str], Decision]:
        reasons: list[str] = []
        if shipment.delivered:
            reasons.append("Carrier shows the package as delivered; conflicting evidence needs investigation")
        if shipment.status not in PROBLEM_STATUSES:
            reasons.append(f"Carrier status {shipment.status} does not confirm a loss or delay")
        late_by = _days_between(shipment.expected_delivery_date, case.created_at)
        if late_by is None:
            reasons.append("No expected delivery date on record")
        elif late_by > LATE_WINDOW_DAYS:
            reasons.append(f"{late_by} days past expected delivery, outside the {LATE_WINDOW_DAYS}-day late-delivery window")
        if inventory is None or inventory.available_quantity == 0:
            reasons.append("No replacement stock available")
        return reasons, Decision.REPLACE

    @staticmethod
    def _return_request(case: SupportCase, shipment: Shipment) -> tuple[list[str], Decision]:
        days = _days_between(shipment.delivered_at, case.created_at)
        if days is None:
            return ["No delivery date on record"], Decision.REFUND
        if days <= RETURN_WINDOW_DAYS:
            return [], Decision.REFUND
        if days <= STORE_CREDIT_RETURN_DAYS:
            return [], Decision.STORE_CREDIT
        return [f"Delivered {days} days ago, past the {STORE_CREDIT_RETURN_DAYS}-day return limit"], Decision.REFUND
