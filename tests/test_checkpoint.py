"""Human-checkpoint tests: capability flag, fingerprint, decision endpoint and trace.

Every trace write goes to a temporary file. Checkpoint writes are enabled only inside tests that set
CHECKPOINT_WRITES_ENABLED. The repository traces/ file is never touched.
"""
import json

import pytest
from fastapi.testclient import TestClient

from api import app
from cosmic_resolve import checkpoint, config, workflow
from cosmic_resolve.config import SETTINGS
from cosmic_resolve.model_provider import RuleBasedModelProvider
from cosmic_resolve.models import Decision, ResolutionProposal, RootCause

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Temporary trace file, no checkpoint writes unless a test enables them, and a clean in-process replay set."""
    trace = tmp_path / "trace.jsonl"
    monkeypatch.setattr(SETTINGS, "trace_path", trace)
    monkeypatch.delenv("CHECKPOINT_WRITES_ENABLED", raising=False)
    checkpoint.reset_decided_for_tests()
    yield trace
    checkpoint.reset_decided_for_tests()


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("CHECKPOINT_WRITES_ENABLED", "true")


def _trace_events(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _mock_actions(path):
    return [e for e in _trace_events(path) if e["event_type"] == "mock_action"]


def _fingerprint(case_id: str) -> str:
    return client.post(f"/api/cases/{case_id}/propose").json()["proposal_fingerprint"]


def _decide(target: str, **body):
    payload = {"reviewer": "Jordan", "proposal_fingerprint": _fingerprint(target), "action": "APPROVE"}
    payload.update(body)
    return client.post(f"/api/cases/{target}/decision", json=payload)


# --- Stage A: capability flag ---------------------------------------------------------------------------------

def test_checkpoint_writes_are_disabled_by_default():
    assert config.checkpoint_writes_enabled({}) is False


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "  ", "disabled", "maybe"])
def test_checkpoint_writes_stay_disabled_for_non_true_values(value):
    assert config.checkpoint_writes_enabled({"CHECKPOINT_WRITES_ENABLED": value}) is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", " yes ", "on"])
def test_checkpoint_writes_enable_only_for_explicit_true_values(value):
    assert config.checkpoint_writes_enabled({"CHECKPOINT_WRITES_ENABLED": value}) is True


def test_checkpoint_flag_is_read_at_call_time(monkeypatch):
    monkeypatch.delenv("CHECKPOINT_WRITES_ENABLED", raising=False)
    assert config.checkpoint_writes_enabled() is False
    monkeypatch.setenv("CHECKPOINT_WRITES_ENABLED", "true")
    assert config.checkpoint_writes_enabled() is True


# --- Stage B: fingerprint and propose envelope -----------------------------------------------------------------

def _proposal(case_id="C-1002") -> ResolutionProposal:
    return workflow.propose_resolution(case_id, RuleBasedModelProvider()).proposal


def test_fingerprint_is_stable_for_identical_proposals():
    assert checkpoint.proposal_fingerprint(_proposal()) == checkpoint.proposal_fingerprint(_proposal())


def test_fingerprint_is_a_sha256_hex_digest():
    fingerprint = checkpoint.proposal_fingerprint(_proposal())
    assert len(fingerprint) == 64 and set(fingerprint) <= set("0123456789abcdef")


@pytest.mark.parametrize(
    "update",
    [
        {"amount": 46.0},
        {"decision": Decision.REPLACE},
        {"policy_clause_ids": ["US-GAD-LD-02"]},
        {"escalation_reasons": ["Something else"]},
        {"customer_message_draft": "A different message."},
        {"root_cause": RootCause(category="OTHER", detail="x")},
        {"evidence": ["A different fact"]},
        {"confidence": 0.5},
        {"case_id": "C-1003"},
    ],
)
def test_fingerprint_changes_when_a_bound_field_changes(update):
    base = _proposal()
    assert checkpoint.proposal_fingerprint(base) != checkpoint.proposal_fingerprint(base.model_copy(update=update))


def test_fingerprint_ignores_trace_and_timestamps():
    first = _proposal()
    _trace_only = workflow.propose_resolution("C-1002", RuleBasedModelProvider())  # writes more trace events
    assert checkpoint.proposal_fingerprint(first) == checkpoint.proposal_fingerprint(_trace_only.proposal)


def test_propose_envelope_carries_fingerprint_and_capability_flag():
    body = client.post("/api/cases/C-1002/propose").json()
    assert len(body["proposal_fingerprint"]) == 64
    assert body["checkpoint_writes_enabled"] is False  # default is read-only
    assert body["recommended_action"] is None  # not an escalation


def test_propose_envelope_reports_enabled_capability(enabled):
    assert client.post("/api/cases/C-1002/propose").json()["checkpoint_writes_enabled"] is True


def test_recommended_action_is_returned_only_for_escalations_awaiting_review():
    escalation = client.post("/api/cases/C-1001/propose").json()
    assert escalation["recommended_action"] == "Manual review required: Value > $200 threshold"
    assert client.post("/api/cases/C-1002/propose").json()["recommended_action"] is None


def test_recommended_action_matches_the_escalate_write_payload(enabled):
    run = workflow.apply_approval(
        workflow.propose_resolution("C-1001", RuleBasedModelProvider()),
        _approval_for_test(),
    )
    escalate_action = next(a for a in run.actions if a["action"] == "escalate")
    assert escalate_action["recommended_action"] == workflow.recommended_action_for(run.proposal)


def _approval_for_test():
    from cosmic_resolve.models import ApprovalDecision

    return ApprovalDecision(approved=True, approved_by="Jordan", approval_token="t")


# --- Stages C-G: decision endpoint ------------------------------------------------------------------------------

def test_disabled_checkpoint_returns_403_and_writes_nothing(isolated_state):
    response = _decide("C-1002")
    assert response.status_code == 403
    assert "disabled" in response.json()["detail"].lower()
    assert _mock_actions(isolated_state) == []


def test_disabled_checkpoint_refuses_rejections_too(isolated_state):
    assert _decide("C-1002", action="REJECT").status_code == 403
    assert all(e["event_type"] != "human_decision" for e in _trace_events(isolated_state))


def test_approve_executes_the_correct_gated_writes(enabled, isolated_state):
    response = _decide("C-1002")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "EXECUTED"
    assert body["decision"] == "STORE_CREDIT"
    assert [a["action"] for a in body["executed_actions"]] == ["issue_store_credit", "send_customer_message", "tag_root_cause"]
    assert body["executed_actions"][0]["amount"] == 45.0
    assert "approval_token" not in json.dumps(body)
    assert [e["details"]["payload"]["action"] for e in _mock_actions(isolated_state)] == [
        "issue_store_credit",
        "send_customer_message",
        "tag_root_cause",
    ]


def test_escalation_approval_runs_only_escalate_and_tag(enabled, isolated_state):
    body = _decide("C-1001").json()
    assert body["decision"] == "ESCALATE"
    assert [a["action"] for a in body["executed_actions"]] == ["escalate", "tag_root_cause"]


def test_reject_writes_nothing_and_records_the_reason(enabled, isolated_state):
    response = _decide("C-1002", action="REJECT", note="Customer contacted us directly.")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "REJECTED"
    assert body["executed_actions"] == []
    assert "manual handling" in body["outcome"]
    assert _mock_actions(isolated_state) == []
    decisions = [e for e in _trace_events(isolated_state) if e["event_type"] == "human_decision"]
    assert decisions[-1]["details"]["approved"] is False
    assert decisions[-1]["details"]["notes"] == "Customer contacted us directly."
    assert decisions[-1]["details"]["action"] == "REJECT"


def test_edit_replaces_only_the_customer_message_and_is_revalidated(enabled, isolated_state):
    response = _decide("C-1002", action="EDIT_AND_APPROVE", edited_message="  We are sorry for the delay.  ")
    assert response.status_code == 200
    message = next(e for e in _mock_actions(isolated_state) if e["details"]["payload"]["action"] == "send_customer_message")
    assert message["details"]["payload"]["text"] == "We are sorry for the delay."  # trimmed
    store_credit = next(e for e in _mock_actions(isolated_state) if e["details"]["payload"]["action"] == "issue_store_credit")
    assert store_credit["details"]["payload"]["amount"] == 45.0  # money unchanged


def test_edit_is_refused_for_escalations_because_no_message_is_sent(enabled, isolated_state):
    response = _decide("C-1001", action="EDIT_AND_APPROVE", edited_message="A new message.")
    assert response.status_code == 422
    assert _mock_actions(isolated_state) == []


def test_final_proposal_is_revalidated_before_any_write(enabled, isolated_state, monkeypatch):
    def reject_everything(*_args, **_kwargs):
        raise ValueError("forced validator failure")

    monkeypatch.setattr(checkpoint, "validate_proposal", reject_everything)
    response = _decide("C-1002")
    assert response.status_code == 422
    assert "forced validator failure" in response.json()["detail"]
    assert _mock_actions(isolated_state) == []


def test_wrong_fingerprint_is_refused_with_409_and_writes_nothing(enabled, isolated_state):
    response = _decide("C-1002", proposal_fingerprint="0" * 64)
    assert response.status_code == 409
    assert _mock_actions(isolated_state) == []


def test_fingerprint_of_another_case_is_refused(enabled, isolated_state):
    other = _fingerprint("C-1003")
    response = client.post("/api/cases/C-1002/decision", json={"action": "APPROVE", "reviewer": "Jordan", "proposal_fingerprint": other})
    assert response.status_code == 409
    assert _mock_actions(isolated_state) == []


def test_unknown_case_is_404(enabled):
    response = client.post(
        "/api/cases/NOPE/decision",
        json={"action": "APPROVE", "reviewer": "Jordan", "proposal_fingerprint": "0" * 64},
    )
    assert response.status_code == 404


def test_replay_within_the_process_is_refused_and_writes_nothing_again(enabled, isolated_state):
    assert _decide("C-1002").status_code == 200
    count = len(_mock_actions(isolated_state))
    replay = _decide("C-1002")
    assert replay.status_code == 409
    assert len(_mock_actions(isolated_state)) == count


def test_a_rejected_proposal_cannot_be_approved_afterwards(enabled, isolated_state):
    assert _decide("C-1002", action="REJECT").status_code == 200
    assert _decide("C-1002").status_code == 409
    assert _mock_actions(isolated_state) == []


def test_decision_does_not_depend_on_a_prior_http_propose(enabled, isolated_state):
    fingerprint = checkpoint.proposal_fingerprint(_proposal("C-1002"))  # no /propose request made
    response = client.post(
        "/api/cases/C-1002/decision",
        json={"action": "APPROVE", "reviewer": "Jordan", "proposal_fingerprint": fingerprint},
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    "extra",
    [
        {"decision": "REFUND"},
        {"amount": 999.0},
        {"policy_clause_ids": ["US-FAKE-01"]},
        {"proposal": {"decision": "REFUND"}},
        {"case_id": "C-1003"},
        {"escalation_reasons": []},
    ],
)
def test_client_cannot_replace_decision_amount_clauses_or_proposal(enabled, isolated_state, extra):
    response = _decide("C-1002", **extra)
    assert response.status_code == 422
    assert _mock_actions(isolated_state) == []


@pytest.mark.parametrize(
    "body",
    [
        {"action": "APPROVE"},  # missing fingerprint
        {"action": "APPROVE", "proposal_fingerprint": "xyz", "reviewer": "Jordan"},  # malformed fingerprint
        {"action": "DELETE", "proposal_fingerprint": "0" * 64, "reviewer": "Jordan"},  # unknown action
        {"action": "APPROVE", "proposal_fingerprint": "0" * 64, "reviewer": "   "},  # blank reviewer
        {"action": "APPROVE", "proposal_fingerprint": "0" * 64, "reviewer": "J\x00ordan"},  # control character
        {"action": "APPROVE", "proposal_fingerprint": "0" * 64, "reviewer": "Jordan", "edited_message": "x"},
        {"action": "EDIT_AND_APPROVE", "proposal_fingerprint": "0" * 64, "reviewer": "Jordan"},  # edit without text
        {"action": "EDIT_AND_APPROVE", "proposal_fingerprint": "0" * 64, "reviewer": "Jordan", "edited_message": "   "},
        {"action": "EDIT_AND_APPROVE", "proposal_fingerprint": "0" * 64, "reviewer": "Jordan", "edited_message": "x" * 2001},
        {"action": "REJECT", "proposal_fingerprint": "0" * 64, "reviewer": "Jordan", "note": "n" * 501},
        {"action": "REJECT", "proposal_fingerprint": "0" * 64, "reviewer": "r" * 81},
    ],
)
def test_malformed_requests_return_controlled_4xx(enabled, isolated_state, body):
    response = client.post("/api/cases/C-1002/decision", json=body)
    assert response.status_code == 422
    assert _mock_actions(isolated_state) == []


def test_non_json_body_is_a_controlled_4xx(enabled):
    response = client.post("/api/cases/C-1002/decision", data="not json", headers={"content-type": "application/json"})
    assert 400 <= response.status_code < 500


def test_human_decision_and_actions_executed_are_traced(enabled, isolated_state):
    _decide("C-1002")
    types = [e["event_type"] for e in _trace_events(isolated_state)]
    assert types.index("human_decision") < types.index("actions_executed")
    decision = next(e for e in _trace_events(isolated_state) if e["event_type"] == "human_decision")
    assert decision["details"]["approved_by"] == "Jordan"
    assert decision["details"]["action"] == "APPROVE"
    summary = next(e for e in _trace_events(isolated_state) if e["event_type"] == "actions_executed")
    assert summary["details"]["case_id"] == "C-1002"
    assert [a["action"] for a in summary["details"]["actions"]] == [
        "issue_store_credit",
        "send_customer_message",
        "tag_root_cause",
    ]
    assert summary["details"]["actions"][0]["amount"] == 45.0


def test_actions_executed_summary_contains_no_message_text_or_tokens(enabled, isolated_state):
    _decide("C-1002", action="EDIT_AND_APPROVE", edited_message="Secret-looking marker text 12345")
    summary = next(e for e in _trace_events(isolated_state) if e["event_type"] == "actions_executed")
    text = json.dumps(summary)
    assert "Secret-looking marker" not in text
    assert "approval_token" not in text
    assert "approved_by" not in text


def test_per_case_trace_shows_the_executed_actions(enabled):
    _decide("C-1002")
    events = client.get("/api/cases/C-1002/trace").json()
    assert "actions_executed" in [e["event_type"] for e in events]
    assert "human_decision" in [e["event_type"] for e in events]


def test_per_case_trace_has_no_actions_executed_after_reject(enabled):
    _decide("C-1002", action="REJECT")
    types = [e["event_type"] for e in client.get("/api/cases/C-1002/trace").json()]
    assert "human_decision" in types
    assert "actions_executed" not in types


def test_over_threshold_remains_escalated_after_approval(enabled):
    body = _decide("C-1001").json()
    assert body["decision"] == "ESCALATE"
    assert all(a["action"] not in ("issue_refund", "create_replacement") for a in body["executed_actions"])


def test_response_never_exposes_the_approval_token(enabled):
    text = json.dumps(_decide("C-1002").json())
    assert "approval_token" not in text
