"""Run the eval set through the resolution loop and write a JSON scorecard.

Usage (from the repo root, any shell; the script adds backend/ to sys.path itself):
    python evals/run_evals.py                        # offline rule-based provider (no AWS calls)
    python evals/run_evals.py --provider bedrock     # live Bedrock (same env as backend/demo.py --bedrock)
    python evals/run_evals.py --repeat 3             # run each case 3 times (1 to 10) to measure consistency
    python evals/run_evals.py --out path/to/card.json

Cost is estimated only when both COSMIC_COST_PER_MTOK_INPUT_USD and COSMIC_COST_PER_MTOK_OUTPUT_USD are set
(prices per million tokens, from you; none are hardcoded). Otherwise cost is null and only tokens are reported.

Exit code 1 when policy-citation validity is below 100% (PRD target). Accuracy is reported, not gated.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "backend"))

from cosmic_resolve.config import EVALS_DIR  # noqa: E402
from cosmic_resolve.evaluation import (  # noqa: E402
    MAX_REPEAT,
    EvalPreflightError,
    append_run,
    citation_gate_failed,
    format_summary,
    load_eval_cases,
    load_history,
    run_evaluation,
)
from cosmic_resolve.bedrock_agent import select_provider  # noqa: E402
from cosmic_resolve.model_provider import ProviderError  # noqa: E402

DEFAULT_OUT = EVALS_DIR / "scorecard.json"
COST_ENV = {"input": "COSMIC_COST_PER_MTOK_INPUT_USD", "output": "COSMIC_COST_PER_MTOK_OUTPUT_USD"}


def cost_rates_from_env(environ=os.environ) -> dict[str, float] | None:
    """Prices per million tokens from the environment. None when both are unset (empty counts as unset).

    Raises ValueError when only one is set, or a value is not a finite non-negative number.
    """
    raw = {side: environ.get(name, "").strip() for side, name in COST_ENV.items()}
    if not any(raw.values()):
        return None
    if not all(raw.values()):
        raise ValueError(f"Set both {COST_ENV['input']} and {COST_ENV['output']}, or neither.")
    rates: dict[str, float] = {}
    for side, text in raw.items():
        try:
            value = float(text)
        except ValueError:
            raise ValueError(f"{COST_ENV[side]} must be a number, got {text!r}.") from None
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{COST_ENV[side]} must be a finite non-negative number, got {text!r}.")
        rates[f"{side}_per_mtok_usd"] = value
    return rates


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run the Cosmic Resolve eval set and write a JSON scorecard.")
    parser.add_argument("--provider", choices=["offline", "bedrock"], default="offline")
    parser.add_argument("--bedrock", action="store_true", help="Shortcut for --provider bedrock (matches backend/demo.py).")
    parser.add_argument("--repeat", type=int, default=1, help=f"Runs per case, 1 to {MAX_REPEAT} (default 1).")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"Scorecard path (default {DEFAULT_OUT}).")
    args = parser.parse_args(argv)
    provider_name = "bedrock" if args.bedrock else args.provider

    if not 1 <= args.repeat <= MAX_REPEAT:
        print(f"--repeat must be from 1 to {MAX_REPEAT} (got {args.repeat}). Nothing was run and nothing was written.", file=sys.stderr)
        return 2

    try:
        cost_rates = cost_rates_from_env()
    except ValueError as exc:
        print(f"{exc} Nothing was run and nothing was written.", file=sys.stderr)
        return 2

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

    live = provider_name == "bedrock"
    try:
        provider = select_provider(live)
    except ProviderError as exc:
        print(f"Cannot start Bedrock provider: {exc}", file=sys.stderr)
        return 2
    model_id = provider.model_id if live else None
    # These labels are stored in the scorecard history; do not rename them.
    label = "bedrock" if live else "offline rule-based"

    scorecard = run_evaluation(
        provider,
        provider_label=label,
        model_id=model_id,
        entries=entries,
        repeat=args.repeat,
        cost_rates=cost_rates,
    )

    history = append_run(args.out, scorecard)

    print(format_summary(scorecard))
    print(f"Scorecard: {args.out} (run {len(history['runs'])} in history)")
    if citation_gate_failed(scorecard):
        print("FAIL: policy-citation validity is below the 100% target.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
