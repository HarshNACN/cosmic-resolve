"""Token usage tracking in the Bedrock providers, and the prompt wiring (policy constants, get_case guidance).

Offline only: scripted clients stand in for Bedrock.
"""
import json

import pytest

from cosmic_resolve import workflow
from cosmic_resolve.agent import CLAIMS_ESCALATION_THRESHOLD
from cosmic_resolve.bedrock_agent import AGENT_SYSTEM_PROMPT, BedrockAgentProvider
from cosmic_resolve.bedrock_provider import SYSTEM_PROMPT, TOOL_NAME, BedrockModelProvider
from cosmic_resolve.config import DATA_DIR, ESCALATION_THRESHOLD_USD, GOODWILL_CAPS_USD, SETTINGS
from cosmic_resolve.model_provider import RuleBasedModelProvider
from cosmic_resolve.tool_registry import read_tool_specs
from cosmic_resolve.tools import get_case, get_policy


class ScriptedClient:
    def __init__(self, responses):
        self.responses = list(responses)

    def converse(self, **kwargs):
        if not self.responses:
            raise AssertionError("scripted client ran out of responses")
        return self.responses.pop(0)


class FailingClient:
    def converse(self, **kwargs):
        raise RuntimeError("simulated outage")


def tool_use(name, payload, use_id):
    return {"toolUse": {"name": name, "input": payload, "toolUseId": use_id}}


def reply(*blocks, stop="tool_use", usage=None):
    response = {"output": {"message": {"role": "assistant", "content": list(blocks)}}, "stopReason": stop}
    if usage is not None:
        response["usage"] = {"inputTokens": usage[0], "outputTokens": usage[1], "totalTokens": sum(usage)}
    return response


def submit_input():
    """A proposal the validator accepts for C-1001, produced by the offline provider so the fixture data is real."""
    case = get_case("C-1001")
    policy = get_policy(case.market, case.category, case.case_type)
    proposal = RuleBasedModelProvider().generate_resolution(case, workflow.gather_context(case), policy)
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


def _agent(client):
    return BedrockAgentProvider(client=client, model_id="test-profile")


def _case_and_policy():
    case = get_case("C-1001")
    return case, get_policy(case.market, case.category, case.case_type)


# --- Usage tracking -----------------------------------------------------------------------------------------------------

def test_agent_usage_is_summed_over_every_turn():
    client = ScriptedClient([
        reply(tool_use("get_shipment", {"tracking_id": "T-1001"}, "u1"), usage=(100, 10)),
        reply(tool_use("get_order", {"order_id": "O-1001"}, "u2"), usage=(150, 12)),
        reply(tool_use(TOOL_NAME, submit_input(), "s1"), usage=(200, 30)),
    ])
    provider = _agent(client)
    case, policy = _case_and_policy()

    provider.investigate(case, policy)

    assert provider.last_usage == {"inputTokens": 450, "outputTokens": 52, "turns": 3}


def test_agent_usage_resets_at_the_start_of_each_run():
    provider = _agent(ScriptedClient([reply(tool_use(TOOL_NAME, submit_input(), "s1"), usage=(100, 5))]))
    case, policy = _case_and_policy()
    provider.investigate(case, policy)
    assert provider.last_usage["turns"] == 1

    provider._client = FailingClient()  # second run fails on its first call
    with pytest.raises(Exception):
        provider.investigate(case, policy)
    assert provider.last_usage == {"inputTokens": 0, "outputTokens": 0, "turns": 0}


def test_agent_turn_without_usage_counts_as_zero_tokens():
    provider = _agent(ScriptedClient([reply(tool_use(TOOL_NAME, submit_input(), "s1"))]))
    case, policy = _case_and_policy()
    provider.investigate(case, policy)
    assert provider.last_usage == {"inputTokens": 0, "outputTokens": 0, "turns": 1}


def test_fixed_pipeline_records_one_turn_of_usage():
    response = reply(tool_use(TOOL_NAME, submit_input(), "s1"), stop="tool_use", usage=(1200, 80))
    provider = BedrockModelProvider(client=ScriptedClient([response]), model_id="test-profile")
    assert provider.last_usage is None  # nothing before a call

    case, policy = _case_and_policy()
    provider.generate_resolution(case, workflow.gather_context(case), policy)

    assert provider.last_usage == {"inputTokens": 1200, "outputTokens": 80, "turns": 1}


# --- Prompt wiring ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("prompt", [SYSTEM_PROMPT, AGENT_SYSTEM_PROMPT])
def test_policy_numbers_in_both_prompts_come_from_the_constants(prompt):
    assert f"${ESCALATION_THRESHOLD_USD:.0f}" in prompt
    assert f"{CLAIMS_ESCALATION_THRESHOLD} or more claims" in prompt
    for tier, cap in GOODWILL_CAPS_USD.items():
        assert f"{tier.capitalize()} ${cap:.0f}" in prompt


def test_policy_clause_sets_state_the_limits_the_prompt_repeats():
    """Every case type's clauses must state the $200 and 3-claims rules; the goodwill caps where goodwill applies."""
    clauses = json.loads((DATA_DIR / "policies.json").read_text(encoding="utf-8"))
    by_type: dict[str, str] = {}
    for clause in clauses:
        by_type[clause["case_type"]] = by_type.get(clause["case_type"], "") + " " + clause["text"]
    for case_type, text in by_type.items():
        assert f"${ESCALATION_THRESHOLD_USD:.0f}" in text, case_type
        assert f"{CLAIMS_ESCALATION_THRESHOLD} or more claims" in text, case_type
        if "Goodwill credit is capped" in text:
            for tier, cap in GOODWILL_CAPS_USD.items():
                assert f"{tier.capitalize()} ${cap:.0f}" in text, (case_type, tier)


def test_agent_prompt_says_the_header_is_provided_and_get_case_is_optional():
    assert "already in the first message" in AGENT_SYSTEM_PROMPT
    case, policy = _case_and_policy()
    message = _agent(ScriptedClient([])).investigation_message(case, policy)
    assert "already loaded; get_case is not needed" in message
    spec = next(s["toolSpec"] for s in read_tool_specs() if s["toolSpec"]["name"] == "get_case")
    assert "already in the first message" in spec["description"]
    assert "get_case" in {s["toolSpec"]["name"] for s in read_tool_specs()}  # still registered (PRD lists it)
