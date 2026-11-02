import pytest

from cosmic_resolve.models import Customer, Decision, ResolutionProposal, RootCause
from cosmic_resolve.tools import get_case, get_customer, get_policy
from cosmic_resolve.validators import validate_proposal


def test_validate_proposal_success() -> None:
    case = get_case("C-1001")
    policy = get_policy("US", "GADGETS", "DAMAGED_ON_ARRIVAL")

    proposal = ResolutionProposal(
        case_id=case.case_id,
        decision=Decision.ESCALATE,
        amount=649.0,
        policy_clause_ids=[clause.clause_id for clause in policy],
        evidence=["Customer image confirms cracked housing", "Carrier delivered without damage scan"],
        confidence=0.86,
        escalation_reasons=["Value > $200 threshold"],
        customer_message_draft="We are sending a replacement.",
        root_cause=RootCause(category="PACKAGING", detail="Insufficient padding"),
    )

    assert validate_proposal(proposal, case, policy) is True


def test_validate_proposal_rejects_unknown_clause() -> None:
    case = get_case("C-1001")
    policy = get_policy("US", "GADGETS", "DAMAGED_ON_ARRIVAL")

    proposal = ResolutionProposal(
        case_id=case.case_id,
        decision=Decision.REPLACE,
        amount=120.0,
        policy_clause_ids=["US-FAKE-CLAUSE"],
        evidence=["Customer image confirms cracked housing"],
        confidence=0.9,
        escalation_reasons=[],
        customer_message_draft="replacement",
        root_cause=RootCause(category="PACKAGING", detail="Insufficient padding"),
    )

    with pytest.raises(ValueError):
        validate_proposal(proposal, case, policy)


def test_validate_proposal_requires_escalation_for_large_value() -> None:
    case = get_case("C-1001")
    policy = get_policy("US", "GADGETS", "DAMAGED_ON_ARRIVAL")

    proposal = ResolutionProposal(
        case_id=case.case_id,
        decision=Decision.REPLACE,
        amount=250.0,
        policy_clause_ids=[clause.clause_id for clause in policy],
        evidence=["Customer image confirms cracked housing"],
        confidence=0.9,
        escalation_reasons=[],
        customer_message_draft="replacement",
        root_cause=RootCause(category="PACKAGING", detail="Insufficient padding"),
    )

    with pytest.raises(ValueError):
        validate_proposal(proposal, case, policy)


def _proposal(case_id: str, clause_ids: list[str], **overrides) -> ResolutionProposal:
    fields = dict(
        case_id=case_id,
        decision=Decision.REPLACE,
        amount=45.0,
        policy_clause_ids=clause_ids,
        evidence=["Carrier: lost in transit"],
        confidence=0.9,
        escalation_reasons=[],
        customer_message_draft="draft",
        root_cause=RootCause(category="CARRIER", detail="Lost in transit"),
    )
    fields.update(overrides)
    return ResolutionProposal(**fields)


def test_over_threshold_non_escalate_is_rejected_even_with_reason() -> None:
    case = get_case("C-1001")
    policy = get_policy("US", "GADGETS", "DAMAGED_ON_ARRIVAL")
    proposal = _proposal(
        case.case_id,
        [c.clause_id for c in policy],
        amount=649.0,
        escalation_reasons=["Value > $200 threshold"],
    )
    with pytest.raises(ValueError, match="must be ESCALATE"):
        validate_proposal(proposal, case, policy)


def test_exactly_200_does_not_force_escalation() -> None:
    case = get_case("C-1001")
    policy = get_policy("US", "GADGETS", "DAMAGED_ON_ARRIVAL")
    proposal = _proposal(case.case_id, [c.clause_id for c in policy], amount=200.0)
    assert validate_proposal(proposal, case, policy) is True


def test_escalate_requires_reason() -> None:
    case = get_case("C-1001")
    policy = get_policy("US", "GADGETS", "DAMAGED_ON_ARRIVAL")
    proposal = _proposal(case.case_id, [c.clause_id for c in policy], decision=Decision.ESCALATE)
    with pytest.raises(ValueError, match="escalation reason"):
        validate_proposal(proposal, case, policy)


def test_clause_for_other_case_type_is_rejected() -> None:
    case = get_case("C-1001")  # damaged on arrival
    wrong_policy = get_policy("US", "GADGETS", "LATE_DELIVERY")
    proposal = _proposal(case.case_id, [c.clause_id for c in wrong_policy])
    with pytest.raises(ValueError, match="do not apply"):
        validate_proposal(proposal, case, wrong_policy)


def test_goodwill_within_tier_cap_passes() -> None:
    case = get_case("C-1002")
    policy = get_policy("US", "GADGETS", "LATE_DELIVERY")
    customer = get_customer(case.customer_id)  # SILVER
    proposal = _proposal(case.case_id, [c.clause_id for c in policy], decision=Decision.GOODWILL_CREDIT, amount=5.0)
    assert validate_proposal(proposal, case, policy, customer) is True


def test_goodwill_over_tier_cap_is_rejected() -> None:
    case = get_case("C-1002")
    policy = get_policy("US", "GADGETS", "LATE_DELIVERY")
    customer = get_customer(case.customer_id)  # SILVER
    proposal = _proposal(case.case_id, [c.clause_id for c in policy], decision=Decision.GOODWILL_CREDIT, amount=50.0)
    with pytest.raises(ValueError, match="cap"):
        validate_proposal(proposal, case, policy, customer)


def test_goodwill_without_customer_record_is_rejected() -> None:
    case = get_case("C-1002")
    policy = get_policy("US", "GADGETS", "LATE_DELIVERY")
    proposal = _proposal(case.case_id, [c.clause_id for c in policy], decision=Decision.GOODWILL_CREDIT, amount=5.0)
    with pytest.raises(ValueError, match="customer record"):
        validate_proposal(proposal, case, policy)


def test_goodwill_unknown_tier_is_rejected() -> None:
    case = get_case("C-1002")
    policy = get_policy("US", "GADGETS", "LATE_DELIVERY")
    customer = Customer(
        customer_id=case.customer_id, name="X", loyalty_tier="DIAMOND", lifetime_value=0, prior_claims_12m=0, region="US"
    )
    proposal = _proposal(case.case_id, [c.clause_id for c in policy], decision=Decision.GOODWILL_CREDIT, amount=1.0)
    with pytest.raises(ValueError, match="No goodwill cap"):
        validate_proposal(proposal, case, policy, customer)
