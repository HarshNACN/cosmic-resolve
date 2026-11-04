"""Evaluation harness: run every case in evals/eval_cases.json through the real loop and score the outcomes.

Pure scoring logic lives here so the CLI (evals/run_evals.py) and the later Eval tab can share it.
Nothing in this module writes to the mock action trace; runs go to a separate eval trace file.

    entries = load_eval_cases()                       # preflight; raises EvalPreflightError
    scorecard = run_evaluation(provider, provider_label="offline")
"""
from __future__ import annotations

import functools
import json
import math
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from . import workflow
from .config import SETTINGS, TRACE_DIR
from .model_provider import ModelProvider
from . import tool_registry
from .models import Decision
from .workflow import AWAITING_APPROVAL, NO_POLICY, PROVIDER_ERROR, VALIDATION_FAILED, propose_resolution

EVAL_FILE_NAME = "eval_cases.json"
EXPECTED_CASE_COUNT = 30
EVAL_TRACE_PATH = TRACE_DIR / "eval_run.jsonl"
CITATION_VALIDITY_TARGET = 1.0
# Upper bound on repeat runs per case, to keep live spend bounded.
MAX_REPEAT = 10
# Optional prices per million tokens, supplied by the caller (never hardcoded). Shape:
# {"input_per_mtok_usd": float, "output_per_mtok_usd": float}; stored in the scorecard meta when used.
COST_RATE_KEYS = ("input_per_mtok_usd", "output_per_mtok_usd")

# Runs that never surface a decision to a human. They count as incorrect and are reported separately.
BLOCKED_STATUSES = {VALIDATION_FAILED, NO_POLICY, PROVIDER_ERROR}
# Money or goods remedies. Proposing one where ESCALATE was expected is the dangerous error.
REMEDY_DECISIONS = {Decision.REPLACE, Decision.REFUND, Decision.STORE_CREDIT, Decision.GOODWILL_CREDIT}
# Read tools that workflow.gather_context / propose_resolution call through the workflow module namespace.
READ_TOOLS = tuple(tool_registry.READ_TOOLS)  # the model-callable read tools; one source of truth


# Evidence the model must fetch itself before deciding (agent loop only). Order and shipment decide the
# remedy; the customer record decides the escalation thresholds.
REQUIRED_EVIDENCE_TOOLS = ("get_order", "get_shipment", "get_customer")


class EvalPreflightError(ValueError):
    """The eval file does not match the data set or the expected shape. Nothing was run."""


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise EvalPreflightError(f"{path.name} must contain a JSON list.")
    return payload


def load_eval_cases(path: Path | None = None) -> list[dict[str, Any]]:
    """Load the eval entries and check them against the data set. Reports every problem found at once."""
    path = path or SETTINGS.evals_dir / EVAL_FILE_NAME
    entries = _load_json_list(path)

    problems: list[str] = []
    if len(entries) != EXPECTED_CASE_COUNT:
        problems.append(f"expected {EXPECTED_CASE_COUNT} cases, found {len(entries)}")

    case_ids = [entry.get("case_id") for entry in entries]
    duplicates = sorted({cid for cid in case_ids if case_ids.count(cid) > 1 and cid is not None})
    if duplicates:
        problems.append(f"duplicate case_id values: {duplicates}")

    known_cases = {record.get("case_id") for record in _load_json_list(SETTINGS.data_dir / "cases.json")}
    known_clauses = {record.get("clause_id") for record in _load_json_list(SETTINGS.data_dir / "policies.json")}

    for entry in entries:
        cid = entry.get("case_id", "<missing>")
        if cid not in known_cases:
            problems.append(f"{cid}: case_id not found in cases.json")
        try:
            Decision(entry.get("expected_decision"))
        except ValueError:
            problems.append(f"{cid}: expected_decision {entry.get('expected_decision')!r} is not a valid Decision")
        clause_ids = entry.get("expected_policy_clause_ids")
        if not isinstance(clause_ids, list) or not clause_ids:
            problems.append(f"{cid}: expected_policy_clause_ids must be a non-empty list")
            continue
        for clause_id in clause_ids:
            if clause_id not in known_clauses:
                problems.append(f"{cid}: clause {clause_id!r} not found in policies.json")

    if problems:
        raise EvalPreflightError("Eval file failed preflight in " + str(path) + ":\n  - " + "\n  - ".join(problems))
    return entries


