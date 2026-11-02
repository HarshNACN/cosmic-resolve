import pytest

from cosmic_resolve.models import (
    ApprovalDecision,
    Decision,
    ResolutionProposal,
    RootCause,
    SupportCase,
)


def test_support_case_model() -> None:
    case = SupportCase(
        case_id="C-1001",
        order_id="O-1001",
        customer_id="C-001",
        tracking_id="T-1001",
        case_type="DAMAGED_ON_ARRIVAL",
        market="US",
        category="GADGETS",
        complaint_text="Cracked case",
        channel="EMAIL",
        created_at="2026-11-02T09:00:00Z",
    )
    assert case.status == "OPEN"


def test_resolution_proposal_model() -> None:
    proposal = ResolutionProposal(
        case_id="C-1001",
        decision=Decision.REPLACE,
        amount=649.0,
        policy_clause_ids=["US-GAD-DOA-02"],
        evidence=["Customer photo shows cracked housing"],
        confidence=0.86,
        escalation_reasons=[],
        customer_message_draft="We are arranging a replacement.",
        root_cause=RootCause(category="PACKAGING", detail="Insufficient padding"),
    )
    assert proposal.decision == Decision.REPLACE
    assert proposal.confidence == 0.86


def test_approval_decision_requires_token_when_approved() -> None:
    with pytest.raises(ValueError):
        ApprovalDecision(approved=True, approved_by="Jordan", approval_token="")
