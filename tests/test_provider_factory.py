"""Provider configuration, the no-silent-fallback rule, agentic trace proof and credential safety.

Nothing here calls AWS. boto3 is replaced by a fake module whose client is a scripted object, and botocore
exceptions are stand-ins with the same class names and response shape. Trace writes go to a temporary file.
"""
import sys
import types

import pytest
from fastapi.testclient import TestClient

import api
from cosmic_resolve import config, provider_factory
from cosmic_resolve.bedrock_agent import BedrockAgentProvider
from cosmic_resolve.bedrock_provider import TOOL_NAME, BedrockModelProvider
from cosmic_resolve.checkpoint import reset_decided_for_tests
from cosmic_resolve.config import SETTINGS
from cosmic_resolve.model_provider import ProviderError, RuleBasedModelProvider
from cosmic_resolve.tools import get_case, get_policy
from cosmic_resolve.tracing import read_trace_events
from cosmic_resolve.workflow import gather_context

client = TestClient(api.app)

PROVIDER_VARS = (
    "MODEL_PROVIDER", "COSMIC_RESOLVE_LIVE", "COSMIC_RESOLVE_PIPELINE", "BEDROCK_INFERENCE_PROFILE",
    "BEDROCK_MODEL_ID", "AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE", "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "CHECKPOINT_WRITES_ENABLED",
)

# Marker values that must never appear in any response or trace. They look like credentials on purpose.
KEY_MARKER = "AKIAFAKEMARKER000001"
SECRET_MARKER = "secretmarkervalue0123456789"
TOKEN_MARKER = "tokenmarkervalue0123456789"
ARN_MARKER = "arn:aws:iam::123456789012:role/raw-role-name"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for name in PROVIDER_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(SETTINGS, "trace_path", tmp_path / "trace.jsonl")
    reset_decided_for_tests()
    yield tmp_path / "trace.jsonl"
    reset_decided_for_tests()


def _set_bedrock_env(monkeypatch, *, region=True, profile=True):
    monkeypatch.setenv("MODEL_PROVIDER", "bedrock")
    if region:
        monkeypatch.setenv("AWS_REGION", "us-east-2")
    if profile:
        monkeypatch.setenv("BEDROCK_INFERENCE_PROFILE", "us.anthropic.claude-sonnet-5-5")


def _fake_boto3(monkeypatch, scripted_client):
    """A stand-in boto3 whose client() returns the scripted object. Records the region it was asked for."""
    seen = {}
    fake = types.ModuleType("boto3")

    def client_factory(service, region_name=None, **kwargs):
        seen["service"] = service
        seen["region"] = region_name
        return scripted_client

    fake.client = client_factory
    monkeypatch.setitem(sys.modules, "boto3", fake)
    return seen


class ScriptedClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def converse(self, **kwargs):
        self.calls += 1
        if not self.responses:
            raise AssertionError("scripted client ran out of responses")
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class Raising:
    """A client whose every call fails with the given exception."""

    def __init__(self, error):
        self.error = error

    def converse(self, **kwargs):
        raise self.error


# botocore-shaped stand-ins. The provider classifies by class name and response code, so these are enough.
class ClientError(Exception):
    def __init__(self, code):
        super().__init__(f"raw AWS text {ARN_MARKER} {code}")
        self.response = {"Error": {"Code": code, "Message": f"raw AWS text {ARN_MARKER}"}}


class NoCredentialsError(Exception):
    pass


class ReadTimeoutError(Exception):
    pass


class EndpointConnectionError(Exception):
    pass


def _tool_use(name, payload, use_id):
    return {"toolUse": {"name": name, "input": payload, "toolUseId": use_id}}


def _reply(*blocks, stop="tool_use"):
    return {"output": {"message": {"role": "assistant", "content": list(blocks)}}, "stopReason": stop}


def _valid_submit_input(case_id="C-1001"):
    """A proposal the validator accepts for this case, produced by the offline rules so the fixtures are real."""
    case = get_case(case_id)
    policy = get_policy(case.market, case.category, case.case_type)
    proposal = RuleBasedModelProvider().generate_resolution(case, gather_context(case), policy)
    data = proposal.model_dump(mode="json")
    data.pop("case_id")
    root = data.pop("root_cause")
    data["root_cause_category"] = root["category"]
    data["root_cause_detail"] = root["detail"]
    return data


