"""Eval upgrades: repeat runs, per-run timing and token usage, optional cost, and older-shape scorecards.

Offline only: every provider here is scripted, so no test makes a live Bedrock call.
"""
import importlib.util
from pathlib import Path

import pytest

from cosmic_resolve.config import SETTINGS
from cosmic_resolve.evaluation import build_scorecard, format_summary, load_eval_cases, run_case, run_evaluation
from cosmic_resolve.models import Decision, ResolutionProposal, RootCause

RATES = {"input_per_mtok_usd": 3.0, "output_per_mtok_usd": 15.0}
NEW_ROW_FIELDS = ("repeat", "seconds", "input_tokens", "output_tokens", "model_turns", "estimated_cost_usd")
NEW_METRICS = (
    "consistency_rate", "pass_all_rate", "avg_seconds_per_case", "p95_seconds", "avg_input_tokens",
    "avg_output_tokens", "avg_model_turns", "avg_cost_per_case_usd", "total_estimated_cost_usd",
)


class OracleProvider:
    """Returns each case's expected decision, citing the case's own policy scope."""

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


class UsageProvider(OracleProvider):
    """Oracle that also reports token usage, the way the Bedrock providers do."""

    def __init__(self, entries, usage):
        super().__init__(entries)
        self._usage = usage
        self.last_usage = None

    def generate_resolution(self, case, context, applicable_policy):
        proposal = super().generate_resolution(case, context, applicable_policy)
        self.last_usage = dict(self._usage)
        return proposal


class AlternatingProvider(OracleProvider):
    """Correct on the first call for each case, a different decision on every later call."""

    def __init__(self, entries):
        super().__init__(entries)
        self._calls: dict[str, int] = {}

    def generate_resolution(self, case, context, applicable_policy):
        n = self._calls.get(case.case_id, 0)
        self._calls[case.case_id] = n + 1
        if n == 0:
            return super().generate_resolution(case, context, applicable_policy)
        expected = Decision(self._by_case[case.case_id]["expected_decision"])
        other = Decision.STORE_CREDIT if expected != Decision.STORE_CREDIT else Decision.REFUND
        return ResolutionProposal(
            case_id=case.case_id,
            decision=other,
            amount=0.0,
            policy_clause_ids=[applicable_policy[0].clause_id],
            evidence=["alternate evidence"],
            confidence=0.5,
            escalation_reasons=[],
            customer_message_draft="alternate message",
            root_cause=RootCause(category="UNKNOWN", detail="alternate"),
        )


@pytest.fixture(autouse=True)
def eval_trace(tmp_path, monkeypatch):
    """Every test writes eval traces to a temp file, never to traces/."""
    monkeypatch.setattr(SETTINGS, "trace_path", tmp_path / "mock_actions.jsonl")
    return tmp_path / "eval_run.jsonl"


@pytest.fixture
def entries():
    return load_eval_cases()


def _run(provider, entries, trace, **kwargs):
    return run_evaluation(provider, provider_label="test", entries=entries, trace_path=trace, **kwargs)


