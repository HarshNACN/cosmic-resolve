import json

import pytest

from cosmic_resolve import workflow
from cosmic_resolve.bedrock_agent import AGENT_SYSTEM_PROMPT, BedrockAgentProvider
from cosmic_resolve.bedrock_provider import TOOL_NAME
from cosmic_resolve.config import SETTINGS
from cosmic_resolve.model_provider import ProviderError, RuleBasedModelProvider
from cosmic_resolve.tracing import read_trace_events
from cosmic_resolve.tools import get_case, get_policy
from cosmic_resolve.workflow import gather_context


class ScriptedClient:
    """Plays back a fixed list of Converse responses and records every request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("scripted client ran out of responses")
        return self.responses.pop(0)


def tool_use(name, payload, use_id):
    return {"toolUse": {"name": name, "input": payload, "toolUseId": use_id}}


def reply(*blocks, stop="tool_use"):
    return {"output": {"message": {"role": "assistant", "content": list(blocks)}}, "stopReason": stop}


def submit_response(proposal_input):
    return reply(tool_use(TOOL_NAME, proposal_input, "submit-1"), stop="tool_use")


def valid_submit_input():
    """A proposal the validator accepts for C-1001, produced by the offline provider so the fixture data is real."""
    case, policy = _case_and_policy()
    proposal = RuleBasedModelProvider().generate_resolution(case, gather_context(case), policy)
    data = proposal.model_dump(mode="json")
    data.pop("case_id")
    root = data.pop("root_cause")
    data["root_cause_category"] = root["category"]
    data["root_cause_detail"] = root["detail"]
    return data


@pytest.fixture(autouse=True)
def trace_file(tmp_path, monkeypatch):
    path = tmp_path / "trace.jsonl"
    monkeypatch.setattr(SETTINGS, "trace_path", path)
    return path


def _provider(client, **kwargs):
    return BedrockAgentProvider(client=client, model_id="test-profile", **kwargs)


def _case_and_policy():
    case = get_case("C-1001")
    return case, get_policy(case.market, case.category, case.case_type)


def test_model_chosen_tool_order_is_honored(trace_file):
    client = ScriptedClient([
        reply(tool_use("get_shipment", {"tracking_id": "T-1001"}, "u1")),
        reply(tool_use("get_order", {"order_id": "O-1001"}, "u2")),
        submit_response(valid_submit_input()),
    ])
    case, policy = _case_and_policy()

    _provider(client).investigate(case, policy)

    calls = [e for e in read_trace_events("C-1001", trace_path=trace_file) if e.event_type == "tool_call"]
    assert [e.details["tool"] for e in calls] == ["get_shipment", "get_order"]
    assert len(client.calls) == 3


def test_error_result_is_returned_to_model_and_recovered_from():
    client = ScriptedClient([
        reply(tool_use("get_shipment", {"tracking_id": "T-9999"}, "u1")),
        submit_response(valid_submit_input()),
    ])
    case, policy = _case_and_policy()

    proposal = _provider(client).investigate(case, policy)

    assert proposal.case_id == "C-1001"
    tool_result = client.calls[1]["messages"][-1]["content"][0]["toolResult"]
    assert tool_result["toolUseId"] == "u1"
    assert tool_result["status"] == "error"
    assert "T-9999" in tool_result["content"][0]["json"]["error"]


def test_max_turns_cap_trips():
    looping = reply(tool_use("get_case", {"case_id": "C-1001"}, "u"))
    client = ScriptedClient([looping, looping, looping])
    case, policy = _case_and_policy()

    with pytest.raises(ProviderError, match="within 3 turns"):
        _provider(client, max_turns=3).investigate(case, policy)
    assert len(client.calls) == 3


def test_write_tool_name_is_rejected_as_error_result():
    client = ScriptedClient([
        reply(tool_use("issue_refund", {"order_id": "O-1001", "amount": "10", "reason": "x"}, "u1")),
        submit_response(valid_submit_input()),
    ])
    case, policy = _case_and_policy()

    _provider(client).investigate(case, policy)

    result = client.calls[1]["messages"][-1]["content"][0]["toolResult"]
    assert result["status"] == "error"
    assert "Unknown tool" in result["content"][0]["json"]["error"]


def test_write_tools_are_not_offered_to_the_model():
    client = ScriptedClient([submit_response(valid_submit_input())])
    case, policy = _case_and_policy()

    _provider(client).investigate(case, policy)

    offered = {spec["toolSpec"]["name"] for spec in client.calls[0]["toolConfig"]["tools"]}
    assert offered == {
        "get_case", "get_order", "get_customer", "get_shipment",
        "check_inventory", "get_policy", "get_product_listing", TOOL_NAME,
    }


def test_plain_text_reply_is_a_provider_error():
    client = ScriptedClient([reply({"text": "I think we should refund."}, stop="end_turn")])
    case, policy = _case_and_policy()

    with pytest.raises(ProviderError, match="did not call the submit_resolution tool"):
        _provider(client).investigate(case, policy)


def test_bedrock_failure_is_a_provider_error():
    class Failing:
        def converse(self, **kwargs):
            raise RuntimeError("throttled")

    case, policy = _case_and_policy()
    # Browser-safe message: the raw exception text is not returned, only the category.
    with pytest.raises(ProviderError, match="The Bedrock call failed.") as exc:
        _provider(Failing()).investigate(case, policy)
    assert "throttled" not in str(exc.value)


def test_customer_name_never_reaches_the_model():
    client = ScriptedClient([
        reply(tool_use("get_customer", {"customer_id": "C-001"}, "u1")),
        submit_response(valid_submit_input()),
    ])
    case, policy = _case_and_policy()

    _provider(client).investigate(case, policy)

    result_text = json.dumps(client.calls[1]["messages"][-1])
    assert '"loyalty_tier"' in result_text
    assert '"name"' not in result_text


def test_trace_records_each_tool_call_and_result(trace_file):
    client = ScriptedClient([
        reply(tool_use("get_order", {"order_id": "O-1001"}, "u1")),
        submit_response(valid_submit_input()),
    ])
    case, policy = _case_and_policy()

    _provider(client).investigate(case, policy)

    events = read_trace_events("C-1001", trace_path=trace_file)
    types = [e.event_type for e in events]
    assert types == ["tool_call", "tool_result"]
    assert events[0].details == {"case_id": "C-1001", "turn": 1, "tool": "get_order", "arguments": {"order_id": "O-1001"}}
    assert events[1].details["status"] == "success"
    assert events[1].details["result"]["order_id"] == "O-1001"


def test_system_prompt_names_the_read_tools_and_investigation_step():
    assert "Investigate before deciding" in AGENT_SYSTEM_PROMPT
    assert "submit_resolution" in AGENT_SYSTEM_PROMPT


def test_workflow_uses_investigation_and_still_validates(trace_file):
    client = ScriptedClient([
        reply(tool_use("get_shipment", {"tracking_id": "T-1001"}, "u1")),
        submit_response(valid_submit_input()),
    ])

    run = workflow.propose_resolution("C-1001", _provider(client))

    assert run.status == workflow.AWAITING_APPROVAL
    assert run.context["customer"] is not None
    types = [e.event_type for e in read_trace_events("C-1001", trace_path=trace_file)]
    # The model's tool calls happen before the deterministic validator fetch.
    assert types.index("tool_call") < types.index("proposal_generated")
    assert types.count("context_gathered") == 1
    assert types.index("provider_request") < types.index("tool_call")


def test_fixed_pipeline_provider_still_pre_fetches(trace_file):
    class Fixed:
        def generate_resolution(self, case, context, policy):
            return RuleBasedModelProvider().generate_resolution(case, context, policy)

    run = workflow.propose_resolution("C-1001", Fixed())

    assert run.status == workflow.AWAITING_APPROVAL
    types = [e.event_type for e in read_trace_events("C-1001", trace_path=trace_file)]
    assert types.index("context_gathered") < types.index("provider_request")


def _fake_boto3(monkeypatch):
    """The providers read the model ID and region from os.environ and import boto3 lazily, so stub the client."""
    import sys
    import types

    fake = types.ModuleType("boto3")
    fake.client = lambda *args, **kwargs: object()
    monkeypatch.setitem(sys.modules, "boto3", fake)


def test_selector_defaults_to_fixed_pipeline(monkeypatch):
    from cosmic_resolve.bedrock_agent import live_bedrock_provider
    from cosmic_resolve.bedrock_provider import BedrockModelProvider

    _fake_boto3(monkeypatch)
    monkeypatch.setenv("BEDROCK_INFERENCE_PROFILE", "p")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.delenv("COSMIC_RESOLVE_PIPELINE", raising=False)
    provider = live_bedrock_provider({"BEDROCK_INFERENCE_PROFILE": "p", "AWS_REGION": "us-east-1"})
    assert type(provider) is BedrockModelProvider


def test_selector_agent_flag_selects_loop(monkeypatch):
    from cosmic_resolve.bedrock_agent import live_bedrock_provider

    _fake_boto3(monkeypatch)
    monkeypatch.setenv("BEDROCK_INFERENCE_PROFILE", "p")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("COSMIC_RESOLVE_PIPELINE", "agent")
    env = {"BEDROCK_INFERENCE_PROFILE": "p", "AWS_REGION": "us-east-1", "COSMIC_RESOLVE_PIPELINE": "agent"}
    assert isinstance(live_bedrock_provider(env), BedrockAgentProvider)


def test_eval_row_counts_only_model_tool_calls_and_checks_evidence():
    from cosmic_resolve.evaluation import run_case

    client = ScriptedClient([
        reply(tool_use("get_order", {"order_id": "O-1001"}, "u1")),
        reply(tool_use("get_shipment", {"tracking_id": "T-1001"}, "u2")),
        reply(tool_use("get_customer", {"customer_id": "C-001"}, "u3")),
        submit_response(valid_submit_input()),
    ])
    row = run_case({"case_id": "C-1001", "expected_decision": "REPLACE"}, _provider(client))

    assert row["tool_calls"] == 3  # the validator's own fetches are not counted
    assert row["tool_names"] == ["get_order", "get_shipment", "get_customer"]
    assert row["missing_evidence"] == []


def test_eval_row_reports_missing_required_evidence():
    from cosmic_resolve.evaluation import run_case

    client = ScriptedClient([
        reply(tool_use("get_order", {"order_id": "O-1001"}, "u1")),
        submit_response(valid_submit_input()),
    ])
    row = run_case({"case_id": "C-1001", "expected_decision": "REPLACE"}, _provider(client))

    assert row["tool_calls"] == 1
    assert row["missing_evidence"] == ["get_shipment", "get_customer"]


def test_fixed_pipeline_rows_have_no_evidence_check():
    from cosmic_resolve.evaluation import run_case

    row = run_case({"case_id": "C-1001", "expected_decision": "REPLACE"}, RuleBasedModelProvider())

    assert row["missing_evidence"] is None
    assert row["tool_names"] is None
    assert row["tool_calls"] == 7


def _ticking_clock(step: float):
    """Each read advances the clock by `step` seconds, so the time limit trips after a known number of checks."""
    ticks = iter(x * step for x in range(10_000))
    return lambda: next(ticks)


def test_investigation_stops_when_the_time_budget_is_spent():
    client = ScriptedClient([
        reply(tool_use("get_shipment", {"tracking_id": "T-1001"}, "u1")),
        reply(tool_use("get_order", {"order_id": "O-1001"}, "u2")),
        submit_response(valid_submit_input()),
    ])
    case, policy = _case_and_policy()
    # Start at 0; checks before turns 1, 2 and 3 read 20, 40, 60 seconds. The 45-second budget trips before turn 3.
    provider = _provider(client, max_seconds=45, clock=_ticking_clock(20))

    with pytest.raises(ProviderError, match="exceeded 45 seconds"):
        provider.investigate(case, policy)
    assert len(client.calls) == 2  # no third model call once the budget is gone


def test_investigation_within_the_time_budget_completes():
    client = ScriptedClient([
        reply(tool_use("get_shipment", {"tracking_id": "T-1001"}, "u1")),
        submit_response(valid_submit_input()),
    ])
    case, policy = _case_and_policy()
    proposal = _provider(client, max_seconds=45, clock=_ticking_clock(20)).investigate(case, policy)
    assert proposal.case_id == "C-1001"


def test_time_budget_must_be_positive():
    with pytest.raises(ValueError):
        _provider(ScriptedClient([]), max_seconds=0)
