"""Boundary checks for the offline rule-based agent (policy windows, photo, claims, stock, carrier conflicts)."""
from cosmic_resolve.agent import ResolutionAgent
from cosmic_resolve.models import (
    Customer,
    Decision,
    InventoryRecord,
    RootCause,
    Shipment,
    SupportCase,
)

CREATED = "2026-11-02T09:00:00Z"


def _case(case_type: str) -> SupportCase:
    return SupportCase(
        case_id="C-T", order_id="O-T", customer_id="C-T", tracking_id="T-T", case_type=case_type,
        market="US", category="GADGETS", complaint_text="test", channel="CHAT", created_at=CREATED,
    )


def _customer(claims: int = 0, tier: str = "SILVER") -> Customer:
    return Customer(customer_id="C-T", name="Test", loyalty_tier=tier, lifetime_value=0, prior_claims_12m=claims, region="US")


def _shipment(**overrides) -> Shipment:
    data = dict(
        tracking_id="T-T", order_id="O-T", carrier="UPS", status="DELIVERED",
        expected_delivery_date=None, delivered_at=None, events=["event"], delivered=True,
        signature_required=False, customer_photo_provided=True,
    )
    data.update(overrides)
    return Shipment(**data)


def _decide(case_type, shipment, *, amount=45.0, customer=None, inventory=None):
    proposal = ResolutionAgent().generate_proposal(
        _case(case_type), [_policy(case_type)], amount, ["evidence"],
        RootCause(category="X", detail="x"),
        shipment=shipment, customer=customer or _customer(), inventory=inventory or _stock(),
    )
    return proposal.decision, proposal.escalation_reasons


def _policy(case_type):
    from cosmic_resolve.models import PolicyClause
    return PolicyClause(clause_id="US-T", market="US", category="GADGETS", case_type=case_type, text="t")


def _stock(quantity: int = 5) -> InventoryRecord:
    return InventoryRecord(sku="S", region="US", available_quantity=quantity)


def test_damaged_arrival_inside_30_days_with_photo_replaces():
    assert _decide("DAMAGED_ON_ARRIVAL", _shipment(delivered_at="2026-10-03"))[0] == Decision.REPLACE


def test_damaged_arrival_31_days_escalates():
    decision, reasons = _decide("DAMAGED_ON_ARRIVAL", _shipment(delivered_at="2026-10-02"))
    assert decision == Decision.ESCALATE
    assert any("30-day" in r for r in reasons)


def test_damaged_arrival_without_photo_escalates():
    decision, _ = _decide("DAMAGED_ON_ARRIVAL", _shipment(delivered_at="2026-10-30", customer_photo_provided=False))
    assert decision == Decision.ESCALATE


def test_damaged_arrival_without_stock_escalates():
    decision, reasons = _decide("DAMAGED_ON_ARRIVAL", _shipment(delivered_at="2026-10-30"), inventory=_stock(0))
    assert decision == Decision.ESCALATE
    assert "No replacement stock available" in reasons


def test_late_delivery_10_days_past_expected_replaces():
    shipment = _shipment(status="LOST_IN_TRANSIT", delivered=False, expected_delivery_date="2026-10-23")
    assert _decide("LATE_DELIVERY", shipment)[0] == Decision.REPLACE


def test_late_delivery_11_days_past_expected_escalates():
    shipment = _shipment(status="LOST_IN_TRANSIT", delivered=False, expected_delivery_date="2026-10-22")
    decision, reasons = _decide("LATE_DELIVERY", shipment)
    assert decision == Decision.ESCALATE
    assert any("10-day" in r for r in reasons)


def test_late_delivery_shown_as_delivered_escalates():
    shipment = _shipment(status="DELIVERED", delivered=True, expected_delivery_date="2026-10-30")
    decision, reasons = _decide("LATE_DELIVERY", shipment)
    assert decision == Decision.ESCALATE
    assert any("conflicting" in r for r in reasons)


def test_return_inside_30_days_refunds():
    assert _decide("RETURN_REQUEST", _shipment(delivered_at="2026-10-03"))[0] == Decision.REFUND


def test_return_31_to_60_days_gives_store_credit():
    assert _decide("RETURN_REQUEST", _shipment(delivered_at="2026-10-02"))[0] == Decision.STORE_CREDIT


def test_return_after_60_days_escalates():
    decision, reasons = _decide("RETURN_REQUEST", _shipment(delivered_at="2026-09-02"))
    assert decision == Decision.ESCALATE
    assert any("60-day" in r for r in reasons)


def test_three_claims_escalate_any_case_type():
    decision, reasons = _decide("RETURN_REQUEST", _shipment(delivered_at="2026-10-30"), customer=_customer(claims=3))
    assert decision == Decision.ESCALATE
    assert any("3 or more" in r for r in reasons)


def test_over_200_escalates():
    decision, reasons = _decide("RETURN_REQUEST", _shipment(delivered_at="2026-10-30"), amount=201.0)
    assert decision == Decision.ESCALATE
    assert any("threshold" in r for r in reasons)
