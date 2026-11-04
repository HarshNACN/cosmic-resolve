"""The one place that chooses the recommendation provider, and what the API reports about it.

Configuration (see config.effective_provider):
    MODEL_PROVIDER=offline   deterministic rules. The default when nothing is set. Never touches AWS.
    MODEL_PROVIDER=bedrock   the agentic Bedrock loop (BedrockAgentProvider): Claude chooses read tools.

Legacy: COSMIC_RESOLVE_LIVE=true is honoured only when MODEL_PROVIDER is unset, and then keeps the existing
COSMIC_RESOLVE_PIPELINE behaviour, so local demos and scripts do not change.

Failure policy: once Bedrock is selected, no failure falls back to the offline rules. A missing boto3, region,
model/profile or credential raises ProviderError here, and the API turns it into PROVIDER_ERROR.

Credentials are never read here. boto3's standard chain loads them (environment variables on Vercel, the login
profile locally). Nothing in this module returns a credential value, account ID or ARN.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import sys
from collections.abc import Mapping
from typing import Any

from . import config
from .bedrock_agent import BedrockAgentProvider, select_provider
from .bedrock_provider import BedrockModelProvider
from .model_provider import ModelProvider, ProviderError, RuleBasedModelProvider

logger = logging.getLogger(__name__)

# Maps the execution mode to the older "pipeline" label, which the API keeps for compatibility.
PIPELINE_BY_MODE = {"rule_based": "offline", "single_shot": "bedrock", "agentic": "agent"}


def build_provider(environ: Mapping[str, str] = os.environ) -> ModelProvider:
    """The provider for this request. Raises ProviderConfigError for contradictory settings and ProviderError
    when Bedrock is selected but cannot be set up. It never returns the offline provider as a substitute."""
    choice = config.effective_provider(environ)
    if choice == config.PROVIDER_OFFLINE:
        return RuleBasedModelProvider()
    if config.provider_setting(environ) is None:
        # Legacy local switch: COSMIC_RESOLVE_LIVE=true with COSMIC_RESOLVE_PIPELINE picks agent or fixed pipeline.
        return select_provider(True, environ)
    return BedrockAgentProvider()


def provider_metadata(provider: object) -> dict[str, str]:
    """Safe labels for a built provider: which provider ran and how it reasoned. No configuration values."""
    if isinstance(provider, RuleBasedModelProvider):
        return {"provider": "offline", "execution_mode": "rule_based"}
    if isinstance(provider, BedrockModelProvider):
        return {
            "provider": getattr(provider, "provider_name", "bedrock"),
            "execution_mode": getattr(provider, "execution_mode", "single_shot"),
        }
    # A stand-in provider that is not one of ours reports as the single-shot Bedrock path. Only the real agent class
    # is "agentic", which keeps the pipeline label the same as before this factory existed.
    if isinstance(provider, BedrockAgentProvider):
        return {"provider": "bedrock", "execution_mode": "agentic"}
    return {"provider": "bedrock", "execution_mode": "single_shot"}


def configured_metadata(environ: Mapping[str, str] = os.environ) -> dict[str, str]:
    """The labels the configuration would produce, for a request that failed before a provider existed."""
    if config.effective_provider(environ) == config.PROVIDER_OFFLINE:
        return {"provider": "offline", "execution_mode": "rule_based"}
    if config.provider_setting(environ) is not None or environ.get("COSMIC_RESOLVE_PIPELINE", "").strip().lower() == "agent":
        return {"provider": "bedrock", "execution_mode": "agentic"}
    return {"provider": "bedrock", "execution_mode": "single_shot"}


def pipeline_label(execution_mode: str) -> str:
    return PIPELINE_BY_MODE.get(execution_mode, "bedrock")


def get_provider_diagnostics(environ: Mapping[str, str] = os.environ, *, check_credentials: bool = False) -> dict[str, Any]:
    """A safe readiness report for tests and server logs. It returns booleans and categories only.

    It never returns a credential value, account ID or ARN, and it sends no request to AWS. With
    check_credentials=True it asks botocore which credential source it would use, which can read local
    login state. The default is False, so nothing touches the credential chain unless asked.
    """
    try:
        configured = config.effective_provider(environ)
        config_error = None
    except config.ProviderConfigError as exc:
        configured = None
        config_error = str(exc)
    report: dict[str, Any] = {
        "configured_provider": configured,
        "config_error": config_error,
        "boto3_importable": _boto3_importable(),
        "region_configured": bool(environ.get("AWS_REGION") or environ.get("AWS_DEFAULT_REGION")),
        "model_configured": bool(environ.get("BEDROCK_INFERENCE_PROFILE") or environ.get("BEDROCK_MODEL_ID")),
        "credential_source": None,
    }
    if check_credentials and report["boto3_importable"]:
        report["credential_source"] = _credential_source_category()
    return report


def _boto3_importable() -> bool:
    """True when `import boto3` would succeed. A module already in sys.modules is judged by what it is."""
    if "boto3" in sys.modules:
        return sys.modules["boto3"] is not None
    try:
        return importlib.util.find_spec("boto3") is not None
    except (ImportError, ValueError):
        return False


def _credential_source_category() -> str:
    """The name of the credential method botocore would use (for example "env" or "sso"). No secret is read out."""
    try:
        import botocore.session  # local import: only the diagnostic needs botocore

        credentials = botocore.session.get_session().get_credentials()
    except Exception:  # noqa: BLE001 - a diagnostic must never raise into a request
        return "error"
    if credentials is None:
        return "none"
    return str(getattr(credentials, "method", "unknown"))


def log_provider_selected(provider_info: dict[str, str], report: dict[str, Any]) -> None:
    """Server log line for production: provider, region set or not, model set or not. Never a value."""
    logger.info(
        "Provider selected: %s (%s); region configured=%s; model configured=%s",
        provider_info["provider"],
        provider_info["execution_mode"],
        report["region_configured"],
        report["model_configured"],
    )
