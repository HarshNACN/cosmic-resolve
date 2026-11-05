"""HTTP behaviour of the voice endpoints, with fake speech and model services (no network, no audio hardware)."""
import base64
import json
import threading

import pytest
from fastapi.testclient import TestClient

from api import app
from cosmic_resolve.checkpoint import reset_decided_for_tests
from cosmic_resolve.config import SETTINGS
from cosmic_resolve.tools import _load_json_list
from cosmic_resolve.voice import agent_config as cfg
from cosmic_resolve.voice import routes, store
from cosmic_resolve.voice.stt import TranscriptionError

CUSTOMER = "C-002"


class FakeLLM:
    def extract(self, view, utterance):
        return {"case_type": "LATE_DELIVERY"}

    def speak(self, view, utterance):
        yield "I am sorry about that."


class FakeSTT:
    def __init__(self, text="the smart plug", error=None):
        self.text, self.error, self.calls = text, error, []

    def transcribe(self, audio, filename="speech.webm", content_type="audio/webm"):
        self.calls.append((len(audio), filename, content_type))
        if self.error:
            raise self.error
        return self.text


class FakeSpeaker:
    def __init__(self, fail=False):
        self.fail, self.spoken = fail, []

    def synthesize(self, text):
        self.spoken.append(text)
        if self.fail:
            raise RuntimeError("tts down")
        yield b"\x01\x00" * 8, 22050


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(SETTINGS, "trace_path", tmp_path / "trace.jsonl")
    monkeypatch.setenv("CHECKPOINT_WRITES_ENABLED", "true")
    monkeypatch.delenv("VOICE_MULTILINGUAL", raising=False)  # a local .env may switch it on; these tests are English-only
    store.reset()
    routes.reset_services()
    reset_decided_for_tests()
    routes.configure_services(llm=FakeLLM(), stt=FakeSTT(), tts=FakeSpeaker())
    yield
    store.reset()
    routes.reset_services()
    reset_decided_for_tests()


client = TestClient(app)


def events(response):
    assert response.status_code == 200, response.text
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def kinds(evs):
    return [e["type"] for e in evs]


def agent_lines(evs):
    return [e["text"] for e in evs if e["type"] == "agent_sentence"]


def new_session(customer_id=CUSTOMER):
    response = client.post("/voice/sessions", json={"customer_id": customer_id})
    assert response.status_code == 200, response.text
    return response.json()


def turn_text(sid, text):
    return events(client.post(f"/voice/sessions/{sid}/turn", data={"text": text}))


def turn_audio(sid, payload=b"fake-webm-bytes"):
    return client.post(f"/voice/sessions/{sid}/turn", files={"audio": ("speech.webm", payload, "audio/webm")})


# --- Setup and status ------------------------------------------------------------------------------------------------

def test_warmup_reports_what_is_configured():
    status = client.post("/voice/warmup").json()
    assert status["llm"] and status["stt"] and status["tts"]
    assert status["agent"] == cfg.AGENT_NAME


def test_warmup_names_the_missing_settings(monkeypatch):
    routes.reset_services()
    for name in (cfg.ENV_GROQ_KEY, cfg.ENV_STT_MODEL, cfg.ENV_DIALOGUE_PROFILE, cfg.ENV_PIPER_VOICE):
        monkeypatch.delenv(name, raising=False)
    status = client.post("/voice/warmup").json()
    assert (status["llm"], status["stt"], status["tts"]) == (False, False, False)
    problems = " ".join(status["problems"])
    for name in (cfg.ENV_GROQ_KEY, cfg.ENV_DIALOGUE_PROFILE, cfg.ENV_PIPER_VOICE):
        assert name in problems


def test_the_demo_cast_is_offered_with_names_and_order_counts():
    cast = client.get("/voice/callers").json()["callers"]
    assert [c["customer_id"] for c in cast] == list(cfg.DEMO_CALLERS)
    assert cast[0]["name"] == "Jon Park" and all(c["orders"] > 0 and c["tier"] for c in cast)


def test_every_demo_caller_can_reach_the_order_behind_their_demo_case():
    """Guards the demo: if the data changes, a caller must still be able to pick the order the story needs."""
    from cosmic_resolve.voice.orders import recent_orders

    cases = {c["case_id"]: c for c in _load_json_list("cases.json")}
    for case_id in ("C-1001", "C-1002", "C-1028"):  # PRD demo cases 2, 1 and 3
        case = cases[case_id]
        assert case["customer_id"] in cfg.DEMO_CALLERS, f"{case_id}'s customer is not in the demo cast"
        assert case["order_id"] in {o["order_id"] for o in recent_orders(case["customer_id"])}, case_id


def test_create_session_returns_a_snapshot_without_internal_ids():
    snapshot = new_session()
    assert snapshot["customer"]["first_name"] == "Jon"
    assert snapshot["state"] == store.STATE_PICK_ORDER
    assert any(o["title"] == "Smart Plug Mini" for o in snapshot["orders"])
    assert all("tracking_id" not in o for o in snapshot["orders"])


