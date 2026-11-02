import json

import pytest

from cosmic_resolve import workflow
from cosmic_resolve.config import SETTINGS
from cosmic_resolve.model_provider import NoopModelProvider, RuleBasedModelProvider
from cosmic_resolve.models import ApprovalDecision, Decision

PROVIDER = RuleBasedModelProvider()


@pytest.fixture(autouse=True)
def trace_file(tmp_path, monkeypatch):
    path = tmp_path / "trace.jsonl"
    monkeypatch.setattr(SETTINGS, "trace_path", path)
    return path


def _approval(approved=True, decision=None):
    return ApprovalDecision(approved=approved, approved_by="Jordan", approval_token="tok-1", decision=decision)


def _event_types(path):
    if not path.exists():
        return []
    return [json.loads(line)["event_type"] for line in path.read_text().splitlines()]


def test_propose_makes_no_writes(trace_file):
    run = workflow.propose_resolution("C-1002", PROVIDER)
    assert run.status == workflow.AWAITING_APPROVAL
    assert run.proposal.decision == Decision.STORE_CREDIT
    assert run.actions == []
    assert "mock_action" not in _event_types(trace_file)


def test_over_threshold_case_escalates():
    run = workflow.propose_resolution("C-1001", PROVIDER)
    assert run.proposal.decision == Decision.ESCALATE
    assert run.proposal.escalation_reasons


def test_approved_run_executes_gated_writes(trace_file):
    run = workflow.apply_approval(workflow.propose_resolution("C-1002", PROVIDER), _approval())
    assert run.status == workflow.EXECUTED
    assert [a["action"] for a in run.actions] == ["issue_store_credit", "send_customer_message", "tag_root_cause"]
    types = _event_types(trace_file)
    assert types.index("human_decision") < types.index("mock_action")


def test_escalation_runs_escalate_tool_without_customer_message():
    run = workflow.apply_approval(workflow.propose_resolution("C-1001", PROVIDER), _approval())
    assert [a["action"] for a in run.actions] == ["escalate", "tag_root_cause"]


def test_rejection_writes_nothing(trace_file):
    run = workflow.apply_approval(workflow.propose_resolution("C-1002", PROVIDER), _approval(approved=False))
    assert run.status == workflow.REJECTED
    assert run.actions == []
    assert "human_decision" in _event_types(trace_file)
    assert "mock_action" not in _event_types(trace_file)


def test_missing_approval_is_refused():
    run = workflow.propose_resolution("C-1002", PROVIDER)
    with pytest.raises(ValueError):
        workflow.apply_approval(run, None)
    assert run.actions == []


def test_approval_for_a_different_decision_is_refused():
    run = workflow.propose_resolution("C-1002", PROVIDER)
    with pytest.raises(ValueError):
        workflow.apply_approval(run, _approval(decision=Decision.REFUND))
    assert run.actions == []


def test_cannot_apply_twice():
    run = workflow.apply_approval(workflow.propose_resolution("C-1002", PROVIDER), _approval())
    with pytest.raises(ValueError):
        workflow.apply_approval(run, _approval())


def test_invalid_proposal_is_blocked_by_validator(trace_file):
    class BadProvider:
        def generate_resolution(self, case, context, applicable_policy):
            proposal = PROVIDER.generate_resolution(case, context, applicable_policy)
            return proposal.model_copy(update={"policy_clause_ids": ["US-FAKE-99"]})

    run = workflow.propose_resolution("C-1002", BadProvider())
    assert run.status == workflow.VALIDATION_FAILED
    with pytest.raises(ValueError):
        workflow.apply_approval(run, _approval())
    assert "validation_failed" in _event_types(trace_file)
    assert "mock_action" not in _event_types(trace_file)


def test_trace_covers_the_loop(trace_file):
    workflow.apply_approval(workflow.propose_resolution("C-1002", PROVIDER), _approval())
    types = _event_types(trace_file)
    for expected in ["case_loaded", "context_gathered", "provider_request", "proposal_generated",
                     "validation_passed", "human_decision", "mock_action"]:
        assert expected in types


def test_noop_provider_still_raises():
    with pytest.raises(NotImplementedError):
        workflow.propose_resolution("C-1002", NoopModelProvider())
