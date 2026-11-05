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

Demo sign-in (SYNTHETIC, NOT AUTHENTICATION). A customer types a full name and a shared demo code to see their own
orders. This only decides whose synthetic orders the demo shows. It is not identity verification and must never be
described as one; a real service would use email and password. It is limited to a short list of designated demo
profiles, no route returns a customer list, and the session token is sent only in the Authorization header.

Voice handoff: a future voice channel should produce the same SupportIntakeRequest (channel="VOICE") and call the
same receive_intake function. It must not add a second intake contract, resolution path or authorization path.
"""
from __future__ import annotations

import hmac
import secrets
import threading
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .tools import DomainLookupError, _load_json_list, get_order, get_product_listing
from .tracing import append_case_event
from .voice.orders import recent_orders
from .voice.outcome import RESOLVED, case_outcome
from .voice.store import get_case_record, list_cases, register_case

# Damaged item, late or missing delivery, and return. These are the three demo orders from the fixtures.
DEMO_ORDER_REFERENCES: tuple[str, ...] = ("O-1001", "O-1002", "O-1003")

# The designated synthetic demo profiles: Maya Rowe, Jon Park and Anita Lee (the owners of the three demo orders) and
# Penelope Coleman (the prompt-injection demo). Nobody else can sign in, whatever name is typed.
DEMO_CUSTOMER_IDS: tuple[str, ...] = ("C-001", "C-002", "C-003", "C-044")
# One shared demo code, shown on the sign-in page. It is not a secret and not a password.
DEMO_ACCESS_CODE = "COSMO-DEMO"
# One message for every failure (unknown name, not a demo profile, wrong code), so the form reveals nothing.
IDENTIFY_FAILURE = "We couldn't find that account. Check the name and the demo code."
SESSION_REQUIRED = "Your demo session ended. Please sign in again."

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
# A signed-in request really does create a case for the support team, so its receipt says that, and nothing more:
# no promise of an outcome or a time. The note keeps the synthetic-data disclosure (resolution actions are simulated).
CASE_MESSAGE = "Your request was sent to our support team."
CASE_NOTE = "Demo prototype with synthetic data. No real money moves and nothing ships."


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


class SupportIdentifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=80)
    code: str = Field(min_length=1, max_length=40)


class SupportSession(BaseModel):
    """What the page keeps after a demo sign-in: an opaque token and a first name. Never a customer id."""

    model_config = ConfigDict(extra="forbid")

    token: str
    first_name: str


# token -> customer id, in memory for the life of the backend process (a restart signs everyone out).
_SESSIONS: dict[str, str] = {}
_SESSION_LOCK = threading.Lock()


def _normalize_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def identify(request: SupportIdentifyRequest) -> SupportSession:
    """Demo sign-in by full name and the shared demo code, for the designated demo profiles only."""
    wanted = _normalize_name(request.name)
    code_matches = hmac.compare_digest(request.code.strip().upper().encode(), DEMO_ACCESS_CODE.upper().encode())
    match = next(
        (
            record
            for record in _load_json_list("customers.json")
            if record.get("customer_id") in DEMO_CUSTOMER_IDS and _normalize_name(str(record.get("name", ""))) == wanted
        ),
        None,
    )
    if match is None or not code_matches:
        raise CustomerError(401, IDENTIFY_FAILURE)
    token = secrets.token_urlsafe(24)
    with _SESSION_LOCK:
        _SESSIONS[token] = match["customer_id"]
    return SupportSession(token=token, first_name=str(match["name"]).split()[0])


def customer_for_token(authorization: str | None) -> str:
    """The customer id behind an `Authorization: Bearer <token>` header, or a 401. The id is never accepted from a client."""
    scheme, _, value = (authorization or "").partition(" ")
    token = value.strip()
    with _SESSION_LOCK:
        customer_id = _SESSIONS.get(token) if scheme.lower() == "bearer" and token else None
    if customer_id is None:
        raise CustomerError(401, SESSION_REQUIRED)
    return customer_id


def reset_sessions_for_tests() -> None:
    with _SESSION_LOCK:
        _SESSIONS.clear()


def orders_for_customer(customer_id: str) -> list[CustomerOrderSummary]:
    """The signed-in customer's own recent orders (never anyone else's), in the customer-safe shape."""
    return [
        CustomerOrderSummary(
            order_reference=order["order_id"],
            product_name=order["title"],
            order_date=order["order_date"],
            price=order["price"],
            delivery_summary=_DELIVERY_SUMMARY.get(order["delivery_status"], "Delivery status unavailable"),
        )
        for order in recent_orders(customer_id)
    ]


class RequestStatus(str, Enum):
    """Where a customer's request really is. The states come from what the records prove (voice/outcome.py)."""

    RECEIVED = "RECEIVED"  # Request received
    UNDER_REVIEW = "UNDER_REVIEW"  # Under review
    APPROVED = "APPROVED"  # Resolution approved: a person approved it, the actions are not confirmed done
    RESOLVED = "RESOLVED"  # Resolved: approved AND confirmed done
    FOLLOW_UP = "FOLLOW_UP"  # Follow-up required: a person on the team has to act