def test_create_session_rejects_unknown_customers_and_extra_fields():
    assert client.post("/voice/sessions", json={"customer_id": "C-9999"}).status_code == 404
    assert client.post("/voice/sessions", json={"customer_id": CUSTOMER, "admin": True}).status_code == 422
    assert client.post("/voice/sessions", json={}).status_code == 422


def test_a_customer_with_no_orders_cannot_start_a_call():
    owners = {o["customer_id"] for o in _load_json_list("orders.json")}
    nobody = next(c["customer_id"] for c in _load_json_list("customers.json") if c["customer_id"] not in owners)
    assert client.post("/voice/sessions", json={"customer_id": nobody}).status_code == 409


def test_unknown_sessions_are_404():
    assert client.get("/voice/sessions/nope").status_code == 404
    assert client.post("/voice/sessions/nope/turn", data={"text": "hi"}).status_code == 404
    assert client.post("/voice/sessions/nope/speak", json={"kind": "greeting"}).status_code == 404


# --- Greeting and turns ----------------------------------------------------------------------------------------------

def test_greeting_streams_text_then_audio_and_only_once():
    sid = new_session()["session_id"]
    evs = events(client.post(f"/voice/sessions/{sid}/speak", json={"kind": "greeting"}))
    assert kinds(evs) == ["agent_sentence", "audio", "state", "done"]
    assert "Jon" in agent_lines(evs)[0]
    audio = next(e for e in evs if e["type"] == "audio")
    assert audio["rate"] == 22050 and base64.b64decode(audio["pcm"]) == b"\x01\x00" * 8
    assert client.post(f"/voice/sessions/{sid}/speak", json={"kind": "greeting"}).status_code == 409


def test_speak_rejects_unknown_kinds():
    sid = new_session()["session_id"]
    assert client.post(f"/voice/sessions/{sid}/speak", json={"kind": "anything"}).status_code == 422


def test_a_turn_needs_exactly_one_input():
    sid = new_session()["session_id"]
    assert client.post(f"/voice/sessions/{sid}/turn", data={}).status_code == 422
    assert client.post(f"/voice/sessions/{sid}/turn", data={"text": "hi", "order_id": "O-1002"}).status_code == 422


def test_a_typed_turn_picks_the_order_and_every_sentence_is_spoken():
    sid = new_session()["session_id"]
    evs = turn_text(sid, "the smart plug")
    assert kinds(evs)[0] == "customer_text" and kinds(evs)[-1] == "done"
    assert "Smart Plug Mini" in agent_lines(evs)[0]
    assert kinds(evs).count("audio") == len(agent_lines(evs))
    assert next(e for e in evs if e["type"] == "state")["session"]["selected_order_id"] == "O-1002"


def test_tapping_an_order_card_selects_it():
    sid = new_session()["session_id"]
    evs = events(client.post(f"/voice/sessions/{sid}/turn", data={"order_id": "O-1002"}))
    assert "Smart Plug Mini" in agent_lines(evs)[0]


def test_a_spoken_turn_is_transcribed_then_handled():
    sid = new_session()["session_id"]
    evs = events(turn_audio(sid))
    assert kinds(evs)[0] == "stage" and evs[0]["stage"] == "transcribing"
    assert next(e for e in evs if e["type"] == "customer_text")["text"] == "the smart plug"
    assert routes._service("stt").calls == [(len(b"fake-webm-bytes"), "speech.webm", "audio/webm")]


def test_silence_or_noise_is_asked_again_without_advancing_the_call():
    routes.configure_services(stt=FakeSTT(text="Thank you."))
    sid = new_session()["session_id"]
    evs = events(turn_audio(sid))
    assert agent_lines(evs) == [cfg.DIDNT_CATCH]
    assert store.get_session(sid).state == store.STATE_PICK_ORDER
    assert "customer_text" not in kinds(evs)


def test_a_speech_service_failure_is_reported_not_crashed():
    routes.configure_services(stt=FakeSTT(error=TranscriptionError("The speech service is busy. Please try again in a moment.")))
    sid = new_session()["session_id"]
    evs = events(turn_audio(sid))
    assert next(e for e in evs if e["type"] == "error")["message"].startswith("The speech service is busy")
    assert kinds(evs)[-1] == "done"


def test_audio_needs_speech_to_text_but_typing_does_not():
    routes.configure_services(stt=None)
    sid = new_session()["session_id"]
    assert turn_audio(sid).status_code == 503
    assert "Smart Plug Mini" in agent_lines(turn_text(sid, "the smart plug"))[0]


def test_oversized_recordings_are_refused():
    sid = new_session()["session_id"]
    assert turn_audio(sid, payload=b"x" * (cfg.MAX_AUDIO_BYTES + 10)).status_code == 413


