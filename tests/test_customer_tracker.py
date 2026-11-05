"""The customer's request tracker: verified progress only, their own requests only, nothing internal.

Statuses (see voice/outcome.py): RECEIVED, UNDER_REVIEW, APPROVED (approved, actions not confirmed), RESOLVED (confirmed
done), FOLLOW_UP (a person must act). The decision, amount and approved message appear only once RESOLVED.
"""
import json

import pytest
from fastapi.testclient import TestClient

from api import app
from cosmic_resolve import customer
from cosmic_resolve.checkpoint import reset_decided_for_tests
from cosmic_resolve.config import SETTINGS
from cosmic_resolve.tools import MockWriteError
from cosmic_resolve.voice import agent_config as cfg
from cosmic_resolve.voice import routes, store
from cosmic_resolve.voice.orders import recent_orders
from voice_events import approve, run_actions

client = TestClient(app, raise_server_exceptions=False)
ALLOWED_KEYS = {"reference", "issue_type", "issue_label", "order_reference", "product_name", "status", "decision", "amount", "message"}


class FakeLLM:
    def extract(self, view, utterance):
        return {}

    def speak(self, view, utterance):
        yield "I am sorry about that."


class FakeSpeaker:
    def synthesize(self, text, language="en"):
        yield b"\x01\x00" * 8, 22050


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(SETTINGS, "trace_path", tmp_path / "trace.jsonl")
    monkeypatch.setenv("CHECKPOINT_WRITES_ENABLED", "true")
    monkeypatch.delenv(cfg.ENV_MULTILINGUAL, raising=False)
    store.reset()
    routes.reset_services()
    customer.reset_sessions_for_tests()
    reset_decided_for_tests()
    routes.configure_services(llm=FakeLLM(), stt=None, tts=FakeSpeaker())
    yield
    store.reset()
    routes.reset_services()
    customer.reset_sessions_for_tests()
    reset_decided_for_tests()


