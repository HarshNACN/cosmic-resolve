import json
import re

import pytest

from cosmic_resolve.config import DATA_DIR, ESCALATION_THRESHOLD_USD, EVALS_DIR, GOODWILL_CAPS_USD
from cosmic_resolve.tools import get_policy

CASE_TYPES = ["DAMAGED_ON_ARRIVAL", "LATE_DELIVERY", "RETURN_REQUEST"]


def _all_clauses() -> list[dict]:
    return json.loads((DATA_DIR / "policies.json").read_text(encoding="utf-8"))


def test_policy_book_has_unique_wellformed_clause_ids() -> None:
    clauses = _all_clauses()
    ids = [c["clause_id"] for c in clauses]
    assert len(clauses) >= 12
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"US-GAD-(DOA|LD|RET)-\d{2}", i) for i in ids)


@pytest.mark.parametrize("case_type", CASE_TYPES)
def test_each_case_type_has_clauses_and_matching_id_prefix(case_type: str) -> None:
    prefix = {"DAMAGED_ON_ARRIVAL": "DOA", "LATE_DELIVERY": "LD", "RETURN_REQUEST": "RET"}[case_type]
    clauses = get_policy("US", "GADGETS", case_type)
    assert len(clauses) >= 3
    assert all(f"-{prefix}-" in c.clause_id for c in clauses)


@pytest.mark.parametrize("case_type", CASE_TYPES)
def test_every_case_type_states_the_escalation_threshold(case_type: str) -> None:
    text = " ".join(c.text for c in get_policy("US", "GADGETS", case_type))
    assert f"${ESCALATION_THRESHOLD_USD:.0f}" in text


@pytest.mark.parametrize("case_type", ["DAMAGED_ON_ARRIVAL", "LATE_DELIVERY"])
def test_goodwill_caps_in_policy_text_match_config(case_type: str) -> None:
    text = " ".join(c.text for c in get_policy("US", "GADGETS", case_type))
    for tier, cap in GOODWILL_CAPS_USD.items():
        assert f"{tier.capitalize()} ${cap:.0f}" in text


def test_eval_cases_cite_clauses_that_exist() -> None:
    known = {c["clause_id"] for c in _all_clauses()}
    eval_cases = json.loads((EVALS_DIR / "eval_cases.json").read_text(encoding="utf-8"))
    for case in eval_cases:
        assert set(case["expected_policy_clause_ids"]) <= known