class CustomerRequestStatus(BaseModel):
    """What a customer may see about one of their own requests. No policy, reasoning, confidence, trace or internal ids.

    The decision, amount and the approved message are only present once the resolution is confirmed done, so the page
    can never show an outcome that has not happened.
    """

    model_config = ConfigDict(extra="forbid")

    reference: str  # the case id: the same one the support team sees
    issue_type: IssueType
    issue_label: str
    order_reference: str
    product_name: str
    status: RequestStatus
    decision: str | None = None
    amount: float | None = None
    message: str | None = None


_ISSUE_FOR_CASE_TYPE = {case_type: issue for issue, case_type in INTERNAL_CASE_TYPE.items()}


def _request_status(case) -> CustomerRequestStatus:
    outcome = case_outcome(case.case_id)
    resolved = outcome.state == RESOLVED
    issue = _ISSUE_FOR_CASE_TYPE.get(case.case_type, IssueType.OTHER)
    try:
        product = get_product_listing(get_order(case.order_id).sku).title
    except DomainLookupError:
        product = ""
    return CustomerRequestStatus(
        reference=case.case_id,
        issue_type=issue,
        issue_label=ISSUE_LABELS[issue],
        order_reference=case.order_id,
        product_name=product,
        status=RequestStatus(outcome.state),
        decision=outcome.decision if resolved else None,
        amount=outcome.amount if resolved else None,
        message=(outcome.message or None) if resolved else None,
    )


def requests_for_customer(customer_id: str) -> list[CustomerRequestStatus]:
    """The signed-in customer's own requests (web form and voice), newest first. Never anyone else's."""
    return [_request_status(case) for case in reversed(list_cases()) if case.customer_id == customer_id]


def request_for_customer(customer_id: str, case_id: str) -> CustomerRequestStatus:
    case = get_case_record(case_id)
    if case is None or case.customer_id != customer_id:
        # The same answer for a request that does not exist and one that belongs to someone else.
        raise CustomerError(404, "That request is not available.")
    return _request_status(case)


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


def _create_case(request: SupportIntakeRequest, customer_id: str) -> CustomerSupportReceipt:
    """A signed-in request creates a real case, through the same runtime-case path the voice agent uses.

    The order must be one of this customer's own offered orders (ownership comes from the session, never from the
    client). The case then appears in the internal queue and goes through the unchanged checkpoint: nothing is proposed,
    decided or executed here. "Something else" has no automated case type and is created for a person to handle.
    """
    order = next((o for o in recent_orders(customer_id) if o["order_id"] == request.order_reference), None)
    if order is None:
        raise CustomerError(404, "That order is not available in this demo.")
    case = register_case(
        order_id=order["order_id"],
        customer_id=customer_id,
        tracking_id=order["tracking_id"],
        case_type=INTERNAL_CASE_TYPE.get(request.issue_type, "OTHER"),
        complaint_text=request.customer_statement,
        channel=request.channel,
    )
    append_case_event(
        case.case_id, "support_case_created", "Support request created a case", channel=request.channel, order_id=order["order_id"]
    )
    return CustomerSupportReceipt(
        reference=case.case_id,
        issue_label=ISSUE_LABELS[request.issue_type],
        customer_status=CustomerStatus.REQUEST_RECEIVED,
        customer_message=CASE_MESSAGE,
        next_step=CASE_NOTE,
    )


def receive_intake(request: SupportIntakeRequest, customer_id: str | None = None) -> CustomerSupportReceipt:
    """Acknowledge one intake. Without a signed-in customer it only validates (the original behaviour: no case, no write).
    With one, it creates a real case for the support team; it still proposes, decides and executes nothing."""
    if customer_id is not None:
        return _create_case(request, customer_id)
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
