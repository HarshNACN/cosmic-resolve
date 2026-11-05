"""Shared test setup.

The backend loads the repo's git-ignored .env at import time. A developer who runs live demos has MODEL_PROVIDER=bedrock
there, which would make every test that builds a provider call Bedrock (slow, needs AWS, not deterministic). Tests must
never make live AWS or Bedrock calls, so each test starts from the offline provider. A test that needs another setting
sets it itself with monkeypatch.setenv, which overrides this.
"""
import pytest


@pytest.fixture(autouse=True)
def _offline_provider_by_default(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "offline")
    monkeypatch.delenv("COSMIC_RESOLVE_LIVE", raising=False)
    monkeypatch.delenv("COSMIC_RESOLVE_PIPELINE", raising=False)