@contextmanager
def _counting_read_tools() -> Iterator[dict[str, int]]:
    """Wrap the read tools that the workflow module imported, so each call is counted. Restored on exit."""
    counter = {"calls": 0}
    originals = {name: getattr(workflow, name) for name in READ_TOOLS}

    def _wrap(fn):
        @functools.wraps(fn)
        def _counted(*args: Any, **kwargs: Any) -> Any:
            counter["calls"] += 1
            return fn(*args, **kwargs)

        return _counted

    for name, fn in originals.items():
        setattr(workflow, name, _wrap(fn))
    try:
        yield counter
    finally:
        for name, fn in originals.items():
            setattr(workflow, name, fn)


def _usage_fields(usage: Mapping[str, int] | None, cost_rates: Mapping[str, float] | None) -> dict[str, Any]:
    """Token, turn and cost fields for one run. Null when the provider reports no usage (offline) or no rates are given."""
    if usage is None:
        return {"input_tokens": None, "output_tokens": None, "model_turns": None, "estimated_cost_usd": None}
    cost = None
    if cost_rates:
        cost = round(
            (usage["inputTokens"] * cost_rates["input_per_mtok_usd"] + usage["outputTokens"] * cost_rates["output_per_mtok_usd"])
            / 1_000_000,
            6,
        )
    return {
        "input_tokens": usage["inputTokens"],
        "output_tokens": usage["outputTokens"],
        "model_turns": usage["turns"],
        "estimated_cost_usd": cost,
    }


def run_case(
    entry: dict[str, Any],
    provider: ModelProvider,
    *,
    cost_rates: Mapping[str, float] | None = None,
    repeat_index: int = 0,
) -> dict[str, Any]:
    """Run one eval case through propose_resolution and return its result row. Read-only; writes nothing."""
    expected = Decision(entry["expected_decision"])
    investigates = callable(getattr(provider, "investigate", None))
    # Clear any usage left by an earlier run, so a stale value can never be attributed to this case.
    try:
        provider.last_usage = None
    except AttributeError:
        pass  # provider has no usage attribute (offline providers)
    with _counting_read_tools() as counter:
        started = time.perf_counter()
        run = propose_resolution(entry["case_id"], provider)
        seconds = time.perf_counter() - started
    usage = getattr(provider, "last_usage", None)
    # For the agent loop, count only the model's own tool calls. The counter above also sees the validator's fetches.
    if investigates:
        tool_names: list[str] | None = list(getattr(provider, "last_tool_names", []))
        tool_calls = len(tool_names)
        missing_evidence: list[str] | None = [name for name in REQUIRED_EVIDENCE_TOOLS if name not in tool_names]
    else:
        tool_names = None
        tool_calls = counter["calls"]
        missing_evidence = None

    proposal = run.proposal
    scope_ids = {clause.clause_id for clause in run.policy}
    cited = list(proposal.policy_clause_ids) if proposal is not None else []
    # Same rule as validate_proposal: every cited clause must be in this case's own policy scope.
    clause_valid = all(clause_id in scope_ids for clause_id in cited) if proposal is not None else None
    actual = proposal.decision if (run.status == AWAITING_APPROVAL and proposal is not None) else None

    return {
        "case_id": entry["case_id"],
        "expected_decision": expected.value,
        "actual_decision": actual.value if actual else None,
        "run_status": run.status,
        "error": run.error,
        "proposal_produced": proposal is not None,
        "proposed_decision": proposal.decision.value if proposal is not None else None,
        "expected_clause_ids": list(entry.get("expected_policy_clause_ids", [])),
        "cited_clause_ids": cited,
        "clause_valid": clause_valid,
        "tool_calls": tool_calls,
        "tool_names": tool_names,
        "missing_evidence": missing_evidence,
        "decision_correct": actual == expected,
        "mismatch": actual != expected,
        "notes": entry.get("notes", ""),
        "repeat": repeat_index,
        "seconds": round(seconds, 3),
        **_usage_fields(usage, cost_rates),
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _outcome(row: dict[str, Any]) -> str:
    """What a human would have seen for this run: the surfaced decision, or the blocked status."""
    return row["actual_decision"] or row["run_status"]


def _mean(values: Sequence[float], digits: int) -> float | None:
    return round(sum(values) / len(values), digits) if values else None


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    """Nearest-rank percentile. None when there are no values."""
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(1, math.ceil(fraction * len(ordered))) - 1], 3)


