import os
from collections.abc import Mapping
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = Path(__file__).resolve().parent.parent

# Load <repo>/.env (git-ignored) if present. Variables already set in the shell win.
load_dotenv(ROOT_DIR / ".env", override=False)

# backend/data is the runtime copy of the fixtures. It ships inside the independently built Vercel
# backend service, which cannot read the root data/ folder. tests/test_data_integrity.py and
# tests/test_deployment.py fail if it drifts from root data/. Root data/ remains the source for
# evals and teammates' scripts. Do not change fixture contents here without updating both.
DATA_DIR = BACKEND_DIR / "data"
EVALS_DIR = ROOT_DIR / "evals"
TRACE_DIR = ROOT_DIR / "traces"

# Vercel's only writable location is /tmp, which is ephemeral and private to each function instance.
# Trace availability on Vercel is best-effort: it can be empty or partial, and nothing is durable.
VERCEL_TRACE_PATH = Path("/tmp/cosmic-resolve-traces.jsonl")


def default_trace_path(environ: Mapping[str, str] = os.environ) -> Path:
    """Repo-local traces/ when running locally; /tmp (best-effort) when VERCEL=1."""
    if environ.get("VERCEL") == "1":
        return VERCEL_TRACE_PATH
    return TRACE_DIR / "mock_actions.jsonl"


ON_VERCEL = os.environ.get("VERCEL") == "1"
DEFAULT_TRACE_PATH = default_trace_path()

_TRUE_VALUES = {"1", "true", "yes", "on"}


def checkpoint_writes_enabled(environ: Mapping[str, str] = os.environ) -> bool:
    """Whether the human-checkpoint decision endpoint may execute gated (mock) writes.

    Off unless CHECKPOINT_WRITES_ENABLED is explicitly set to a true value. It is read on every call, so
    tests and local sessions can change it. vercel.json must never set it, so the public Vercel deployment
    stays read-only at the checkpoint. This is an application-level switch, not authentication.
    """
    return environ.get("CHECKPOINT_WRITES_ENABLED", "").strip().lower() in _TRUE_VALUES


PROVIDER_OFFLINE = "offline"
PROVIDER_BEDROCK = "bedrock"
PROVIDER_VALUES = (PROVIDER_OFFLINE, PROVIDER_BEDROCK)


class ProviderConfigError(ValueError):
    """The provider configuration is invalid or contradictory. Raised instead of guessing a provider.

    The message never echoes the configured value, in case someone pasted a secret into the wrong variable.
    """


def provider_setting(environ: Mapping[str, str] = os.environ) -> str | None:
    """The explicit MODEL_PROVIDER value ("offline" or "bedrock"), or None when it is unset."""
    raw = environ.get("MODEL_PROVIDER", "").strip().lower()
    if not raw:
        return None
    if raw not in PROVIDER_VALUES:
        raise ProviderConfigError("MODEL_PROVIDER must be 'offline' or 'bedrock'.")
    return raw


def effective_provider(environ: Mapping[str, str] = os.environ) -> str:
    """Which provider serves recommendations: "offline" or "bedrock". Read on every call.

    MODEL_PROVIDER is the authoritative setting and defaults to offline. The older local switch
    COSMIC_RESOLVE_LIVE is honoured only when MODEL_PROVIDER is unset, so existing local demos keep working. If both
    are set and disagree, this raises instead of picking one.
    """
    explicit = provider_setting(environ)
    legacy_raw = environ.get("COSMIC_RESOLVE_LIVE", "").strip().lower()
    legacy_on = legacy_raw in _TRUE_VALUES
    if explicit is None:
        return PROVIDER_BEDROCK if legacy_on else PROVIDER_OFFLINE
    if legacy_raw and legacy_on != (explicit == PROVIDER_BEDROCK):
        raise ProviderConfigError("MODEL_PROVIDER and COSMIC_RESOLVE_LIVE disagree. Unset COSMIC_RESOLVE_LIVE.")
    return explicit


def live_provider_enabled(environ: Mapping[str, str] = os.environ) -> bool:
    """Whether recommendations come from Bedrock rather than the offline rules. See effective_provider."""
    return effective_provider(environ) == PROVIDER_BEDROCK

# Flat human-approval threshold for all loyalty tiers (PRD decision #1). Stated in data/policies.json (clauses
# DOA-03, LD-03, RET-04); the model prompts are generated from this value.
ESCALATION_THRESHOLD_USD = 200.0

# Maximum GOODWILL_CREDIT per loyalty tier, enforced in code (PRD decision #2). These are the policy-book values
# stated in data/policies.json (clauses DOA-04 and LD-04); tests/test_policies.py checks they still match.
GOODWILL_CAPS_USD: dict[str, float] = {
    "BRONZE": 5.0,
    "SILVER": 10.0,
    "GOLD": 20.0,
    "PLATINUM": 40.0,
}


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data_dir: Path = Field(default_factory=lambda: DATA_DIR)
    evals_dir: Path = Field(default_factory=lambda: EVALS_DIR)
    trace_path: Path = Field(default_factory=lambda: DEFAULT_TRACE_PATH)
    default_market: str = "US"
    default_category: str = "GADGETS"
    default_case_type: str = "DAMAGED_ON_ARRIVAL"


SETTINGS = Settings()
