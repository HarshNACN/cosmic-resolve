import json

import pytest

from cosmic_resolve import evaluation
from cosmic_resolve.config import SETTINGS
from cosmic_resolve.evaluation import (
    EvalPreflightError,
    build_scorecard,
    citation_gate_failed,
    load_eval_cases,
    run_case,
    run_evaluation,
)
from cosmic_resolve.model_provider import ProviderError, RuleBasedModelProvider
from cosmic_resolve.models import Decision, ResolutionProposal, RootCause
from cosmic_resolve.workflow import AWAITING_APPROVAL, NO_POLICY, PROVIDER_ERROR, VALIDATION_FAILED


class OracleProvider:
    """Returns the expected decision for each eval case, citing the case's own policy scope."""

    def __init__(self, entries):
        self._by_case = {e["case_id"]: e for e in entries}

    def generate_resolution(self, case, context, applicable_policy):
        entry = self._by_case[case.case_id]
        decision = Decision(entry["expected_decision"])
        return ResolutionProposal(
            case_id=case.case_id,
            decision=decision,
            amount=entry["amount"],
            policy_clause_ids=[applicable_policy[0].clause_id],
            evidence=["oracle evidence"],
            confidence=0.9,
            escalation_reasons=["oracle escalation"] if decision == Decision.ESCALATE else [],
            customer_message_draft="oracle message",
            root_cause=RootCause(category="UNKNOWN", detail="oracle"),
        )


class FixedProvider:
    """Proposes one decision for every case with a chosen amount and clause ID."""

    def __init__(self, decision, amount=0.0, clause_id=None):
        self._decision = decision
        self._amount = amount
        self._clause_id = clause_id

    def generate_resolution(self, case, context, applicable_policy):
        clause = self._clause_id or applicable_policy[0].clause_id
        return ResolutionProposal(
            case_id=case.case_id,
            decision=self._decision,
            amount=self._amount,
            policy_clause_ids=[clause],
            evidence=["fixed evidence"],
            confidence=0.5,
            escalation_reasons=["fixed escalation"] if self._decision == Decision.ESCALATE else [],
            customer_message_draft="fixed message",
            root_cause=RootCause(category="UNKNOWN", detail="fixed"),
        )


class FailingProvider:
    def generate_resolution(self, case, context, applicable_policy):
        raise ProviderError("simulated outage")


@pytest.fixture(autouse=True)
def eval_trace(tmp_path, monkeypatch):
    """Every test writes eval traces to a temp file, never to traces/."""
    path = tmp_path / "eval_run.jsonl"
    monkeypatch.setattr(SETTINGS, "trace_path", tmp_path / "mock_actions.jsonl")
    return path


@pytest.fixture
def entries():
    return load_eval_cases()


def _run(provider, entries, eval_trace):
    return run_evaluation(provider, provider_label="test", entries=entries, trace_path=eval_trace)


def _expected_counts(entries):
    escalate = sum(1 for e in entries if e["expected_decision"] == "ESCALATE")
    refund = sum(1 for e in entries if e["expected_decision"] == "REFUND")
    return escalate, len(entries) - refund


def test_preflight_accepts_committed_eval_file(entries):
    assert len(entries) == 30


def test_oracle_scores_perfectly(entries, eval_trace):
    card = _run(OracleProvider(entries), entries, eval_trace)
    m = card["metrics"]
    assert m["decision_accuracy"] == 1.0
    assert m["policy_citation_validity"] == 1.0
    assert m["correct_escalation_rate"] == 1.0
    assert m["unnecessary_escalation_rate"] == 0.0
    assert m["false_refund_rate"] == 0.0
    assert m["unsafe_remedy_count"] == 0
    assert card["mismatches"] == []
    assert not citation_gate_failed(card)


def test_all_refund_provider_shows_the_misses(entries, eval_trace):
    card = _run(FixedProvider(Decision.REFUND), entries, eval_trace)
    m = card["metrics"]
    escalate, not_refund = _expected_counts(entries)
    refund_correct = sum(1 for e in entries if e["expected_decision"] == "REFUND")

    assert m["decision_accuracy"] == round(refund_correct / 30, 4)
    assert m["false_refund_rate"] == 1.0  # every non-REFUND expectation was refunded
    assert card["denominators"]["expected_not_refund"] == not_refund
    assert m["correct_escalation_rate"] == 0.0
    assert m["unnecessary_escalation_rate"] == 0.0
    assert m["unsafe_remedy_count"] == escalate
    assert len(card["unsafe_remedy_cases"]) == escalate
    assert len(card["mismatches"]) == 30 - refund_correct


def test_false_refund_excludes_blocked_runs(entries, eval_trace):
    # A REFUND with a clause from another case's scope is blocked by the validator, so no human sees it.
    provider = FixedProvider(Decision.REFUND, clause_id="US-GAD-LD-01")
    card = _run(provider, entries, eval_trace)
    m = card["metrics"]
    assert m["validator_blocked"] > 0
    rows = [run_case(e, provider) for e in entries]
    surfaced_false_refunds = sum(
        1 for row in rows if row["actual_decision"] == "REFUND" and row["expected_decision"] != "REFUND"
    )
    assert m["false_refund_rate"] == round(surfaced_false_refunds / card["denominators"]["expected_not_refund"], 4)
    assert surfaced_false_refunds < card["denominators"]["expected_not_refund"]