def sign_in(name="Jon Park"):
    return client.post("/api/support/identify", json={"name": name, "code": customer.DEMO_ACCESS_CODE}).json()["token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def submit(token, order="O-1002", issue="LATE_OR_MISSING"):
    body = {"order_reference": order, "issue_type": issue, "customer_statement": "It never arrived and tracking says it was lost.", "channel": "WEB"}
    return client.post("/api/support/requests", json=body, headers=auth(token)).json()["reference"]


def status(token, case_id):
    response = client.get(f"/api/support/my/requests/{case_id}", headers=auth(token))
    assert response.status_code == 200, response.text
    return response.json()


def case(case_id):
    return store.get_case_record(case_id)


def propose_and_decide(case_id, action="APPROVE"):
    proposal = client.post(f"/api/cases/{case_id}/propose").json()
    return client.post(
        f"/api/cases/{case_id}/decision",
        json={"action": action, "proposal_fingerprint": proposal["proposal_fingerprint"], "reviewer": "Jordan"},
    )


def test_a_request_moves_through_the_states_as_the_real_engine_acts():
    jon = sign_in()
    case_id = submit(jon)
    first = status(jon, case_id)
    assert first["status"] == "RECEIVED" and first["reference"] == case_id
    assert (first["decision"], first["amount"], first["message"]) == (None, None, None)

    client.post(f"/api/cases/{case_id}/propose")  # an associate generates the recommendation
    assert status(jon, case_id)["status"] == "UNDER_REVIEW"

    result = propose_and_decide(case_id)
    assert result.status_code == 200
    done = status(jon, case_id)
    assert done["status"] == "RESOLVED" and done["decision"] == "REPLACE" and done["amount"] is None
    assert done["message"] and done["product_name"] == "Smart Plug Mini" and done["issue_type"] == "LATE_OR_MISSING"


def test_an_approval_is_not_shown_as_resolved_until_the_action_is_confirmed_and_no_outcome_leaks_before_then(monkeypatch):
    jon = sign_in()
    case_id = submit(jon)
    proposal = client.post(f"/api/cases/{case_id}/propose").json()
    body = {"action": "APPROVE", "proposal_fingerprint": proposal["proposal_fingerprint"], "reviewer": "Jordan"}

    from cosmic_resolve import workflow

    def down(*args, **kwargs):
        raise MockWriteError("the replacement system is down")

    with monkeypatch.context() as broken:
        broken.setattr(workflow, "create_replacement", down)
        assert client.post(f"/api/cases/{case_id}/decision", json=body).status_code == 500
    held = status(jon, case_id)
    assert held["status"] == "APPROVED"  # approved, not resolved
    assert (held["decision"], held["amount"], held["message"]) == (None, None, None)  # nothing is claimed that has not happened

    assert client.post(f"/api/cases/{case_id}/decision", json=body).status_code == 200
    assert status(jon, case_id)["status"] == "RESOLVED"


def test_a_refund_shows_its_confirmed_amount_and_a_rejection_or_escalation_is_a_follow_up():
    jon = sign_in()
    refunded = submit(jon)
    run_actions(refunded, case(refunded).order_id, case(refunded).customer_id, "REFUND", "Your refund is on its way.", 45.0)
    got = status(jon, refunded)
    assert got["status"] == "RESOLVED" and got["decision"] == "REFUND" and got["amount"] == 45.0 and got["message"] == "Your refund is on its way."

    rejected = submit(jon)
    run_actions(rejected, case(rejected).order_id, case(rejected).customer_id, "REPLACE", approved=False)
    escalated = submit(jon)
    run_actions(escalated, case(escalated).order_id, case(escalated).customer_id, "ESCALATE")
    for case_id in (rejected, escalated):
        seen = status(jon, case_id)
        assert seen["status"] == "FOLLOW_UP" and (seen["decision"], seen["amount"], seen["message"]) == (None, None, None)


def test_only_the_customers_own_requests_are_listed_newest_first_and_others_look_like_nothing():
    jon, maya = sign_in("Jon Park"), sign_in("Maya Rowe")
    first = submit(jon)
    second = submit(jon)
    hers = submit(maya, order=recent_orders("C-001")[0]["order_id"])
    mine = client.get("/api/support/my/requests", headers=auth(jon)).json()
    assert [r["reference"] for r in mine] == [second, first]
    assert [r["reference"] for r in client.get("/api/support/my/requests", headers=auth(maya)).json()] == [hers]

    other = client.get(f"/api/support/my/requests/{hers}", headers=auth(jon))
    missing = client.get("/api/support/my/requests/W-9999", headers=auth(jon))
    assert other.status_code == missing.status_code == 404 and other.json() == missing.json()  # indistinguishable


def test_voice_cases_appear_in_the_same_tracker_as_form_requests():
    jon = sign_in()
    session = client.post("/api/voice/sessions", json={}, headers=auth(jon)).json()
    sid = session["session_id"]
    for said in ("the smart plug", "It never arrived and tracking says it was lost.", "yes"):
        client.post(f"/api/voice/sessions/{sid}/turn", data={"text": said})
    listed = client.get("/api/support/my/requests", headers=auth(jon)).json()
    assert len(listed) == 1 and listed[0]["reference"].startswith("V-") and listed[0]["status"] == "RECEIVED"


def test_a_token_is_required_in_the_header_and_never_in_the_url():
    jon = sign_in()
    case_id = submit(jon)
    assert client.get("/api/support/my/requests").status_code == 401
    assert client.get(f"/api/support/my/requests/{case_id}").status_code == 401
    assert client.get(f"/api/support/my/requests?token={jon}").status_code == 401
    assert client.get("/api/support/my/requests", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/api/support/cases").status_code == 404  # the old paths stay closed
    assert client.get(f"/api/support/cases/{case_id}").status_code == 404


def test_nothing_internal_is_ever_in_the_customers_view():
    jon = sign_in()
    case_id = submit(jon)
    run = client.post(f"/api/cases/{case_id}/propose").json()
    propose_and_decide(case_id)
    seen = status(jon, case_id)
    assert set(seen) == ALLOWED_KEYS
    # the one free-text field is the message the associate approved for the customer; every other field is checked for internals
    assert seen["message"] == run["proposal"]["customer_message_draft"]
    structured = json.dumps({k: v for k, v in seen.items() if k != "message"}) + json.dumps(
        [{k: v for k, v in r.items() if k != "message"} for r in client.get("/api/support/my/requests", headers=auth(jon)).json()]
    )
    for forbidden in ("customer_id", "C-002", "policy", "confidence", "fingerprint", "proposal", "escalation", "reasoning", "trace", "approved_by", "Jordan", "root_cause", "DAMAGED_ON_ARRIVAL", "LATE_DELIVERY"):
        assert forbidden not in structured, forbidden
