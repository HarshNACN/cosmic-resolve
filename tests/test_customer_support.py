"""Customer-support contract tests (DEMO CUSTOMER MODE, synthetic data only).

Tests call the public /api/support routes through the real app. Nothing here is a production access control.
Trace writes go to a temporary file.
"""
import json
import re

import pytest
from fastapi.testclient import TestClient

from api import app
from cosmic_resolve import customer, tools, workflow
from cosmic_resolve.config import SETTINGS

client = TestClient(app)

ORDER_KEYS = {"order_reference", "product_name", "order_date", "price", "delivery_summary"}
RECEIPT_KEYS = {"reference", "issue_label", "customer_status", "customer_message", "next_step"}
FORBIDDEN_IN_CUSTOMER_TEXT = [
    "customer_id",
    "prior_claims",
    "loyalty",
    "lifetime_value",
    "events",
    "clause",
    "policy",
    "confidence",
    "proposal",
    "fingerprint",
    "trace",
    "root_cause",
    "escalation",
    "approval",
    "DAMAGED_ON_ARRIVAL",
    "LATE_DELIVERY",
    "RETURN_REQUEST",
    "PROVIDER_ERROR",
    "VALIDATION_FAILED",
    "AWAITING_APPROVAL",
    "Maya",
    "Jon",
    "Anita",
]


@pytest.fixture(autouse=True)
def isolated_trace(tmp_path, monkeypatch):
    monkeypatch.setattr(SETTINGS, "trace_path", tmp_path / "trace.jsonl")
    return tmp_path / "trace.jsonl"


def _body(**overrides):
    body = {
        "order_reference": "O-1001",
        "issue_type": "DAMAGED_ITEM",
        "customer_statement": "The housing arrived cracked and the box was dented.",
        "channel": "WEB",
    }
    body.update(overrides)
    return body


# --- demo orders -----------------------------------------------------------------------------------------------

def test_demo_orders_are_exactly_the_three_allowlisted_orders():
    response = client.get("/api/support/demo/orders")
    assert response.status_code == 200
    orders = response.json()
    assert [o["order_reference"] for o in orders] == ["O-1001", "O-1002", "O-1003"]


def test_demo_order_fields_are_exactly_the_customer_safe_set():
    for order in client.get("/api/support/demo/orders").json():
        assert set(order) == ORDER_KEYS


def test_demo_orders_come_from_fixtures_and_are_not_fabricated():
    by_ref = {o["order_reference"]: o for o in client.get("/api/support/demo/orders").json()}
    assert by_ref["O-1001"]["product_name"] == "Noise Cancelling Headphones Pro"
    assert by_ref["O-1001"]["price"] == 649.0
    assert by_ref["O-1001"]["order_date"] == "2026-10-25"
    assert by_ref["O-1002"]["product_name"] == "Smart Plug Mini"
    assert by_ref["O-1003"]["product_name"] == "Fitness Watch Elite"


def test_delivery_summary_is_a_customer_phrase_not_a_shipment_status():
    by_ref = {o["order_reference"]: o for o in client.get("/api/support/demo/orders").json()}
    assert by_ref["O-1001"]["delivery_summary"] == "Delivered"
    assert by_ref["O-1002"]["delivery_summary"] == "Not delivered yet"
    assert by_ref["O-1003"]["delivery_summary"] == "Delivered"
    for order in by_ref.values():
        assert "LOST_IN_TRANSIT" not in order["delivery_summary"]


def test_demo_orders_response_leaks_no_internal_or_personal_data():
    text = client.get("/api/support/demo/orders").text
    for token in FORBIDDEN_IN_CUSTOMER_TEXT:
        assert token not in text, token
    assert not re.search(r"C-\d{3}\b", text)  # no internal customer IDs


def test_customer_contract_cannot_list_all_orders_or_cases():
    assert client.get("/api/support/orders").status_code == 404
    assert client.get("/api/support/cases").status_code == 404
    assert client.get("/api/support/cases/C-1001").status_code == 404