def _event_types(case_id):
    return [event.event_type for event in read_trace_events(case_id)]


def _propose(case_id="C-1001"):
    response = client.post(f"/api/cases/{case_id}/propose")
    assert response.status_code == 200, response.text
    return response


# --- configuration -------------------------------------------------------------------------------------------------

def test_default_provider_is_offline():
    assert config.effective_provider({}) == "offline"
    assert isinstance(provider_factory.build_provider({}), RuleBasedModelProvider)


def test_explicit_offline_selects_the_rules():
    assert isinstance(provider_factory.build_provider({"MODEL_PROVIDER": "offline"}), RuleBasedModelProvider)


@pytest.mark.parametrize("value", ["gemini", "bedrock-agent", "1", "BEDROCKX"])
def test_invalid_model_provider_is_a_configuration_error_that_does_not_echo_the_value(value):
    with pytest.raises(config.ProviderConfigError) as exc:
        provider_factory.build_provider({"MODEL_PROVIDER": value})
    assert "MODEL_PROVIDER must be" in str(exc.value)
    assert value not in str(exc.value)  # a value pasted into the wrong variable is never echoed back


@pytest.mark.parametrize(
    "environ",
    [
        {"MODEL_PROVIDER": "offline", "COSMIC_RESOLVE_LIVE": "true"},
        {"MODEL_PROVIDER": "bedrock", "COSMIC_RESOLVE_LIVE": "false"},
    ],
)
def test_contradictory_settings_fail_closed(environ):
    with pytest.raises(config.ProviderConfigError):
        config.effective_provider(environ)


def test_consistent_legacy_and_explicit_settings_are_accepted():
    assert config.effective_provider({"MODEL_PROVIDER": "bedrock", "COSMIC_RESOLVE_LIVE": "true"}) == "bedrock"
    assert config.effective_provider({"MODEL_PROVIDER": "offline", "COSMIC_RESOLVE_LIVE": "false"}) == "offline"


def test_legacy_local_switch_still_selects_bedrock_when_model_provider_is_unset():
    assert config.effective_provider({"COSMIC_RESOLVE_LIVE": "true"}) == "bedrock"
    assert config.live_provider_enabled({"COSMIC_RESOLVE_LIVE": "true"}) is True
    assert config.live_provider_enabled({}) is False


def test_offline_never_imports_constructs_or_calls_bedrock(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)  # importing boto3 would fail loudly

    def forbidden(*args, **kwargs):
        raise AssertionError("offline mode must not construct a Bedrock provider")

    monkeypatch.setattr(BedrockAgentProvider, "__init__", forbidden)
    monkeypatch.setattr(BedrockModelProvider, "__init__", forbidden)
    body = _propose().json()
    assert body["status"] == "AWAITING_APPROVAL"
    assert body["provider"] == "offline"


# --- selection and metadata ----------------------------------------------------------------------------------------

def test_bedrock_selects_the_agentic_provider(monkeypatch):
    _set_bedrock_env(monkeypatch)
    seen = _fake_boto3(monkeypatch, ScriptedClient([]))
    provider = provider_factory.build_provider()
    assert isinstance(provider, BedrockAgentProvider)
    assert provider_factory.provider_metadata(provider) == {"provider": "bedrock", "execution_mode": "agentic"}
    assert seen == {"service": "bedrock-runtime", "region": "us-east-2"}


def test_pipeline_flag_is_ignored_when_model_provider_is_bedrock(monkeypatch):
    _set_bedrock_env(monkeypatch)
    monkeypatch.setenv("COSMIC_RESOLVE_PIPELINE", "fixed")  # would pick the single-shot path under the legacy switch
    _fake_boto3(monkeypatch, ScriptedClient([]))
    assert isinstance(provider_factory.build_provider(), BedrockAgentProvider)


def test_pipeline_labels_map_to_the_existing_names():
    assert provider_factory.pipeline_label("rule_based") == "offline"
    assert provider_factory.pipeline_label("single_shot") == "bedrock"
    assert provider_factory.pipeline_label("agentic") == "agent"


