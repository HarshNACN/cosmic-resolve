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