def test_only_three_orders_are_returned_even_though_the_fixtures_hold_400():
    assert len(tools._load_json_list("orders.json")) == 400
    assert len(customer.demo_orders()) == 3


# --- intake: validation ----------------------------------------------------------------------------------------

def test_unknown_order_reference_is_rejected_without_revealing_existence():
    unknown = client.post("/api/support/requests", json=_body(order_reference="O-9999"))
    real_but_not_demo = client.post("/api/support/requests", json=_body(order_reference="O-1004"))
    assert unknown.status_code == 404
    assert real_but_not_demo.status_code == 404
    assert unknown.json() == real_but_not_demo.json()


@pytest.mark.parametrize("issue", ["DAMAGED", "CASE_TYPE", "", "damaged_item"])
def test_invalid_issue_type_is_rejected(issue):
    assert client.post("/api/support/requests", json=_body(issue_type=issue)).status_code == 422


@pytest.mark.parametrize("statement", ["", "   ", "short", "x" * 1001])
def test_empty_short_or_overlong_statements_are_rejected(statement):
    assert client.post("/api/support/requests", json=_body(customer_statement=statement)).status_code == 422


def test_statement_is_trimmed_before_length_checks():
    padded = "   " + "The housing arrived cracked." + "   "
    assert client.post("/api/support/requests", json=_body(customer_statement=padded)).status_code == 200


@pytest.mark.parametrize(
    "extra",
    [
        {"decision": "REFUND"},
        {"amount": 999.0},
        {"policy_clause_ids": ["US-GAD-DOA-01"]},
        {"confidence": 1.0},
        {"approval_token": "x"},
        {"approved": True},
        {"case_id": "C-1001"},
        {"customer_id": "C-001"},
        {"fingerprint": "0" * 64},
    ],
)
def test_client_cannot_supply_decisions_policy_amounts_or_approval(extra):
    response = client.post("/api/support/requests", json=_body(**extra))
    assert response.status_code == 422


def test_unsupported_channel_is_rejected():
    assert client.post("/api/support/requests", json=_body(channel="PHONE")).status_code == 422


def test_voice_channel_uses_the_same_contract():
    response = client.post("/api/support/requests", json=_body(channel="VOICE"))
    assert response.status_code == 200


def test_malformed_json_is_a_controlled_client_error():
    response = client.post("/api/support/requests", data="not json", headers={"content-type": "application/json"})
    assert 400 <= response.status_code < 500


# --- intake: receipt --------------------------------------------------------------------------------------------

def test_receipt_fields_are_exactly_the_customer_safe_set():
    receipt = client.post("/api/support/requests", json=_body()).json()
    assert set(receipt) == RECEIPT_KEYS


def test_receipt_leaks_no_internal_terms():
    text = client.post("/api/support/requests", json=_body()).text
    for token in FORBIDDEN_IN_CUSTOMER_TEXT:
        assert token not in text, token


def test_receipt_reference_is_a_display_reference_with_expected_shape():
    receipt = client.post("/api/support/requests", json=_body()).json()
    assert re.fullmatch(r"CR-[0-9A-F]{6}", receipt["reference"])


def test_references_differ_between_requests():
    refs = {client.post("/api/support/requests", json=_body()).json()["reference"] for _ in range(5)}
    assert len(refs) == 5


@pytest.mark.parametrize(
    "issue, label",
    [
        ("DAMAGED_ITEM", "Item arrived damaged"),
        ("LATE_OR_MISSING", "Order is late or missing"),
        ("RETURN_ITEM", "Return an item"),
        ("OTHER", "Something else"),
    ],
)
def test_each_issue_has_a_customer_label(issue, label):
    receipt = client.post("/api/support/requests", json=_body(issue_type=issue)).json()
    assert receipt["issue_label"] == label


