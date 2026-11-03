"""Consistency checks for evals/eval_cases.json against the fixtures, policy book and validators.

Kept separate from test_data_integrity.py because the eval file is maintained on its own schedule.
Until it is completed, run the rest with: pytest --ignore=tests/test_eval_data.py
"""

import json

import pytest

from cosmic_resolve.config import DATA_DIR, ESCALATION_THRESHOLD_USD, EVALS_DIR
from cosmic_resolve.models import Decision, ResolutionProposal, RootCause
from cosmic_resolve.tools import get_case, get_customer, get_policy, get_shipment
from cosmic_resolve.validators import validate_proposal

EVAL_CASES = json.loads((EVALS_DIR / "eval_cases.json").read_text(encoding="utf-8"))
CASE_IDS = {c["case_id"] for c in json.loads((DATA_DIR / "cases.json").read_text(encoding="utf-8"))}
CLAUSES = {c["clause_id"]: c for c in json.loads((DATA_DIR / "policies.json").read_text(encoding="utf-8"))}

REQUIRED_KEYS = {"case_id", "expected_decision", "amount", "expected_policy_clause_ids", "notes"}
IDS = [e["case_id"] for e in EVAL_CASES]


def _proposal_from(entry: dict) -> ResolutionProposal:
    """Build a proposal that carries only the expected outcome, with neutral filler elsewhere."""
    decision = Decision(entry["expected_decision"])
    return ResolutionProposal(
        case_id=entry["case_id"],
        decision=decision,
        amount=entry["amount"],
        policy_clause_ids=entry["expected_policy_clause_ids"],
        evidence=["expected outcome"],
        confidence=0.9,
        escalation_reasons=["expected escalation"] if decision == Decision.ESCALATE else [],
        customer_message_draft="expected outcome",
        root_cause=RootCause(category="TEST", detail="expected outcome"),
    )


def test_eval_set_has_the_prd_number_of_cases() -> None:
    assert 25 <= len(EVAL_CASES) <= 30, f"PRD 6.5 asks for 25-30 eval cases, found {len(EVAL_CASES)}"


def test_eval_case_ids_are_unique_and_every_case_is_covered() -> None:
    assert len(IDS) == len(set(IDS))
    assert set(IDS) <= CASE_IDS, "eval entries reference cases that do not exist"
    assert set(IDS) == CASE_IDS, f"cases without an eval entry: {sorted(CASE_IDS - set(IDS))}"


@pytest.mark.parametrize("entry", EVAL_CASES, ids=IDS)
def test_entry_has_the_expected_shape(entry: dict) -> None:
    assert set(entry) == REQUIRED_KEYS
    assert entry["expected_decision"] in Decision.__members__
    assert entry["amount"] >= 0
    assert entry["expected_policy_clause_ids"], "every decision must cite a clause"
    assert set(entry["expected_policy_clause_ids"]) <= set(CLAUSES)


@pytest.mark.parametrize("entry", EVAL_CASES, ids=IDS)
def test_expected_clauses_belong_to_the_cases_case_type(entry: dict) -> None:
    case = get_case(entry["case_id"])
    for clause_id in entry["expected_policy_clause_ids"]:
        clause = CLAUSES[clause_id]
        assert (clause["market"], clause["category"], clause["case_type"]) == (
            case.market,
            case.category,
            case.case_type,
        ), f"{clause_id} does not apply to {case.case_type}"


@pytest.mark.parametrize("entry", EVAL_CASES, ids=IDS)
def test_expected_outcome_passes_the_proposal_validator(entry: dict) -> None:
    case = get_case(entry["case_id"])
    customer = get_customer(case.customer_id)
    policy = get_policy(case.market, case.category, case.case_type)
    assert validate_proposal(_proposal_from(entry), case, policy, customer) is True


@pytest.mark.parametrize("entry", EVAL_CASES, ids=IDS)
def test_expected_decision_follows_the_escalation_rules(entry: dict) -> None:
    case = get_case(entry["case_id"])
    customer = get_customer(case.customer_id)
    shipment = get_shipment(case.tracking_id)
    decision = entry["expected_decision"]
    must_escalate = []

    if entry["amount"] > ESCALATION_THRESHOLD_USD:
        must_escalate.append("value over threshold")
    if customer.prior_claims_12m >= 3:
        must_escalate.append("3+ prior claims")
    if case.case_type == "DAMAGED_ON_ARRIVAL" and not shipment.customer_photo_provided:
        must_escalate.append("damage claim without a photo")
    if case.case_type == "LATE_DELIVERY" and shipment.delivered and shipment.signature_required:
        must_escalate.append("signed delivery contradicts the claim")

    if must_escalate:
        assert decision == "ESCALATE", f"expected ESCALATE ({', '.join(must_escalate)}), found {decision}"


def test_eval_set_includes_enough_escalation_cases() -> None:
    escalations = [e for e in EVAL_CASES if e["expected_decision"] == "ESCALATE"]
    assert len(escalations) >= 8, "PRD calls for about 8 edge cases"