def test_audio_must_be_a_file_upload():
    sid = new_session()["session_id"]
    assert client.post(f"/voice/sessions/{sid}/turn", data={"audio": "not a file"}).status_code == 422


def test_two_turns_cannot_overlap():
    sid = new_session()["session_id"]
    lock = routes._turn_locks.setdefault(sid, threading.Lock())
    lock.acquire()
    try:
        evs = events(client.post(f"/voice/sessions/{sid}/turn", data={"text": "the smart plug"}))
    finally:
        lock.release()
    assert [e["type"] for e in evs] == ["error", "done"]
    assert store.get_session(sid).transcript == []  # nothing was processed


def test_a_speech_output_failure_still_delivers_the_text():
    routes.configure_services(tts=FakeSpeaker(fail=True))
    sid = new_session()["session_id"]
    evs = turn_text(sid, "the smart plug")
    assert "Smart Plug Mini" in agent_lines(evs)[0]
    assert any(e["type"] == "error" for e in evs) and "audio" not in kinds(evs)


def test_without_a_speaker_the_agent_still_replies_in_text():
    routes.configure_services(tts=None)
    sid = new_session()["session_id"]
    evs = turn_text(sid, "the smart plug")
    assert agent_lines(evs) and "audio" not in kinds(evs)


def test_without_a_model_the_call_still_works_with_keyword_rules():
    routes.configure_services(llm=None)
    sid = new_session()["session_id"]
    turn_text(sid, "the smart plug")
    evs = turn_text(sid, "it never arrived")
    assert store.get_session(sid).case_type == "LATE_DELIVERY" and cfg.EMPATHY_FALLBACK in agent_lines(evs)


# --- A whole call, through the real checkpoint -----------------------------------------------------------------------

def test_a_full_call_from_speech_to_the_spoken_outcome():
    snapshot = new_session()
    sid = snapshot["session_id"]
    events(client.post(f"/voice/sessions/{sid}/speak", json={"kind": "greeting"}))
    turn_text(sid, "the smart plug")
    turn_text(sid, "It never arrived and tracking says it was lost.")
    submitted = turn_text(sid, "yes")
    case_id = next(e for e in submitted if e["type"] == "case_created")["case_id"]
    assert case_id.startswith("V-")

    # The case is now an ordinary case: listed first, loadable, traceable, and proposable.
    listing = client.get("/cases").json()
    assert listing[0]["case_id"] == case_id and listing[0]["channel"] == "VOICE" and len(listing) == 31
    assert client.get(f"/cases/{case_id}").json()["customer_id"] == CUSTOMER
    trace_types = [e["event_type"] for e in client.get(f"/cases/{case_id}/trace").json()]
    assert "voice_case_created" in trace_types

    # Nothing is decided yet, so the call has no outcome and cannot announce one.
    assert client.get(f"/voice/sessions/{sid}").json()["outcome"] is None
    assert client.post(f"/voice/sessions/{sid}/speak", json={"kind": "outcome"}).status_code == 409

    # The associate generates the recommendation and approves it, exactly as for any case.
    proposal = client.post(f"/cases/{case_id}/propose").json()
    assert proposal["status"] == "AWAITING_APPROVAL" and proposal["proposal"]["decision"] == "REPLACE"
    decision = client.post(
        f"/cases/{case_id}/decision",
        json={"action": "APPROVE", "proposal_fingerprint": proposal["proposal_fingerprint"], "reviewer": "Jordan"},
    )
    assert decision.status_code == 200, decision.text

    # The call now knows, and speaks a summary of what ran; the approved message is shown unchanged, never spoken.
    outcome = client.get(f"/voice/sessions/{sid}").json()["outcome"]
    assert outcome["status"] == "APPROVED"
    assert outcome["text"].startswith("Good news: a replacement for your Smart Plug Mini is on its way.")
    assert outcome["text"].endswith("The specialist's full message is on your screen.")
    spoken = events(client.post(f"/voice/sessions/{sid}/speak", json={"kind": "outcome"}))
    assert agent_lines(spoken) == [outcome["text"]] and "audio" in kinds(spoken)
    assert client.get(f"/voice/sessions/{sid}").json()["state"] == store.STATE_CLOSED


def test_a_rejected_case_is_announced_neutrally():
    sid = new_session()["session_id"]
    turn_text(sid, "the smart plug")
    turn_text(sid, "it never arrived")
    case_id = next(e for e in turn_text(sid, "yes") if e["type"] == "case_created")["case_id"]
    proposal = client.post(f"/cases/{case_id}/propose").json()
    client.post(
        f"/cases/{case_id}/decision",
        json={"action": "REJECT", "proposal_fingerprint": proposal["proposal_fingerprint"], "reviewer": "Jordan"},
    )
    assert client.get(f"/voice/sessions/{sid}").json()["outcome"]["text"] == cfg.OUTCOME_REJECTED


def test_voice_cases_do_not_leak_between_tests():
    assert len(client.get("/cases").json()) == 30
