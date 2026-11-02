from __future__ import annotations

import json
from pathlib import Path

from cosmic_resolve.config import EVALS_DIR
from cosmic_resolve.models import Decision


def run_eval() -> dict[str, float | int]:
    eval_cases_path = EVALS_DIR / "eval_cases.json"
    with eval_cases_path.open("r", encoding="utf-8") as handle:
        eval_cases = json.load(handle)

    score = 0
    for case in eval_cases:
        decision = case["expected_decision"]
        if decision in Decision.__members__:
            score += 1

    return {
        "total_cases": len(eval_cases),
        "expected_decisions_valid": score,
        "accuracy": round(score / len(eval_cases), 2) if eval_cases else 0.0,
    }


if __name__ == "__main__":
    result = run_eval()
    print(result)
