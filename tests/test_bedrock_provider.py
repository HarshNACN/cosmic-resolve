import pytest

from cosmic_resolve import workflow
from cosmic_resolve.bedrock_provider import TOOL_NAME, BedrockModelProvider
from cosmic_resolve.config import SETTINGS
from cosmic_resolve.model_provider import ProviderError
from cosmic_resolve.models import Decision
from cosmic_resolve.tools import get_case, get_policy

GOOD_INPUT = {
    "case_id": "SHOULD-BE-IGNORED",
    "decision": "STORE_CREDIT",
    "amount": 45.0,
    "policy_clause_ids": ["US-GAD-LD-01"],
    "evidence": ["Shipment T-1002 status: LOST_IN_TRANSIT"],
    "confidence": 0.9,
    "escalation_reasons": [],
    "customer_message_draft": "Sorry about the delay.",
    "root_cause_category": "CARRIER_DELAY",
    "root_cause_detail": "Lost in transit",
}


class StubClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def _tool_response(payload):
    return {"output": {"message": {"content": [{"toolUse": {"name": TOOL_NAME, "input": payload}}]}}}


@pytest.fixture(autouse=True)
def trace_file(tmp_path, monkeypatch):
    monkeypatch.setattr(SETTINGS, "trace_path", tmp_path / "trace.jsonl")


def _provider(client):
    return BedrockModelProvider(client=client, model_id="test-profile")


def test_parses_tool_use_and_forces_case_id_from_active_case():
    case = get_case("C-1002")
    proposal = _provider(StubClient(_tool_response(GOOD_INPUT))).generate_resolution(
        case, workflow.gather_context(case), get_policy("US", "GADGETS", "LATE_DELIVERY")
    )
    assert proposal.case_id == "C-1002"
    assert proposal.decision == Decision.STORE_CREDIT
    assert proposal.root_cause.category == "CARRIER_DELAY"


def test_request_offers_the_tool_and_marks_complaint_untrusted_without_pii():
    client = StubClient(_tool_response(GOOD_INPUT))
    case = get_case("C-1001")
    _provider(client).generate_resolution(case, workflow.gather_context(case), get_policy("US", "GADGETS", "DAMAGED_ON_ARRIVAL"))
    call = client.calls[0]
    assert call["modelId"] == "test-profile"
    assert call["toolConfig"]["tools"][0]["toolSpec"]["name"] == TOOL_NAME
    text = call["messages"][0]["content"][0]["text"]
    assert "UNTRUSTED" in text and "<complaint>" in text
    assert "US-GAD-DOA-03" in text
    assert "Maya" not in text  # customer name must not be sent to the model


def test_no_tool_call_is_a_provider_error():
    client = StubClient({"output": {"message": {"content": [{"text": "I refuse."}]}}})
    case = get_case("C-1002")
    with pytest.raises(ProviderError):
        _provider(client).generate_resolution(case, workflow.gather_context(case), [])


def test_malformed_proposal_is_a_provider_error():
    client = StubClient(_tool_response({**GOOD_INPUT, "decision": "GIVE_EVERYTHING"}))
    case = get_case("C-1002")
    with pytest.raises(ProviderError):
        _provider(client).generate_resolution(case, workflow.gather_context(case), [])


def test_call_failure_is_a_provider_error():
    case = get_case("C-1002")
    with pytest.raises(ProviderError):
        _provider(StubClient(error=RuntimeError("throttled"))).generate_resolution(case, workflow.gather_context(case), [])


def test_missing_config_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("BEDROCK_INFERENCE_PROFILE", raising=False)
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    with pytest.raises(ProviderError):
        BedrockModelProvider(client=StubClient())


def test_profile_preferred_over_model_id(monkeypatch):
    monkeypatch.setenv("BEDROCK_INFERENCE_PROFILE", "us.profile")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "bare.model")
    assert BedrockModelProvider(client=StubClient()).model_id == "us.profile"


def test_workflow_survives_provider_error_and_validator_still_gates():
    bad = StubClient({"output": {"message": {"content": []}}})
    run = workflow.propose_resolution("C-1002", _provider(bad))
    assert run.status == workflow.PROVIDER_ERROR and run.proposal is None

    over_limit = {**GOOD_INPUT, "decision": "REFUND", "amount": 649.0}  # >$200 must be ESCALATE
    run = workflow.propose_resolution("C-1002", _provider(StubClient(_tool_response(over_limit))))
    assert run.status == workflow.VALIDATION_FAILED


def test_boto3_is_only_imported_lazily():
    import inspect

    import cosmic_resolve.bedrock_provider as module

    top_level = [line for line in inspect.getsource(module).splitlines() if line.startswith(("import boto3", "from boto3"))]
    assert top_level == []
