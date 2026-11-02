from cosmic_resolve.models import ApprovalDecision
from cosmic_resolve.tools import MockWriteError, issue_refund, issue_store_credit, send_customer_message


def test_write_tools_execute_only_with_valid_approval() -> None:
    approval = ApprovalDecision(
        approved=True,
        approved_by="Jordan",
        approval_token="approval-123",
        decision=None,
    )

    refund = issue_refund("O-1001", 100.0, "Replacement is not available", approval)
    assert refund["approved_by"] == "Jordan"

    message = send_customer_message("C-1001", "We are reviewing your order.", approval)
    assert message["case_id"] == "C-1001"

    try:
        issue_store_credit("C-001", 20.0, "Goodwill credit", None)
        assert False, "Expected a write gating error."
    except MockWriteError:
        pass