def test_out_of_scope_citation_fails_the_gate(entries, eval_trace):
    card = _run(FixedProvider(Decision.REFUND, clause_id="US-GAD-LD-01"), entries, eval_trace)
    assert card["metrics"]["policy_citation_validity"] < 1.0
    assert citation_gate_failed(card)


def test_provider_errors_are_counted_not_crashed(entries, eval_trace):
    card = _run(FailingProvider(), entries, eval_trace)
    assert card["metrics"]["provider_errors"] == 30
    assert card["metrics"]["decision_accuracy"] == 0.0
    assert card["metrics"]["policy_citation_validity"] is None
    assert not citation_gate_failed(card)
    assert "cases" not in card


def test_tool_calls_are_counted_per_case(entries, eval_trace):
    card = _run(RuleBasedModelProvider(), entries, eval_trace)
    # get_case + get_order + get_customer + get_shipment + get_product_listing + check_inventory + get_policy
    assert card["metrics"]["avg_tool_calls_per_case"] == 7.0
    assert card["denominators"]["total_tool_calls"] == 7 * 30
    row = run_case(entries[0], RuleBasedModelProvider())
    assert row["tool_calls"] == 7
    assert row["run_status"] == AWAITING_APPROVAL


def test_harness_restores_trace_path_and_leaves_mock_log_alone(entries, eval_trace):
    before = SETTINGS.trace_path
    _run(RuleBasedModelProvider(), entries, eval_trace)
    assert SETTINGS.trace_path == before
    assert eval_trace.exists()
    assert not before.exists()


def test_read_tools_are_restored_after_run(entries, eval_trace):
    from cosmic_resolve import workflow

    originals = {name: getattr(workflow, name) for name in evaluation.READ_TOOLS}
    _run(RuleBasedModelProvider(), entries, eval_trace)
    for name, fn in originals.items():
        assert getattr(workflow, name) is fn


def test_build_scorecard_blocked_statuses_are_not_correct():
    rows = [
        {
            "case_id": "C-X", "expected_decision": "REPLACE", "actual_decision": None,
            "run_status": VALIDATION_FAILED, "error": "x", "proposal_produced": True,
            "proposed_decision": "REFUND", "expected_clause_ids": [], "cited_clause_ids": ["A"],
            "clause_valid": True, "tool_calls": 7, "decision_correct": False, "mismatch": True, "notes": "",
        },
        {
            "case_id": "C-Y", "expected_decision": "ESCALATE", "actual_decision": None,
            "run_status": NO_POLICY, "error": "none", "proposal_produced": False,
            "proposed_decision": None, "expected_clause_ids": [], "cited_clause_ids": [],
            "clause_valid": None, "tool_calls": 7, "decision_correct": False, "mismatch": True, "notes": "",
        },
    ]
    card = build_scorecard(rows, {"provider": "unit"})
    m = card["metrics"]
    assert m["decision_accuracy"] == 0.0
    assert m["validator_blocked"] == 1
    assert m["no_policy"] == 1
    assert m["false_refund_rate"] == 0.0  # the blocked REFUND never reached a human
    assert m["policy_citation_validity"] == 1.0
    assert card["by_decision"]["REPLACE"] == {VALIDATION_FAILED: 1}


def _write_eval(tmp_path, entries):
    path = tmp_path / "bad_eval.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def _good_entries():
    return json.loads((SETTINGS.evals_dir / "eval_cases.json").read_text(encoding="utf-8"))


def test_preflight_rejects_unknown_case(tmp_path):
    entries = _good_entries()
    entries[0]["case_id"] = "C-9999"
    with pytest.raises(EvalPreflightError, match="C-9999: case_id not found"):
        load_eval_cases(_write_eval(tmp_path, entries))


def test_preflight_rejects_unknown_clause(tmp_path):
    entries = _good_entries()
    entries[1]["expected_policy_clause_ids"] = ["US-GAD-NOPE-99"]
    with pytest.raises(EvalPreflightError, match="US-GAD-NOPE-99"):
        load_eval_cases(_write_eval(tmp_path, entries))


def test_preflight_rejects_invalid_decision(tmp_path):
    entries = _good_entries()
    entries[2]["expected_decision"] = "REFUND_NOW"
    with pytest.raises(EvalPreflightError, match="not a valid Decision"):
        load_eval_cases(_write_eval(tmp_path, entries))


def test_preflight_rejects_wrong_count(tmp_path):
    with pytest.raises(EvalPreflightError, match="expected 30 cases, found 29"):
        load_eval_cases(_write_eval(tmp_path, _good_entries()[:29]))


def test_preflight_rejects_duplicates(tmp_path):
    entries = _good_entries()
    entries[1]["case_id"] = entries[0]["case_id"]
    with pytest.raises(EvalPreflightError, match="duplicate case_id"):
        load_eval_cases(_write_eval(tmp_path, entries))