def _load_cli():
    path = Path(__file__).resolve().parent.parent / "evals" / "run_evals.py"
    spec = importlib.util.spec_from_file_location("run_evals_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- Per-run timing, tokens and cost ----------------------------------------------------------------------------------

def test_run_case_records_timing_and_usage(entries):
    usage = {"inputTokens": 1000, "outputTokens": 200, "turns": 2}
    row = run_case(entries[0], UsageProvider(entries, usage))
    assert row["seconds"] >= 0
    assert (row["input_tokens"], row["output_tokens"], row["model_turns"]) == (1000, 200, 2)
    assert row["estimated_cost_usd"] is None  # no rates given


def test_cost_is_computed_only_when_rates_are_given(entries):
    usage = {"inputTokens": 1_000_000, "outputTokens": 500_000, "turns": 1}
    row = run_case(entries[0], UsageProvider(entries, usage), cost_rates=RATES)
    assert row["estimated_cost_usd"] == 10.5  # 1M input at $3 + 0.5M output at $15


def test_offline_provider_reports_null_usage_even_with_rates(entries):
    row = run_case(entries[0], OracleProvider(entries), cost_rates=RATES)
    assert row["input_tokens"] is None and row["output_tokens"] is None and row["model_turns"] is None
    assert row["estimated_cost_usd"] is None


def test_stale_usage_never_leaks_into_the_next_case(entries):
    provider = OracleProvider(entries)  # reports no usage of its own
    provider.last_usage = {"inputTokens": 999, "outputTokens": 999, "turns": 9}
    assert run_case(entries[0], provider)["input_tokens"] is None


def test_p95_is_nearest_rank_over_timed_runs(entries):
    rows = [run_case(entry, OracleProvider(entries)) for entry in entries]
    for index, row in enumerate(rows):
        row["seconds"] = float(index + 1)  # 1..30 seconds
    metrics = build_scorecard(rows)["metrics"]
    assert metrics["p95_seconds"] == 29.0  # nearest rank: ceil(0.95 * 30) = 29th value
    assert metrics["avg_seconds_per_case"] == 15.5


def test_rates_are_recorded_in_the_scorecard_meta(entries, eval_trace):
    card = _run(UsageProvider(entries, {"inputTokens": 10, "outputTokens": 5, "turns": 1}), entries, eval_trace, cost_rates=RATES)
    assert card["meta"]["cost_rates_usd_per_mtok"] == RATES
    assert card["metrics"]["total_estimated_cost_usd"] is not None
    assert "Estimated cost:" in format_summary(card)


def test_offline_summary_has_no_usage_or_cost_lines(entries, eval_trace):
    summary = format_summary(_run(OracleProvider(entries), entries, eval_trace))
    assert "Tokens per case run" not in summary
    assert "Estimated cost" not in summary
    assert "Consistency" not in summary


def test_cost_env_needs_both_variables_or_neither():
    cli = _load_cli()
    IN, OUT = "COSMIC_COST_PER_MTOK_INPUT_USD", "COSMIC_COST_PER_MTOK_OUTPUT_USD"
    assert cli.cost_rates_from_env({}) is None
    assert cli.cost_rates_from_env({IN: " ", OUT: ""}) is None  # empty counts as unset
    assert cli.cost_rates_from_env({IN: "3", OUT: "15"}) == RATES
    for bad in ({IN: "3"}, {IN: "x", OUT: "1"}, {IN: "-1", OUT: "1"}):
        with pytest.raises(ValueError):
            cli.cost_rates_from_env(bad)


# --- Repeat runs -----------------------------------------------------------------------------------------------------

def test_repeat_one_leaves_new_metrics_null(entries, eval_trace):
    card = _run(OracleProvider(entries), entries, eval_trace)
    assert card["metrics"]["consistency_rate"] is None
    assert card["metrics"]["pass_all_rate"] is None
    assert card["flaky_cases"] is None
    assert card["denominators"]["runs"] == card["denominators"]["cases"] == 30


def test_stable_provider_is_fully_consistent_over_repeats(entries, eval_trace):
    card = _run(OracleProvider(entries), entries, eval_trace, repeat=3)
    assert card["metrics"]["consistency_rate"] == 1.0
    assert card["metrics"]["pass_all_rate"] == 1.0
    assert card["flaky_cases"] == []
    assert card["denominators"]["runs"] == 90
    assert card["denominators"]["cases"] == 30
    assert card["meta"]["repeat"] == 3


def test_alternating_provider_shows_up_as_flaky(entries, eval_trace):
    card = _run(AlternatingProvider(entries), entries, eval_trace, repeat=2)
    assert card["metrics"]["consistency_rate"] == 0.0
    assert card["metrics"]["pass_all_rate"] == 0.0
    assert card["denominators"]["cases_consistent"] == 0
    flaky = card["flaky_cases"]
    assert [item["case_id"] for item in flaky] == sorted(e["case_id"] for e in entries)
    for item in flaky:
        assert sum(item["decision_counts"].values()) == 2
        assert len(item["decision_counts"]) == 2
    assert "Flaky cases:" in format_summary(card)


@pytest.mark.parametrize("bad", [0, 11, -1, True, 2.5])
def test_repeat_outside_the_cap_is_rejected(entries, eval_trace, bad):
    with pytest.raises(ValueError):
        _run(OracleProvider(entries), entries, eval_trace, repeat=bad)


def test_cli_rejects_repeat_above_the_cap_and_writes_nothing(tmp_path):
    cli = _load_cli()
    out = tmp_path / "card.json"
    assert cli.main(["--repeat", "11", "--out", str(out)]) == 2
    assert cli.main(["--repeat", "0", "--out", str(out)]) == 2
    assert not out.exists()


# --- Older scorecard shapes --------------------------------------------------------------------------------------------

def test_older_rows_without_new_fields_still_summarize(entries):
    rows = [run_case(entry, OracleProvider(entries)) for entry in entries]
    legacy = [{k: v for k, v in row.items() if k not in NEW_ROW_FIELDS} for row in rows]
    card = build_scorecard(legacy, {"provider": "old"})
    assert card["metrics"]["decision_accuracy"] == 1.0
    assert card["metrics"]["avg_seconds_per_case"] is None
    assert card["metrics"]["total_estimated_cost_usd"] is None
    assert card["flaky_cases"] is None
    format_summary(card)  # must not raise


def test_older_saved_scorecard_without_new_keys_still_formats(entries):
    card = build_scorecard([run_case(entry, OracleProvider(entries)) for entry in entries], {"provider": "old"})
    for key in NEW_METRICS:
        card["metrics"].pop(key)
    card["denominators"].pop("runs")
    card.pop("flaky_cases")
    summary = format_summary(card)
    assert "Decision accuracy" in summary
    assert "Latency" not in summary and "Consistency" not in summary
