from __future__ import annotations

from typing import Any, Protocol, Sequence

from .agent import ResolutionAgent
from .models import ResolutionProposal, RootCause, SupportCase


class ProviderError(RuntimeError):
    """A model provider could not produce a usable proposal (call failed or output malformed)."""


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


_ROOT_CAUSES = {
    "DAMAGED_ON_ARRIVAL": "CARRIER_DAMAGE",
    "LATE_DELIVERY": "CARRIER_DELAY",
    "RETURN_REQUEST": "PRODUCT_EXPECTATION",
}


class RuleBasedModelProvider:
    """Deterministic offline provider. Builds a proposal from the read-tool context with no model call.

    Stands in for the Bedrock-backed provider so the full loop can run, be tested and be evaluated offline.
    """

    def __init__(self, agent: ResolutionAgent | None = None) -> None:
        self._agent = agent or ResolutionAgent()

    def generate_resolution(
        self,
        case: SupportCase,
        context: dict[str, Any],
        applicable_policy: Sequence[Any],
    ) -> ResolutionProposal:
        order = context["order"]
        shipment = context["shipment"]
        evidence = [f"Shipment {shipment.tracking_id} status: {shipment.status}"]
        evidence += [f"Carrier event: {event}" for event in shipment.events]
        if shipment.customer_photo_provided:
            evidence.append("Customer provided a photo")
        root_cause = RootCause(
            category=_ROOT_CAUSES.get(case.case_type, "UNKNOWN"),
            detail=case.complaint_text,
        )
        return self._agent.generate_proposal(case, list(applicable_policy), order.price, evidence, root_cause)


DEFAULT_PROVIDER = NoopModelProvider()
