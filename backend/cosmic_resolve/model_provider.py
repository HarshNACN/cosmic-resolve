from __future__ import annotations

from typing import Any, Protocol, Sequence

from .models import Decision, ResolutionProposal, SupportCase


class ModelProvider(Protocol):
    def generate_resolution(
        self,
        case: SupportCase,
        context: dict[str, Any],
        applicable_policy: Sequence[Any],
    ) -> ResolutionProposal:
        ...


class NoopModelProvider:
    """Placeholder provider used when no live model is configured."""

    def generate_resolution(
        self,
        case: SupportCase,
        context: dict[str, Any],
        applicable_policy: Sequence[Any],
    ) -> ResolutionProposal:
        raise NotImplementedError("No model provider is configured for this starter repository.")


DEFAULT_PROVIDER = NoopModelProvider()
