import pytest

from cosmic_resolve.models import ApprovalDecision
from cosmic_resolve.tools import DomainLookupError, MockWriteError, get_case, get_customer, get_policy, issue_refund


def test_get_case_and_unknown_record() -> None:
    case = get_case("C-1001")
    assert case.case_id == "C-1001"
    with pytest.raises(DomainLookupError):
        get_case("C-9999")


def test_customer_and_policy_lookups() -> None:
    customer = get_customer("C-001")
    assert customer.loyalty_tier == "GOLD"

    policies = get_policy("US", "GADGETS", "DAMAGED_ON_ARRIVAL")
    assert [policy.clause_id for policy in policies] == [
        "US-GAD-DOA-01",
        "US-GAD-DOA-02",
        "US-GAD-DOA-03",
        "US-GAD-DOA-04",
    ]


def test_write_action_requires_approval() -> None:
    approval = ApprovalDecision(approved=False, approved_by="Jordan", approval_token="token-1")
    with pytest.raises(MockWriteError):
        issue_refund("O-1001", 50.0, "Delivered broken", approval)