def test_every_issue_gets_the_same_intake_only_receipt():
    receipts = [
        client.post("/api/support/requests", json=_body(issue_type=issue)).json()
        for issue in ("DAMAGED_ITEM", "LATE_OR_MISSING", "RETURN_ITEM", "OTHER")
    ]
    assert {r["customer_status"] for r in receipts} == {"REQUEST_RECEIVED"}
    assert {r["customer_message"] for r in receipts} == {"Your request passed intake validation."}
    assert {r["next_step"] for r in receipts} == {customer.DEMO_NOTE}


def test_only_the_intake_only_status_exists():
    assert [status.value for status in customer.CustomerStatus] == ["REQUEST_RECEIVED"]


# Wording that would promise a review, a queue, a notification, a lookup or a response time.
PROMISE_WORDS = [
    "associate",
    "specialist",
    "review",
    "queue",
    "notif",
    "notified",
    "track",
    "lookup",
    "look up",
    "later",
    "get back",
    "respond",
    "within",
    "24 hours",
    "business day",
    "sla",
    "tracking number",
    "case number",
]


def test_receipt_never_promises_review_queue_notification_lookup_or_response_time():
    receipt_text = client.post("/api/support/requests", json=_body()).text.lower()
    for word in PROMISE_WORDS:
        assert word not in receipt_text, word


def test_receipt_uses_reference_and_discloses_the_prototype():
    receipt = client.post("/api/support/requests", json=_body()).json()
    assert "reference" in receipt and "tracking" not in json.dumps(receipt).lower()
    assert "not retained" in receipt["next_step"]
    assert "prototype" in receipt["next_step"].lower()


def test_no_lookup_endpoint_exists_for_references():
    paths = {route.path for route in app.routes}
    assert not any(path.startswith("/support/requests/") for path in paths)
    assert client.get("/api/support/requests/CR-1A2B3C").status_code in (404, 405)
    assert "/support/requests" in paths  # submission only


def test_internal_case_type_mapping_is_deterministic_and_not_in_responses():
    assert customer.INTERNAL_CASE_TYPE[customer.IssueType.DAMAGED_ITEM] == "DAMAGED_ON_ARRIVAL"
    assert customer.INTERNAL_CASE_TYPE[customer.IssueType.LATE_OR_MISSING] == "LATE_DELIVERY"
    assert customer.INTERNAL_CASE_TYPE[customer.IssueType.RETURN_ITEM] == "RETURN_REQUEST"
    assert customer.IssueType.OTHER not in customer.INTERNAL_CASE_TYPE


# --- no resolution, no writes, no trace --------------------------------------------------------------------------

def test_intake_never_proposes_executes_or_traces(isolated_trace, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("customer intake must not call this")

    monkeypatch.setattr(workflow, "propose_resolution", forbidden)
    monkeypatch.setattr(workflow, "apply_approval", forbidden)
    monkeypatch.setattr(tools, "issue_refund", forbidden)
    monkeypatch.setattr(tools, "issue_store_credit", forbidden)
    monkeypatch.setattr(tools, "create_replacement", forbidden)

    for issue in ("DAMAGED_ITEM", "LATE_OR_MISSING", "RETURN_ITEM", "OTHER"):
        assert client.post("/api/support/requests", json=_body(issue_type=issue)).status_code == 200
    assert not isolated_trace.exists() or isolated_trace.read_text(encoding="utf-8").strip() == ""


def test_customer_routes_do_not_expose_decision_or_proposal_endpoints():
    paths = {route.path for route in app.routes}
    assert "/support/requests" in paths and "/support/demo/orders" in paths
    assert not any(p.startswith("/support/") and ("decision" in p or "propose" in p or "trace" in p) for p in paths)


def test_error_responses_do_not_echo_the_statement_or_internal_detail():
    response = client.post("/api/support/requests", json=_body(order_reference="O-9999", customer_statement="secret-marker-text here"))
    assert response.status_code == 404
    assert "secret-marker" not in response.text
    json.loads(response.text)  # well-formed JSON
