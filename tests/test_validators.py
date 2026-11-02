import pytest

from cosmic_resolve.models import Decision, ResolutionProposal, RootCause
from cosmic_resolve.tools import get_case, get_policy
from cosmic_resolve.validators import validate_proposal


def test_validate_proposal_success() -> None:
    case = get_case("C-1001")
    policy = get_policy("US", "GADGETS", "DAMAGED_ON_ARRIVAL")

    proposal = ResolutionProposal(
        case_id=case.case_id,
        decision=Decision.REPLACE,
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
