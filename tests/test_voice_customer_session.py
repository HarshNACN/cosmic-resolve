"""A signed-in customer opens a voice call with the demo session token, never with a customer id.

The internal workbench and the existing tests still open calls for a chosen caller; the customer page must not.
"""
import json

import pytest
from fastapi.testclient import TestClient

from api import app
from cosmic_resolve import customer
from cosmic_resolve.checkpoint import reset_decided_for_tests
from cosmic_resolve.config import SETTINGS
from cosmic_resolve.tools import _load_json_list
from cosmic_resolve.voice import agent_config as cfg
from cosmic_resolve.voice import routes, store

client = TestClient(app)


class FakeLLM:
    def extract(self, view, utterance):
        return {"case_type": "LATE_DELIVERY"}

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


def token_for(name="Jon Park"):
    return client.post("/api/support/identify", json={"name": name, "code": customer.DEMO_ACCESS_CODE}).json()["token"]


def open_call(token=None, **body):
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return client.post("/api/voice/sessions", json=body, headers=headers)


def stream(response):
    assert response.status_code == 200, response.text
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_the_token_opens_a_call_for_that_customer_with_only_their_own_orders():
    owners = {o["order_id"]: o["customer_id"] for o in _load_json_list("orders.json")}
    response = open_call(token_for("Jon Park"))
    assert response.status_code == 200
    snapshot = response.json()
    assert snapshot["customer"]["first_name"] == "Jon"
    assert snapshot["orders"] and {owners[o["order_id"]] for o in snapshot["orders"]} == {"C-002"}
    assert "tracking_id" not in json.dumps(snapshot)


def test_a_customer_id_is_never_accepted_alongside_a_token_and_a_call_needs_one_or_the_other():
    token = token_for()
    assert open_call(token, customer_id="C-001").status_code == 422  # a token plus an id: refused, not "trusted"
    assert open_call(None).status_code == 422  # neither
    assert open_call("not-a-real-token").status_code == 401
    assert client.post("/api/voice/sessions", json={}, headers={"Authorization": "Basic abc"}).status_code == 401


def test_the_internal_callers_route_still_works_for_a_chosen_caller():
    assert open_call(None, customer_id="C-002").status_code == 200
    assert open_call(None, customer_id="C-999").status_code == 404


def test_a_call_started_from_a_token_creates_a_case_owned_by_that_customer_in_the_queue():
    sid = open_call(token_for("Jon Park")).json()["session_id"]

    def say(text):
        return stream(client.post(f"/api/voice/sessions/{sid}/turn", data={"text": text}))

    say("the smart plug")
    say("It never arrived and tracking says it was lost.")
    done = say("yes")
    case_id = next(e["case_id"] for e in done if e["type"] == "case_created")
    case = client.get(f"/api/cases/{case_id}").json()
    assert case["channel"] == "VOICE" and case["customer_id"] == "C-002" and case["order_id"] == "O-1002"
    assert case_id in [c["case_id"] for c in client.get("/api/cases").json()]


def test_the_starting_language_is_kept_for_a_token_call(monkeypatch):
    monkeypatch.setenv(cfg.ENV_MULTILINGUAL, "true")
    assert open_call(token_for(), language="hi").json()["language"] == "hi"
