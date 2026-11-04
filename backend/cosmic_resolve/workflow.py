"""End-to-end resolution loop: read tools -> proposal -> validator -> approval checkpoint -> gated writes.

The loop is split in two so a human checkpoint sits between the halves:
    run = propose_resolution(case_id, provider)    # read-only, never writes
    run = apply_approval(run, approval)            # the only path to write tools
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .model_provider import ModelProvider, ProviderError
from .models import ApprovalDecision, Decision, ResolutionProposal, SupportCase
from .tools import (
    DomainLookupError,
    check_inventory,
    create_replacement,
    escalate,
    get_case,
    get_customer,
    get_order,
    get_policy,
    get_product_listing,
    get_shipment,
    issue_refund,
    issue_store_credit,
    send_customer_message,
    tag_root_cause,
)
from .tracing import append_case_event
from .validators import validate_proposal

AWAITING_APPROVAL = "AWAITING_APPROVAL"
VALIDATION_FAILED = "VALIDATION_FAILED"
NO_POLICY = "NO_POLICY"
PROVIDER_ERROR = "PROVIDER_ERROR"
REJECTED = "REJECTED"
EXECUTED = "EXECUTED"


@dataclass
class CaseRun:
    case: SupportCase
    status: str
    context: dict[str, Any] = field(default_factory=dict)
    policy: list = field(default_factory=list)
    proposal: ResolutionProposal | None = None
    error: str | None = None
    actions: list[dict[str, Any]] = field(default_factory=list)


def _trace_exchange(case_id: str, provider: Any) -> None:
    """Record the full prompt and model reply when the provider exposes them (Bedrock does; offline does not)."""
    exchange = getattr(provider, "last_exchange", None)
    if exchange:
        append_case_event(case_id, "model_exchange", "Full prompt and model response", **exchange)


def gather_context(case: SupportCase) -> dict[str, Any]:
    """Call the read tools. Order, customer and shipment are required; product and inventory are optional."""
    order = get_order(case.order_id)
    context: dict[str, Any] = {
        "order": order,
        "customer": get_customer(case.customer_id),
        "shipment": get_shipment(case.tracking_id),
        "product": None,
        "inventory": None,
    }
    try:
        context["product"] = get_product_listing(order.sku)
    except DomainLookupError:
        pass
    try:
        context["inventory"] = check_inventory(order.sku, order.fulfillment_region)
    except DomainLookupError:
        pass
    return context


def propose_resolution(case_id: str, provider: ModelProvider, *, provider_info: dict[str, str] | None = None) -> CaseRun:
    """Read-only half of the loop. Produces a validated proposal awaiting a human decision.

    Providers with an `investigate` method (the agent loop) choose their own read tools, so the code does not
    pre-fetch the case records for them. Everything else (policy, validator inputs) is still fetched by code.
    `provider_info` ({"provider", "execution_mode"}) is recorded as a provider_selected trace event when given.
    """
    case = get_case(case_id)
    append_case_event(case_id, "case_loaded", "Case loaded", case_type=case.case_type)
    if provider_info:
        append_case_event(
            case_id,
            "provider_selected",
            f"Provider: {provider_info['provider']} ({provider_info['execution_mode']})",
            provider=provider_info["provider"],
            execution_mode=provider_info["execution_mode"],
        )

    investigates = callable(getattr(provider, "investigate", None))
    context: dict[str, Any] = {}
    if not investigates:
        context = gather_context(case)
        append_case_event(case_id, "context_gathered", "Read tools complete", loaded=[k for k, v in context.items() if v is not None])

    try:
        policy = get_policy(case.market, case.category, case.case_type)
    except DomainLookupError as exc:
        # PRD 6.1 fallback: no applicable clause means a human must handle it. No proposal can cite a clause.
        append_case_event(case_id, "no_policy", "No applicable policy clause; needs manual handling", error=str(exc))
        return CaseRun(case=case, status=NO_POLICY, context=context, error=str(exc))

    append_case_event(case_id, "provider_request", "Requesting resolution", clause_ids=[c.clause_id for c in policy])
    try:
        if investigates:
            proposal = provider.investigate(case, policy)
        else:
            proposal = provider.generate_resolution(case, context, policy)
    except ProviderError as exc:
        _trace_exchange(case_id, provider)
        append_case_event(case_id, "provider_error", "Provider failed to produce a proposal", error=str(exc))
        return CaseRun(case=case, status=PROVIDER_ERROR, context=context, policy=policy, error=str(exc))
    _trace_exchange(case_id, provider)

    if investigates:
        # Deterministic fetch for the validator and the approval view, after the model's investigation.
        context = gather_context(case)
        append_case_event(case_id, "context_gathered", "Validator records fetched", loaded=[k for k, v in context.items() if v is not None])

    append_case_event(case_id, "proposal_generated", "Proposal generated", proposal=proposal.model_dump(mode="json"))

    try:
        validate_proposal(proposal, case, policy, context["customer"])
    except ValueError as exc:
        append_case_event(case_id, "validation_failed", "Proposal rejected by validator", error=str(exc))
        return CaseRun(case=case, status=VALIDATION_FAILED, context=context, policy=policy, proposal=proposal, error=str(exc))

    append_case_event(case_id, "validation_passed", "Proposal passed validation; awaiting human approval")
    return CaseRun(case=case, status=AWAITING_APPROVAL, context=context, policy=policy, proposal=proposal)


def recommended_action_for(proposal: ResolutionProposal | None) -> str | None:
    """Neutral next step for an escalation, built only from the proposal's own escalation reasons.

    Used for the API response and for the escalate write payload, so the two cannot drift apart.
    Non-escalations have no recommended action.
    """
    if proposal is None or proposal.decision != Decision.ESCALATE or not proposal.escalation_reasons:
        return None
    return "Manual review required: " + "; ".join(proposal.escalation_reasons)


def apply_approval(run: CaseRun, approval: ApprovalDecision | None, action: str | None = None) -> CaseRun:
    """Human checkpoint. Rejection records the decision and stops; approval runs the gated write tools."""
    if run.status != AWAITING_APPROVAL or run.proposal is None:
        raise ValueError(f"Case {run.case.case_id} is not awaiting approval (status={run.status}).")
    if approval is None:
        raise ValueError("An approval decision is required.")

    case_id = run.case.case_id
    proposal = run.proposal
    if approval.approved and approval.decision is not None and approval.decision != proposal.decision:
        raise ValueError(f"Approval is for {approval.decision.value} but the proposal is {proposal.decision.value}.")

    append_case_event(
        case_id,
        "human_decision",
        "Approved" if approval.approved else "Rejected",
        approved_by=approval.approved_by,
        approved=approval.approved,
        notes=approval.notes,
        **({"action": action} if action is not None else {}),
    )

    if not approval.approved:
        run.status = REJECTED
        return run

    order = run.context["order"]
    if proposal.decision == Decision.REPLACE:
        run.actions.append(create_replacement(order.order_id, order.sku, approval))
    elif proposal.decision == Decision.REFUND:
        run.actions.append(issue_refund(order.order_id, proposal.amount, run.case.case_type, approval))
    elif proposal.decision in (Decision.STORE_CREDIT, Decision.GOODWILL_CREDIT):
        run.actions.append(issue_store_credit(run.case.customer_id, proposal.amount, proposal.decision.value, approval))
    else:
        recommended = recommended_action_for(proposal) or "Manual review required"
        run.actions.append(escalate(case_id, proposal.escalation_reasons, recommended, approval))

    if proposal.decision != Decision.ESCALATE:
        run.actions.append(send_customer_message(case_id, proposal.customer_message_draft, approval))
    run.actions.append(tag_root_cause(case_id, proposal.root_cause.category, proposal.root_cause.detail, approval))

    # One summary event per approval: action names and amounts only. No customer text, reviewer data, or tokens.
    append_case_event(
        case_id,
        "actions_executed",
        "Gated write actions executed",
        decision=proposal.decision.value,
        actions=[_action_summary(entry) for entry in run.actions],
    )
    run.status = EXECUTED
    return run


def _action_summary(entry: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"action": entry["action"]}
    if "amount" in entry:
        summary["amount"] = entry["amount"]
    return summary
