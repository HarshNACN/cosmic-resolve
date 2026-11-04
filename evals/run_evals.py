"""Run the eval set through the resolution loop and write a JSON scorecard.

Usage (from the repo root, any shell; the script adds backend/ to sys.path itself):
    python evals/run_evals.py                        # offline rule-based provider (no AWS calls)
    python evals/run_evals.py --provider bedrock     # live Bedrock (same env as backend/demo.py --bedrock)
    python evals/run_evals.py --out path/to/card.json

Exit code 1 when policy-citation validity is below 100% (PRD target). Accuracy is reported, not gated.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "backend"))

from cosmic_resolve.config import EVALS_DIR  # noqa: E402
from cosmic_resolve.evaluation import (  # noqa: E402
    EvalPreflightError,
    append_run,
    citation_gate_failed,
    format_summary,
    load_eval_cases,
    load_history,
    run_evaluation,
)
from cosmic_resolve.model_provider import ProviderError, RuleBasedModelProvider  # noqa: E402

DEFAULT_OUT = EVALS_DIR / "scorecard.json"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run the Cosmic Resolve eval set and write a JSON scorecard.")
    parser.add_argument("--provider", choices=["offline", "bedrock"], default="offline")
    parser.add_argument("--bedrock", action="store_true", help="Shortcut for --provider bedrock (matches backend/demo.py).")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"Scorecard path (default {DEFAULT_OUT}).")
    args = parser.parse_args(argv)
    provider_name = "bedrock" if args.bedrock else args.provider

    try:
        entries = load_eval_cases()
    except EvalPreflightError as exc:
        print(exc, file=sys.stderr)
        return 2

    # Check the history file before a (possibly paid, live) run, so an unreadable file cannot cost a run.
    try:
        load_history(args.out)
    except ValueError as exc:
        print(f"{exc} Nothing was run and nothing was written.", file=sys.stderr)
        return 2

    model_id = None
    if provider_name == "bedrock":
        from cosmic_resolve.bedrock_agent import live_bedrock_provider

        try:
            provider = live_bedrock_provider()
        except ProviderError as exc:
            print(f"Cannot start Bedrock provider: {exc}", file=sys.stderr)
            return 2
        model_id = provider.model_id
        label = "bedrock"
    else:
        provider = RuleBasedModelProvider()
        label = "offline rule-based"

    scorecard = run_evaluation(provider, provider_label=label, model_id=model_id, entries=entries)

    history = append_run(args.out, scorecard)

    print(format_summary(scorecard))
    print(f"Scorecard: {args.out} (run {len(history['runs'])} in history)")
    if citation_gate_failed(scorecard):
        print("FAIL: policy-citation validity is below the 100% target.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
