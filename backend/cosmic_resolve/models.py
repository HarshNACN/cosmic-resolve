from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Decision(str, Enum):
    REPLACE = "REPLACE"
    REFUND = "REFUND"
    STORE_CREDIT = "STORE_CREDIT"
    GOODWILL_CREDIT = "GOODWILL_CREDIT"
    ESCALATE = "ESCALATE"


class SupportCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    order_id: str
    customer_id: str
    tracking_id: str
    case_type: str
    market: str
    category: str
    complaint_text: str
    channel: str
    created_at: str
    status: str = "OPEN"


class Customer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str
    name: str
    loyalty_tier: str
    lifetime_value: float = Field(ge=0)
    prior_claims_12m: int = Field(ge=0)
    region: str


class Order(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str
    customer_id: str
    sku: str
    price: float = Field(ge=0)
    order_date: str
    status: str
    fulfillment_region: str = "US"


class Shipment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tracking_id: str
    order_id: str
    carrier: str
    status: str
    expected_delivery_date: str | None = None
    delivered_at: str | None = None
    events: list[str] = Field(default_factory=list)
    delivered: bool = False
    signature_required: bool = False
    customer_photo_provided: bool = False


class InventoryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str
    region: str
    available_quantity: int = Field(ge=0)


class Product(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str
    title: str
    category: str
    market: str
    price: float = Field(ge=0)
    listing_claims: list[str] = Field(default_factory=list)


class PolicyClause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clause_id: str
    market: str
    category: str
    case_type: str
    text: str


class RootCause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    detail: str


class ResolutionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    decision: Decision
    amount: float = Field(ge=0)
    policy_clause_ids: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    escalation_reasons: list[str] = Field(default_factory=list)
    customer_message_draft: str
    root_cause: RootCause

    @field_validator("policy_clause_ids")
    @classmethod
    def policy_clauses_must_be_nonempty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("ResolutionProposal requires at least one policy clause ID.")
        return value


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    approved_by: str
    approval_token: str = Field(min_length=1)
    decision: Decision | None = None
    notes: str = ""

    @model_validator(mode="after")
    def validate_approval(self) -> "ApprovalDecision":
        if self.approved and not self.approval_token:
            raise ValueError("Approved actions require a non-empty approval token.")
        if self.approved and not self.approved_by:
            raise ValueError("Approved actions require an approver name.")
        return self


class CheckpointAction(str, Enum):
    APPROVE = "APPROVE"
    EDIT_AND_APPROVE = "EDIT_AND_APPROVE"
    REJECT = "REJECT"


MAX_REVIEWER_LENGTH = 80
MAX_NOTE_LENGTH = 500
MAX_EDITED_MESSAGE_LENGTH = 2000
_ALLOWED_CONTROL_CHARS = {"\n", "\t"}


def _plain_text(value: str) -> str:
    """Reject control characters. Values are only ever stored and rendered as text, never as markup."""
    if any(ord(ch) < 32 and ch not in _ALLOWED_CONTROL_CHARS for ch in value):
        raise ValueError("Text must not contain control characters.")
    return value


class DecisionRequest(BaseModel):
    """A human's checkpoint decision. The client sends no proposal, decision, amount, or clause IDs.

    The server rebuilds the proposal and checks proposal_fingerprint against it. String fields are trimmed.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: CheckpointAction
    proposal_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer: str = Field(min_length=1, max_length=MAX_REVIEWER_LENGTH)
    note: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)
    edited_message: str | None = Field(default=None, max_length=MAX_EDITED_MESSAGE_LENGTH)

    @field_validator("reviewer", "note", "edited_message")
    @classmethod
    def _plain(cls, value: str | None) -> str | None:
        return None if value is None else _plain_text(value)

    @field_validator("note")
    @classmethod
    def _empty_note_is_absent(cls, value: str | None) -> str | None:
        return value or None

    @model_validator(mode="after")
    def _edit_text_only_for_edit_action(self) -> "DecisionRequest":
        if self.action == CheckpointAction.EDIT_AND_APPROVE:
            if not self.edited_message:
                raise ValueError("edited_message is required for EDIT_AND_APPROVE.")
        elif self.edited_message is not None:
            raise ValueError("edited_message is only allowed for EDIT_AND_APPROVE.")
        return self


class ExecutedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    amount: float | None = None


class DecisionResult(BaseModel):
    """Typed outcome of a checkpoint decision. Deliberately omits the approval token and trace internals."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    action: CheckpointAction
    status: str
    decision: Decision
    executed_actions: list[ExecutedAction] = Field(default_factory=list)
    outcome: str


class TraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: str
    event_type: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def now(cls, event_type: str, message: str, details: dict[str, Any] | None = None) -> "TraceEvent":
        return cls(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=event_type,
            message=message,
            details=details or {},
        )
