from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import DATA_DIR, SETTINGS
from .models import (
    ApprovalDecision,
    Customer,
    Decision,
    InventoryRecord,
    Order,
    PolicyClause,
    Product,
    RootCause,
    Shipment,
    SupportCase,
)
from .tracing import append_trace_event
from .validators import validate_approval


class DomainLookupError(ValueError):
    """Raised when a requested record does not exist in the mock data set."""


class MockWriteError(RuntimeError):
    """Raised when a write action is attempted without a valid approval checkpoint."""


def _load_json_list(file_name: str) -> list[dict[str, Any]]:
    path = DATA_DIR / file_name
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError(f"Expected a list in {file_name}, found {type(payload).__name__}.")
    return payload


def _find_record(records: list[dict[str, Any]], key: str, value: str) -> dict[str, Any]:
    for item in records:
        if item.get(key) == value:
            return item
    raise DomainLookupError(f"Record not found: {key}='{value}'")


def get_case(case_id: str) -> SupportCase:
    record = _find_record(_load_json_list("cases.json"), "case_id", case_id)
    return SupportCase.model_validate(record)


def get_order(order_id: str) -> Order:
    record = _find_record(_load_json_list("orders.json"), "order_id", order_id)
    return Order.model_validate(record)


def get_customer(customer_id: str) -> Customer:
    record = _find_record(_load_json_list("customers.json"), "customer_id", customer_id)
    return Customer.model_validate(record)


def get_shipment(tracking_id: str) -> Shipment:
    record = _find_record(_load_json_list("shipments.json"), "tracking_id", tracking_id)
    return Shipment.model_validate(record)


def check_inventory(sku: str, region: str) -> InventoryRecord:
    records = _load_json_list("inventory.json")
    for record in records:
        if record.get("sku") == sku and record.get("region") == region:
            return InventoryRecord.model_validate(record)
    raise DomainLookupError(f"Inventory not found for sku={sku}, region={region}")


def get_policy(market: str, category: str, case_type: str) -> list[PolicyClause]:
    clauses: list[PolicyClause] = []
    for record in _load_json_list("policies.json"):
        if record.get("market") == market and record.get("category") == category and record.get("case_type") == case_type:
            clauses.append(PolicyClause.model_validate(record))
    if not clauses:
        raise DomainLookupError(f"No policy clauses for market={market}, category={category}, case_type={case_type}")
    return clauses


def get_product_listing(sku: str) -> Product:
    record = _find_record(_load_json_list("products.json"), "sku", sku)
    return Product.model_validate(record)


def _check_write_approval(approval: ApprovalDecision | None, action_name: str) -> None:
    try:
        validate_approval(approval)
    except (TypeError, ValueError) as exc:
        raise MockWriteError(f"{action_name} requires an approved checkpoint: {exc}") from exc


def issue_refund(order_id: str, amount: float, reason: str, approval: ApprovalDecision | None) -> dict[str, Any]:
    _check_write_approval(approval, "issue_refund")
    record = {
        "action": "issue_refund",
        "order_id": order_id,
        "amount": amount,
        "reason": reason,
        "approved_by": approval.approved_by,
    }
    append_trace_event("mock_action", "Refund issued", {"payload": record})
    return record


def create_replacement(order_id: str, sku: str, approval: ApprovalDecision | None) -> dict[str, Any]:
    _check_write_approval(approval, "create_replacement")
    record = {
        "action": "create_replacement",
        "order_id": order_id,
        "sku": sku,
        "approved_by": approval.approved_by,
    }
    append_trace_event("mock_action", "Replacement created", {"payload": record})
    return record


def issue_store_credit(customer_id: str, amount: float, reason: str, approval: ApprovalDecision | None) -> dict[str, Any]:
    _check_write_approval(approval, "issue_store_credit")
    record = {
        "action": "issue_store_credit",
        "customer_id": customer_id,
        "amount": amount,
        "reason": reason,
        "approved_by": approval.approved_by,
    }
    append_trace_event("mock_action", "Store credit issued", {"payload": record})
    return record


def send_customer_message(case_id: str, text: str, approval: ApprovalDecision | None) -> dict[str, Any]:
    _check_write_approval(approval, "send_customer_message")
    record = {
        "action": "send_customer_message",
        "case_id": case_id,
        "text": text,
        "approved_by": approval.approved_by,
    }
    append_trace_event("mock_action", "Customer message queued", {"payload": record})
    return record


def escalate(case_id: str, reasons: list[str], recommended_action: str, approval: ApprovalDecision | None) -> dict[str, Any]:
    _check_write_approval(approval, "escalate")
    record = {
        "action": "escalate",
        "case_id": case_id,
        "reasons": reasons,
        "recommended_action": recommended_action,
        "approved_by": approval.approved_by,
    }
    append_trace_event("mock_action", "Escalation created", {"payload": record})
    return record


def tag_root_cause(case_id: str, category: str, detail: str, approval: ApprovalDecision | None) -> dict[str, Any]:
    _check_write_approval(approval, "tag_root_cause")
    root_cause = RootCause(category=category, detail=detail)
    record = {
        "action": "tag_root_cause",
        "case_id": case_id,
        "root_cause": root_cause.model_dump(),
        "approved_by": approval.approved_by,
    }
    append_trace_event("mock_action", "Root cause tagged", {"payload": record})
    return record