# --- no silent fallback: setup failures ----------------------------------------------------------------------------

def test_missing_region_is_provider_error_not_offline(monkeypatch):
    _set_bedrock_env(monkeypatch, region=False)
    _fake_boto3(monkeypatch, ScriptedClient([]))
    body = _propose().json()
    assert body["status"] == "PROVIDER_ERROR"
    assert body["proposal"] is None
    assert body["provider"] == "bedrock"
    assert "AWS_REGION" in body["error"]
    assert "provider_error" in _event_types("C-1001")
    assert "proposal_generated" not in _event_types("C-1001")


def test_missing_profile_is_provider_error_not_offline(monkeypatch):
    _set_bedrock_env(monkeypatch, profile=False)
    _fake_boto3(monkeypatch, ScriptedClient([]))
    body = _propose().json()
    assert body["status"] == "PROVIDER_ERROR"
    assert body["proposal"] is None
    assert "BEDROCK_INFERENCE_PROFILE" in body["error"]


def test_missing_boto3_is_provider_error_not_offline(monkeypatch):
    _set_bedrock_env(monkeypatch)
    monkeypatch.setitem(sys.modules, "boto3", None)
    body = _propose().json()
    assert body["status"] == "PROVIDER_ERROR"
    assert body["proposal"] is None
    assert "boto3 is not installed" in body["error"]


# --- no silent fallback: runtime failures ---------------------------------------------------------------------------

RUNTIME_FAILURES = [
    (NoCredentialsError("no creds"), "Bedrock credentials are not configured."),
    (ClientError("ExpiredTokenException"), "Bedrock credentials have expired or are invalid."),
    (ClientError("InvalidClientTokenId"), "Bedrock credentials have expired or are invalid."),
    (ClientError("AccessDeniedException"), "Bedrock access is not authorized."),
    (ClientError("ThrottlingException"), "Bedrock is temporarily rate limited. Try again shortly."),
    (ClientError("ValidationException"), "Bedrock model configuration is invalid."),
    (ClientError("ResourceNotFoundException"), "The Bedrock model or inference profile was not found."),
    (ReadTimeoutError("slow"), "Bedrock did not respond in time."),
    (EndpointConnectionError("offline network"), "Could not reach Bedrock."),
    (RuntimeError("unexpected"), "The Bedrock call failed."),
]


@pytest.mark.parametrize("error, message", RUNTIME_FAILURES)
def test_runtime_failure_is_provider_error_with_a_safe_message(monkeypatch, error, message):
    _set_bedrock_env(monkeypatch)
    _fake_boto3(monkeypatch, Raising(error))
    body = _propose().json()
    assert body["status"] == "PROVIDER_ERROR"
    assert body["proposal"] is None
    assert body["error"] == message
    # Raw AWS text (account, ARN, request detail) never reaches the browser or the trace.
    assert ARN_MARKER not in str(body)
    trace_text = " ".join(str(e.details) for e in read_trace_events("C-1001"))
    assert ARN_MARKER not in trace_text
    assert "proposal_generated" not in _event_types("C-1001")


def test_malformed_model_reply_is_provider_error(monkeypatch):
    _set_bedrock_env(monkeypatch)
    _fake_boto3(monkeypatch, ScriptedClient([_reply({"text": "I think the answer is a refund."}, stop="end_turn")]))
    body = _propose().json()
    assert body["status"] == "PROVIDER_ERROR"
    assert "did not call the submit_resolution tool" in body["error"]


# --- agentic path and trace proof ----------------------------------------------------------------------------------

def test_agentic_loop_uses_tools_then_submits_and_the_trace_proves_it(monkeypatch):
    _set_bedrock_env(monkeypatch)
    script = ScriptedClient([
        _reply(_tool_use("get_order", {"order_id": "O-1001"}, "u1")),
        _reply(_tool_use("get_shipment", {"tracking_id": "T-1001"}, "u2")),
        _reply(_tool_use(TOOL_NAME, _valid_submit_input(), "u3")),
    ])
    _fake_boto3(monkeypatch, script)
    body = _propose().json()

    assert script.calls == 3
    assert body["status"] == "AWAITING_APPROVAL"
    assert body["provider"] == "bedrock"
    assert body["execution_mode"] == "agentic"
    assert body["pipeline"] == "agent"
    assert body["proposal"] is not None

    types = _event_types("C-1001")
    # The model's tool calls are recorded in the order it made them, all before the proposal is generated.
    tool_calls = [e.details["tool"] for e in read_trace_events("C-1001") if e.event_type == "tool_call"]
    assert tool_calls == ["get_order", "get_shipment"]
    assert types.index("provider_selected") < types.index("tool_call")
    assert types.index("tool_result") < types.index("proposal_generated") < types.index("validation_passed")


