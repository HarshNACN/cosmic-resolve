"""The signed-in support form creates a real case, through the same runtime-case path the voice agent uses.

Anonymous requests keep their original validation-only behaviour (tests/test_customer_support.py). Nothing here
proposes, decides or executes anything at intake: the case waits in the internal queue for a person.
"""
import pytest
from fastapi.testclient import TestClient

from api import app
from cosmic_resolve import customer
from cosmic_resolve.checkpoint import reset_decided_for_tests
from cosmic_resolve.config import SETTINGS
from cosmic_resolve.tracing import read_trace_events
from cosmic_resolve.voice import store
from cosmic_resolve.voice.orders import recent_orders

client = TestClient(app)
RECEIPT_KEYS = {"reference", "issue_label", "customer_status", "customer_message", "next_step"}
STATEMENT = "The smart plug never arrived and tracking says it was lost in transit."


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(SETTINGS, "trace_path", tmp_path / "trace.jsonl")
    monkeypatch.setenv("CHECKPOINT_WRITES_ENABLED", "true")
    store.reset()
    customer.reset_sessions_for_tests()
    reset_decided_for_tests()
    yield
    store.reset()
    customer.reset_sessions_for_tests()
    reset_decided_for_tests()


def token_for(name="Jon Park"):
    return client.post("/api/support/identify", json={"name": name, "code": customer.DEMO_ACCESS_CODE}).json()["token"]


def submit(token=None, order="O-1002", issue="LATE_OR_MISSING", statement=STATEMENT, **extra):
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    body = {"order_reference": order, "issue_type": issue, "customer_statement": statement, "channel": "WEB", **extra}
    return client.post("/api/support/requests", json=body, headers=headers)


def events_for(case_id):
    return [e for e in read_trace_events() if e.details.get("case_id") == case_id]


def test_a_signed_in_request_creates_a_case_that_reaches_the_internal_queue():
    response = submit(token_for())
    assert response.status_code == 200
    receipt = response.json()
    assert set(receipt) == RECEIPT_KEYS and receipt["reference"] == "W-0001"
    assert receipt["customer_message"] == customer.CASE_MESSAGE and receipt["next_step"] == customer.CASE_NOTE
    assert receipt["issue_label"] == "Order is late or missing" and receipt["customer_status"] == "REQUEST_RECEIVED"

    queue = client.get("/api/cases").json()
    case = queue[0]  # runtime cases come first, newest on top
    assert case["case_id"] == "W-0001" and case["channel"] == "WEB"
    assert case["customer_id"] == "C-002" and case["order_id"] == "O-1002" and case["case_type"] == "LATE_DELIVERY"
    assert case["complaint_text"] == STATEMENT  # the customer's own words, untouched
    assert case["status"] == "OPEN" and len(queue) == 31  # the 30 fixture cases plus this one
    assert client.get("/api/cases/W-0001").json()["case_id"] == "W-0001"


def test_intake_only_records_the_case_and_executes_nothing():
    submit(token_for())
    types = [e.event_type for e in events_for("W-0001")]
    assert types == ["support_case_created"]
    assert not [e for e in read_trace_events() if e.event_type in ("human_decision", "mock_action", "actions_executed")]


@pytest.mark.parametrize(
    "issue, case_type",
    [("DAMAGED_ITEM", "DAMAGED_ON_ARRIVAL"), ("LATE_OR_MISSING", "LATE_DELIVERY"), ("RETURN_ITEM", "RETURN_REQUEST"), ("OTHER", "OTHER")],
)
def test_each_issue_maps_to_the_internal_case_type_and_something_else_is_left_for_a_person(issue, case_type):
    assert submit(token_for(), issue=issue).status_code == 200
    assert client.get("/api/cases/W-0001").json()["case_type"] == case_type


def test_a_customer_can_only_open_a_case_for_their_own_offered_orders():
    jon = token_for("Jon Park")
    maya_order = recent_orders("C-001")[0]["order_id"]
    for order in (maya_order, "O-9999", "not-an-order"):
        response = submit(jon, order=order)
        assert response.status_code == 404 and response.json()["detail"] == "That order is not available in this demo."
    assert len(client.get("/api/cases").json()) == 30  # nothing was created


def test_a_bad_or_unknown_token_is_refused_and_never_falls_back_to_anonymous():
    for token in ("not-a-real-token", ""):
        assert client.post("/api/support/requests", headers={"Authorization": f"Bearer {token}"}, json={
            "order_reference": "O-1002", "issue_type": "LATE_OR_MISSING", "customer_statement": STATEMENT, "channel": "WEB"}).status_code == 401
    assert len(client.get("/api/cases").json()) == 30


def test_an_anonymous_request_still_only_validates_and_creates_no_case():
    response = submit(None, order="O-1002")
    assert response.status_code == 200
    receipt = response.json()
    assert receipt["customer_message"] == customer.RECEIPT_MESSAGE and receipt["next_step"] == customer.DEMO_NOTE
    assert receipt["reference"].startswith("CR-")
    assert len(client.get("/api/cases").json()) == 30


def test_web_and_voice_cases_share_one_numbering_and_one_store():
    submit(token_for())
    voice = store.register_case(order_id="O-1002", customer_id="C-002", tracking_id="T", case_type="LATE_DELIVERY", complaint_text="spoken")
    submit(token_for("Maya Rowe"), order=recent_orders("C-001")[0]["order_id"])
    assert [c["case_id"] for c in client.get("/api/cases").json()[:3]] == ["W-0003", "V-0002", "W-0001"]
    assert voice.channel == "VOICE"
    assert {c["channel"] for c in client.get("/api/cases").json()[:3]} == {"WEB", "VOICE"}


def test_numbering_continues_after_a_restart_because_the_case_creation_is_in_the_trace():
    submit(token_for())
    store.reset()  # a backend restart forgets the in-memory case, but the trace file remains
    assert submit(token_for()).json()["reference"] == "W-0002"


def test_a_web_case_goes_through_the_unchanged_approval_engine_to_an_executed_replacement():
    receipt = submit(token_for()).json()
    case_id = receipt["reference"]
    proposal = client.post(f"/api/cases/{case_id}/propose").json()
    assert proposal["status"] == "AWAITING_APPROVAL" and proposal["proposal"]["decision"] == "REPLACE"
    result = client.post(
        f"/api/cases/{case_id}/decision",
        json={"action": "APPROVE", "proposal_fingerprint": proposal["proposal_fingerprint"], "reviewer": "Jordan"},
    )
    assert result.status_code == 200
    assert [a["action"] for a in result.json()["executed_actions"]] == ["create_replacement", "send_customer_message", "tag_root_cause"]
    types = [e.event_type for e in events_for(case_id)]
    assert types[0] == "support_case_created" and "human_decision" in types and types[-1] == "actions_executed"


def test_the_customer_receipt_and_the_queue_never_expose_internal_fields_to_the_customer():
    response = submit(token_for())
    for forbidden in ("customer_id", "C-002", "proposal", "policy", "confidence", "fingerprint", "trace"):
        assert forbidden not in response.text, forbidden