def _repeat_stats(rows: Sequence[dict[str, Any]], case_count: int) -> dict[str, Any]:
    """Consistency across repeat runs. Only called when some case has more than one run."""
    by_case: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_case.setdefault(row["case_id"], []).append(row)

    consistent = [cid for cid, runs in by_case.items() if len({_outcome(r) for r in runs}) == 1]
    correct_every_run = [cid for cid, runs in by_case.items() if all(r["decision_correct"] for r in runs)]
    flaky = [
        {
            "case_id": cid,
            "expected": by_case[cid][0]["expected_decision"],
            "decision_counts": dict(Counter(_outcome(r) for r in by_case[cid])),
        }
        for cid in sorted(by_case)
        if len({_outcome(r) for r in by_case[cid]}) > 1
    ]
    return {
        "consistency_rate": _ratio(len(consistent), case_count),
        "pass_all_rate": _ratio(len(correct_every_run), case_count),
        "flaky_cases": flaky,
        "cases_consistent": len(consistent),
        "cases_correct_every_run": len(correct_every_run),
    }


def build_scorecard(rows: Sequence[dict[str, Any]], meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compute metrics from per-run rows (as returned by run_case). Pure: no I/O.

    Metrics and denominators count runs. `cases` counts distinct case IDs, which equals the run count when repeat=1.
    Rows from older scorecards may lack the timing and token fields; those aggregates then come out null.
    """
    total = len(rows)
    case_count = len({r["case_id"] for r in rows})
    repeated = total > case_count
    correct = sum(1 for r in rows if r["decision_correct"])

    with_proposal = [r for r in rows if r["proposal_produced"]]
    valid_citations = sum(1 for r in with_proposal if r["clause_valid"])

    expected_escalate = [r for r in rows if r["expected_decision"] == Decision.ESCALATE.value]
    other_than_escalate = [r for r in rows if r["expected_decision"] != Decision.ESCALATE.value]
    escalated_when_expected = sum(1 for r in expected_escalate if r["actual_decision"] == Decision.ESCALATE.value)
    escalated_unnecessarily = sum(1 for r in other_than_escalate if r["actual_decision"] == Decision.ESCALATE.value)

    not_refund_expected = [r for r in rows if r["expected_decision"] != Decision.REFUND.value]
    false_refunds = sum(1 for r in not_refund_expected if r["actual_decision"] == Decision.REFUND.value)

    unsafe = [
        r
        for r in expected_escalate
        if r["actual_decision"] is not None and Decision(r["actual_decision"]) in REMEDY_DECISIONS
    ]

    status_counts = {status: sum(1 for r in rows if r["run_status"] == status) for status in (VALIDATION_FAILED, NO_POLICY, PROVIDER_ERROR)}
    tool_total = sum(r["tool_calls"] for r in rows)
    with_evidence_check = [r for r in rows if r.get("missing_evidence") is not None]
    evidence_fetched = sum(1 for r in with_evidence_check if not r["missing_evidence"])

    confusion: dict[str, dict[str, int]] = {}
    for r in rows:
        actual_key = r["actual_decision"] or r["run_status"]
        bucket = confusion.setdefault(r["expected_decision"], {})
        bucket[actual_key] = bucket.get(actual_key, 0) + 1

    repeat_stats = _repeat_stats(rows, case_count) if repeated else None
    seconds = [r["seconds"] for r in rows if r.get("seconds") is not None]
    input_tokens = [r["input_tokens"] for r in rows if r.get("input_tokens") is not None]
    output_tokens = [r["output_tokens"] for r in rows if r.get("output_tokens") is not None]
    model_turns = [r["model_turns"] for r in rows if r.get("model_turns") is not None]
    costs = [r["estimated_cost_usd"] for r in rows if r.get("estimated_cost_usd") is not None]

    metrics = {
        "decision_accuracy": _ratio(correct, total),
        "policy_citation_validity": _ratio(valid_citations, len(with_proposal)),
        "correct_escalation_rate": _ratio(escalated_when_expected, len(expected_escalate)),
        "unnecessary_escalation_rate": _ratio(escalated_unnecessarily, len(other_than_escalate)),
        "false_refund_rate": _ratio(false_refunds, len(not_refund_expected)),
        "unsafe_remedy_count": len(unsafe),
        "avg_tool_calls_per_case": round(tool_total / total, 2) if total else None,
        "required_evidence_rate": _ratio(evidence_fetched, len(with_evidence_check)),
        "validator_blocked": status_counts[VALIDATION_FAILED],
        "no_policy": status_counts[NO_POLICY],
        "provider_errors": status_counts[PROVIDER_ERROR],
        # Null when N = 1 (consistency needs repeats).
        "consistency_rate": repeat_stats["consistency_rate"] if repeat_stats else None,
        "pass_all_rate": repeat_stats["pass_all_rate"] if repeat_stats else None,
        "avg_seconds_per_case": _mean(seconds, 3),
        "p95_seconds": _percentile(seconds, 0.95),
        "avg_input_tokens": _mean(input_tokens, 1),
        "avg_output_tokens": _mean(output_tokens, 1),
        "avg_model_turns": _mean(model_turns, 2),
        "avg_cost_per_case_usd": _mean(costs, 6),
        "total_estimated_cost_usd": round(sum(costs), 6) if costs else None,
    }
    denominators = {
        "cases": case_count,
        "runs": total,
        "decision_correct": correct,
        "cases_with_proposal": len(with_proposal),
        "cases_with_valid_citations": valid_citations,
        "expected_escalate": len(expected_escalate),
        "escalated_when_expected": escalated_when_expected,
        "expected_not_escalate": len(other_than_escalate),
        "escalated_unnecessarily": escalated_unnecessarily,
        "expected_not_refund": len(not_refund_expected),
        "false_refunds": false_refunds,
        "total_tool_calls": tool_total,
        "cases_with_evidence_check": len(with_evidence_check),
        "cases_with_required_evidence": evidence_fetched,
        "runs_with_timing": len(seconds),
        "runs_with_usage": len(input_tokens),
        "runs_with_cost": len(costs),
        "cases_consistent": repeat_stats["cases_consistent"] if repeat_stats else None,
        "cases_correct_every_run": repeat_stats["cases_correct_every_run"] if repeat_stats else None,
    }

    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "case_count": case_count,
            "citation_validity_target": CITATION_VALIDITY_TARGET,
            **(meta or {}),
        },
        "metrics": metrics,
        "denominators": denominators,
        "flaky_cases": repeat_stats["flaky_cases"] if repeat_stats else None,
        "by_decision": confusion,
        "mismatches": [
            {
                "case_id": r["case_id"],
                "expected": r["expected_decision"],
                "actual": r["actual_decision"],
                "run_status": r["run_status"],
                "notes": r["notes"],
            }
            for r in rows
            if r["mismatch"]
        ],
        "unsafe_remedy_cases": [r["case_id"] for r in unsafe],
    }


def run_evaluation(
    provider: ModelProvider,
    *,
    provider_label: str,
    model_id: str | None = None,
    entries: Sequence[dict[str, Any]] | None = None,
    trace_path: Path | None = None,
    repeat: int = 1,
    cost_rates: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Run every eval case `repeat` times and return the scorecard. Eval traces go to trace_path, never mock_actions.jsonl.

    Each full pass over the cases is one repeat, so an interrupted run still leaves complete passes behind.
    """
    if isinstance(repeat, bool) or not isinstance(repeat, int) or not 1 <= repeat <= MAX_REPEAT:
        raise ValueError(f"repeat must be a whole number from 1 to {MAX_REPEAT}, got {repeat!r}.")
    if cost_rates is not None and set(cost_rates) != set(COST_RATE_KEYS):
        raise ValueError(f"cost_rates must have exactly the keys {COST_RATE_KEYS}.")
    entries = list(entries) if entries is not None else load_eval_cases()
    trace_file = trace_path or EVAL_TRACE_PATH
    if trace_file.exists():
        trace_file.unlink()  # one file per run, so the trace reads as this run only

    previous_trace = SETTINGS.trace_path
    SETTINGS.trace_path = trace_file
    try:
        rows = [
            run_case(entry, provider, cost_rates=cost_rates, repeat_index=index)
            for index in range(repeat)
            for entry in entries
        ]
    finally:
        SETTINGS.trace_path = previous_trace

    meta = {
        "provider": provider_label,
        "model_id": model_id,
        "eval_file": EVAL_FILE_NAME,
        "trace_path": str(trace_file),
        "repeat": repeat,
        # The prices behind estimated_cost_usd, so the number can be audited. Null when no rates were given.
        "cost_rates_usd_per_mtok": dict(cost_rates) if cost_rates else None,
    }
    return build_scorecard(rows, meta)


def load_history(path: Path) -> list[dict[str, Any]]:
    """Return the runs already recorded in the scorecard file, oldest first. Raises ValueError if unreadable."""
    if not path.exists():
        return []
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON, so its run history cannot be read ({exc}).") from exc
    if isinstance(existing, dict) and isinstance(existing.get("runs"), list):
        return list(existing["runs"])
    if isinstance(existing, dict) and "metrics" in existing:
        return [existing]  # older single-run file: keep it as the first run
    raise ValueError(f"{path} has an unrecognised format, so its run history cannot be read.")


def append_run(path: Path, scorecard: dict[str, Any]) -> dict[str, Any]:
    """Append one run to the scorecard history. Earlier runs are never rewritten."""
    history = {"runs": load_history(path) + [scorecard]}
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
    return history


def citation_gate_failed(scorecard: dict[str, Any]) -> bool:
    """True when policy-citation validity is below the PRD target. Accuracy is reported, not gated."""
    validity = scorecard["metrics"]["policy_citation_validity"]
    return validity is not None and validity < scorecard["meta"]["citation_validity_target"]


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def format_summary(scorecard: dict[str, Any]) -> str:
    """Human-readable summary. Lines for newer metrics appear only when the scorecard has them."""
    m = scorecard["metrics"]
    d = scorecard["denominators"]
    runs = d.get("runs", d["cases"])  # older scorecards have no runs key: one run per case
    cases_line = f"Cases: {d['cases']}" + (f"  (runs: {runs})" if runs != d["cases"] else "")
    lines = [
        f"Provider: {scorecard['meta'].get('provider')}" + (f" ({scorecard['meta']['model_id']})" if scorecard["meta"].get("model_id") else ""),
        cases_line,
        f"Decision accuracy:            {_pct(m['decision_accuracy'])}  ({d['decision_correct']}/{runs})",
        f"Policy-citation validity:     {_pct(m['policy_citation_validity'])}  (target 100%)",
        f"Correct-escalation rate:      {_pct(m['correct_escalation_rate'])}  ({d['escalated_when_expected']}/{d['expected_escalate']})",
        f"Unnecessary-escalation rate:  {_pct(m['unnecessary_escalation_rate'])}  ({d['escalated_unnecessarily']}/{d['expected_not_escalate']})",
        f"False-refund rate:            {_pct(m['false_refund_rate'])}  ({d['false_refunds']}/{d['expected_not_refund']})",
        f"Unsafe-remedy cases:          {m['unsafe_remedy_count']}  {scorecard['unsafe_remedy_cases']}",
        f"Avg tool calls per case:      {m['avg_tool_calls_per_case']}",
        *([f"Required evidence fetched:    {_pct(m['required_evidence_rate'])}  ({d['cases_with_required_evidence']}/{d['cases_with_evidence_check']})"] if m["required_evidence_rate"] is not None else []),
        f"Blocked: validator={m['validator_blocked']} no_policy={m['no_policy']} provider_errors={m['provider_errors']}",
        f"Mismatches: {len(scorecard['mismatches'])} (see JSON for the list)",
    ]
    if m.get("consistency_rate") is not None:
        flaky = scorecard.get("flaky_cases") or []
        repeat_lines = [
            f"Consistency (same decision every run): {_pct(m['consistency_rate'])}  ({d['cases_consistent']}/{d['cases']})",
            f"Correct in every run:        {_pct(m['pass_all_rate'])}  ({d['cases_correct_every_run']}/{d['cases']})",
        ]
        lines[3:3] = repeat_lines  # right after the accuracy line
        lines.append("Flaky cases: " + (", ".join(item["case_id"] for item in flaky) if flaky else "none"))
    if m.get("avg_seconds_per_case") is not None:
        lines.append(f"Latency per case run:         avg {m['avg_seconds_per_case']:.2f} s, p95 {m['p95_seconds']:.2f} s")
    if m.get("avg_input_tokens") is not None:
        lines.append(
            f"Tokens per case run:          input {m['avg_input_tokens']:.0f}, output {m['avg_output_tokens']:.0f}, "
            f"model turns {m['avg_model_turns']:.2f}"
        )
    if m.get("total_estimated_cost_usd") is not None:
        lines.append(
            f"Estimated cost:               ${m['total_estimated_cost_usd']:.4f} total, "
            f"${m['avg_cost_per_case_usd']:.5f} per case run (rates in meta)"
        )
    return "\n".join(lines)
