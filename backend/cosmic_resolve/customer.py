"""Customer-facing support contract for the hackathon demo.

DEMO CUSTOMER MODE. There is no authentication in this repository. The orders below are a hard-coded allowlist of
three synthetic fixture orders, chosen for the demo. This is not customer identity verification and must not be
described as one. Nothing here is a production access control.

Boundaries:
- Customer responses use the dedicated models in this module. Internal models (SupportCase, ResolutionProposal,
  Customer with prior claims, Shipment events, DecisionResult, traces) are never returned to customers.
- Submitting a request validates it and returns a receipt for that interaction. It does not generate a
  proposal, does not change any case, and never executes a write. Consequential resolution stays with the
  associate checkpoint.
- Nothing is persisted. A receipt cannot be looked up later. The reference is for display only.

Voice handoff: a future voice channel should produce the same SupportIntakeRequest (channel="VOICE") and call the
same receive_intake function. It must not add a second intake contract, resolution path or authorization path.
"""
from __future__ import annotations

import secrets
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .tools import DomainLookupError, _load_json_list, get_order, get_product_listing

# Damaged item, late or missing delivery, and return. These are the three demo orders from the fixtures.
DEMO_ORDER_REFERENCES: tuple[str, ...] = ("O-1001", "O-1002", "O-1003")

MIN_STATEMENT_LENGTH = 10
MAX_STATEMENT_LENGTH = 1000


class CustomerError(Exception):
    """A controlled customer-facing failure. The API maps it to the status code and detail."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class IssueType(str, Enum):
    DAMAGED_ITEM = "DAMAGED_ITEM"
    LATE_OR_MISSING = "LATE_OR_MISSING"
    RETURN_ITEM = "RETURN_ITEM"
    OTHER = "OTHER"


class CustomerStatus(str, Enum):
    # Intake validation only. The demo does not route, store or notify anyone, so no review status exists here.
    REQUEST_RECEIVED = "REQUEST_RECEIVED"


# Receipt copy. It states what happened in this interaction and nothing more: no review, queue, notification,
# lookup or response time. The demo note is part of the receipt so every client shows the same disclosure.
RECEIPT_MESSAGE = "Your request passed intake validation."
DEMO_NOTE = "Demo prototype. Submitted requests are not retained in this prototype."


ISSUE_LABELS: dict[IssueType, str] = {
    IssueType.DAMAGED_ITEM: "Item arrived damaged",
    IssueType.LATE_OR_MISSING: "Order is late or missing",
    IssueType.RETURN_ITEM: "Return an item",
    IssueType.OTHER: "Something else",
}

# Internal routing hint only. Never returned to customers. OTHER has no automated mapping and goes to a specialist.
INTERNAL_CASE_TYPE: dict[IssueType, str] = {
    IssueType.DAMAGED_ITEM: "DAMAGED_ON_ARRIVAL",
    IssueType.LATE_OR_MISSING: "LATE_DELIVERY",
    IssueType.RETURN_ITEM: "RETURN_REQUEST",
}

_DELIVERY_SUMMARY = {
    "DELIVERED": "Delivered",
    "DELAYED": "On the way",
    "IN_TRANSIT": "On the way",
    "LOST_IN_TRANSIT": "Not delivered yet",
    "RETURNED_TO_SENDER": "Not delivered yet",
}


class CustomerOrderSummary(BaseModel):
    """What a customer may see about one order. Deliberately excludes customer IDs, claims, tiers and events."""

    model_config = ConfigDict(extra="forbid")

    order_reference: str
    product_name: str
    order_date: str
    price: float
    delivery_summary: str


class SupportIntakeRequest(BaseModel):
    """The shared intake payload. Web forms and a future voice channel both produce this model."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    order_reference: str = Field(min_length=1, max_length=32)
    issue_type: IssueType
    customer_statement: str = Field(min_length=MIN_STATEMENT_LENGTH, max_length=MAX_STATEMENT_LENGTH)
    channel: Literal["WEB", "VOICE"] = "WEB"


class CustomerSupportReceipt(BaseModel):
    """The result of one intake interaction. No resolution, policy, confidence, trace or internal status."""

    model_config = ConfigDict(extra="forbid")

    reference: str
    issue_label: str
    customer_status: CustomerStatus
    customer_message: str
    next_step: str


def _shipment_for_order(order_id: str) -> dict | None:
    for shipment in _load_json_list("shipments.json"):
        if shipment.get("order_id") == order_id:
            return shipment
    return None


def _order_summary(order_id: str) -> CustomerOrderSummary:
    order = get_order(order_id)
    product = get_product_listing(order.sku)
    shipment = _shipment_for_order(order_id)
    status = shipment.get("status") if shipment else None
    return CustomerOrderSummary(
        order_reference=order.order_id,
        product_name=product.title,
        order_date=order.order_date[:10],
        price=order.price,
        delivery_summary=_DELIVERY_SUMMARY.get(status, "Delivery status unavailable"),
    )


def demo_orders() -> list[CustomerOrderSummary]:
    """The allowlisted demo orders only. Never the full order set."""
    return [_order_summary(reference) for reference in DEMO_ORDER_REFERENCES]


def _new_reference() -> str:
    # Display reference only. It is random and not durable, and nothing looks it up.
    return f"CR-{secrets.token_hex(3).upper()}"


def receive_intake(request: SupportIntakeRequest) -> CustomerSupportReceipt:
    """Validate and acknowledge one intake. Creates no proposal, no case change and no write."""
    if request.order_reference not in DEMO_ORDER_REFERENCES:
        # Same message for unknown and non-demo orders, so the endpoint does not reveal which orders exist.
        raise CustomerError(404, "That order is not available in this demo.")
    try:
        get_order(request.order_reference)
    except DomainLookupError as exc:
        raise CustomerError(404, "That order is not available in this demo.") from exc

    # Every valid request gets the same receipt semantics. Routing by issue type is not a persisted queue.
    return CustomerSupportReceipt(
        reference=_new_reference(),
        issue_label=ISSUE_LABELS[request.issue_type],
        customer_status=CustomerStatus.REQUEST_RECEIVED,
        customer_message=RECEIPT_MESSAGE,
        next_step=DEMO_NOTE,
    )
