"""The whole journey over HTTP, with the real approval engine: customer -> case -> internal queue -> human approval ->
actual execution -> what the customer is shown and told. Nothing but the voice model, speech and the browser is faked.

The point of the failure test is the rule that an approval is not an execution: if the action fails after the approval,
the customer must not be told a refund or replacement happened.
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
from cosmic_resolve.voice.outcome import APPROVED, FOLLOW_UP, RESOLVED, case_outcome

client = TestClient(app, raise_server_exceptions=False)  # a failing action becomes a 500 response, as it would for a browser


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


def sign_in(name):
    return client.post("/api/support/identify", json={"name": name, "code": customer.DEMO_ACCESS_CODE}).json()["token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def submit_form(token, order, issue, statement="It never arrived and the tracking says it was lost in transit."):
    body = {"order_reference": order, "issue_type": issue, "customer_statement": statement, "channel": "WEB"}
    return client.post("/api/support/requests", json=body, headers=auth(token)).json()["reference"]


def call_and_confirm(token, order_words, complaint):
    session = client.post("/api/voice/sessions", json={}, headers=auth(token)).json()
    sid = session["session_id"]

    def say(text):
        response = client.post(f"/api/voice/sessions/{sid}/turn", data={"text": text})
        return [json.loads(line) for line in response.text.splitlines() if line.strip()]

    say(order_words)
    say(complaint)
    done = say("yes")
    return sid, next(e["case_id"] for e in done if e["type"] == "case_created")


def review_and_approve(case_id, action="APPROVE"):
    proposal = client.post(f"/api/cases/{case_id}/propose").json()
    result = client.post(
        f"/api/cases/{case_id}/decision",
        json={"action": action, "proposal_fingerprint": proposal["proposal_fingerprint"], "reviewer": "Jordan"},
    )
    return proposal, result


def customer_hears(sid):
    """What a caller on hold is told once the page asks for the outcome (the same endpoints the page uses)."""
    snapshot = client.get(f"/api/voice/sessions/{sid}").json()
    if not snapshot["outcome"]:
        return None
    spoken = client.post(f"/api/voice/sessions/{sid}/speak", json={"kind": "outcome"}).text
    return snapshot["outcome"], [json.loads(line) for line in spoken.splitlines() if line.strip()]


def test_a_form_request_and_a_voice_call_both_reach_the_queue_and_resolve_through_the_same_checkpoint():
    jon = sign_in("Jon Park")
    web_id = submit_form(jon, "O-1002", "LATE_OR_MISSING")
    sid, voice_id = call_and_confirm(jon, "the smart plug", "It never arrived and tracking says it was lost.")
    assert web_id.startswith("W-") and voice_id.startswith("V-")

    queue = {c["case_id"]: c for c in client.get("/api/cases").json()}  # what the employee sees
    assert queue[web_id]["channel"] == "WEB" and queue[voice_id]["channel"] == "VOICE"
    assert queue[web_id]["customer_id"] == queue[voice_id]["customer_id"] == "C-002"

    assert customer_hears(sid) is None  # nothing has been decided: Cosmo has nothing to announce
    for case_id in (web_id, voice_id):
        proposal, result = review_and_approve(case_id)
        assert proposal["proposal"]["decision"] == "REPLACE" and result.status_code == 200
        assert [a["action"] for a in result.json()["executed_actions"]] == ["create_replacement", "send_customer_message", "tag_root_cause"]
        outcome = case_outcome(case_id)
        assert outcome.state == RESOLVED and outcome.decision == "REPLACE"  # confirmed by the tools' own records

    status, lines = customer_hears(sid)  # the call, still on hold, is now told the verified result
    assert status["status"] == "APPROVED" and any("replacement" in e["text"].lower() for e in lines if e["type"] == "agent_sentence")


def test_an_approval_whose_action_fails_is_not_announced_and_is_confirmed_only_when_it_finally_succeeds(monkeypatch):
    jon = sign_in("Jon Park")
    sid, case_id = call_and_confirm(jon, "the smart plug", "It never arrived and tracking says it was lost.")
    proposal = client.post(f"/api/cases/{case_id}/propose").json()
    body = {"action": "APPROVE", "proposal_fingerprint": proposal["proposal_fingerprint"], "reviewer": "Jordan"}

    from cosmic_resolve import workflow

    def failing_replacement(*args, **kwargs):
        raise MockWriteError("the replacement system is down")

    with monkeypatch.context() as broken:  # the sabotage lasts only for this one decision
        broken.setattr(workflow, "create_replacement", failing_replacement)
        failed = client.post(f"/api/cases/{case_id}/decision", json=body)
    assert failed.status_code == 500  # the employee sees a failure
    assert case_outcome(case_id).state == APPROVED  # approved, but NOT resolved: no summary was written
    assert customer_hears(sid) is None  # so the customer is told nothing about a replacement

    retried = client.post(f"/api/cases/{case_id}/decision", json=body)  # the same decision can be retried: it never completed
    assert retried.status_code == 200
    assert case_outcome(case_id).state == RESOLVED
    status, _ = customer_hears(sid)
    assert status["status"] == "APPROVED"


def test_a_high_value_case_is_escalated_and_the_customer_is_told_a_person_will_follow_up_not_that_it_is_resolved():
    maya = sign_in("Maya Rowe")
    case_id = submit_form(maya, "O-1001", "DAMAGED_ITEM", "The headphones arrived with a cracked case and one side is dead.")
    proposal, result = review_and_approve(case_id)
    assert proposal["proposal"]["decision"] == "ESCALATE" and result.status_code == 200
    outcome = case_outcome(case_id)
    assert outcome.state == FOLLOW_UP and outcome.reason == "ESCALATED" and outcome.state != RESOLVED


def test_a_rejection_is_a_follow_up_and_executes_nothing():
    jon = sign_in("Jon Park")
    case_id = submit_form(jon, "O-1002", "LATE_OR_MISSING")
    proposal, result = review_and_approve(case_id, "REJECT")
    assert result.status_code == 200 and result.json()["executed_actions"] == []
    outcome = case_outcome(case_id)
    assert outcome.state == FOLLOW_UP and outcome.reason == "REJECTED"