def test_provider_selected_event_names_the_provider_and_mode(monkeypatch):
    _propose()  # offline
    selected = [e for e in read_trace_events("C-1001") if e.event_type == "provider_selected"]
    assert len(selected) == 1
    assert selected[0].details["provider"] == "offline"
    assert selected[0].details["execution_mode"] == "rule_based"


# --- credentials are never returned or traced ---------------------------------------------------------------------

def test_credentials_never_appear_in_the_response_or_the_trace(monkeypatch):
    _set_bedrock_env(monkeypatch)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", KEY_MARKER)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", SECRET_MARKER)
    monkeypatch.setenv("AWS_SESSION_TOKEN", TOKEN_MARKER)
    script = ScriptedClient([_reply(_tool_use(TOOL_NAME, _valid_submit_input(), "u1"))])
    _fake_boto3(monkeypatch, script)
    response = _propose()
    trace_text = " ".join(str(e.details) + e.message for e in read_trace_events("C-1001"))
    for marker in (KEY_MARKER, SECRET_MARKER, TOKEN_MARKER):
        assert marker not in response.text
        assert marker not in trace_text


def test_error_path_does_not_leak_credentials_either(monkeypatch):
    _set_bedrock_env(monkeypatch)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", KEY_MARKER)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", SECRET_MARKER)
    _fake_boto3(monkeypatch, Raising(ClientError("ExpiredTokenException")))
    response = _propose()
    assert KEY_MARKER not in response.text and SECRET_MARKER not in response.text


# --- diagnostics ---------------------------------------------------------------------------------------------------

def test_diagnostics_report_categories_only(monkeypatch):
    _set_bedrock_env(monkeypatch)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", KEY_MARKER)
    _fake_boto3(monkeypatch, ScriptedClient([]))
    report = provider_factory.get_provider_diagnostics()
    assert report["configured_provider"] == "bedrock"
    assert report["boto3_importable"] is True
    assert report["region_configured"] is True
    assert report["model_configured"] is True
    assert report["credential_source"] is None  # not checked unless asked
    assert KEY_MARKER not in repr(report)


def test_diagnostics_detect_missing_boto3_and_region(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "bedrock")
    monkeypatch.setitem(sys.modules, "boto3", None)
    report = provider_factory.get_provider_diagnostics()
    assert report["boto3_importable"] is False
    assert report["region_configured"] is False
    assert report["model_configured"] is False


def test_diagnostics_report_invalid_configuration_without_raising(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "gemini")
    report = provider_factory.get_provider_diagnostics()
    assert report["configured_provider"] is None
    assert "MODEL_PROVIDER must be" in report["config_error"]


def test_credential_check_is_opt_in_and_never_raises(monkeypatch):
    _fake_boto3(monkeypatch, ScriptedClient([]))
    report = provider_factory.get_provider_diagnostics(check_credentials=True)
    # botocore is not installed in the test venv, so the check reports "error" rather than raising.
    assert isinstance(report["credential_source"], str)
    assert KEY_MARKER not in repr(report)


# --- decision route under contradictory config ----------------------------------------------------------------------

def test_decision_under_contradictory_config_is_a_controlled_503(monkeypatch):
    monkeypatch.setenv("CHECKPOINT_WRITES_ENABLED", "true")
    monkeypatch.setenv("MODEL_PROVIDER", "offline")
    monkeypatch.setenv("COSMIC_RESOLVE_LIVE", "true")
    response = client.post(
        "/api/cases/C-1001/decision",
        json={"action": "APPROVE", "proposal_fingerprint": "0" * 64, "reviewer": "Jordan"},
    )
    assert response.status_code == 503
    assert "disagree" in response.json()["detail"]
