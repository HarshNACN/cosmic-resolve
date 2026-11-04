"""Minimal FastAPI app (T05 skeleton). Read-only: lists cases and produces proposals.

Run from backend/:  uvicorn api:app --reload --port 8000
The approval endpoint is added in T25. Offline provider by default (no AWS calls); COSMIC_RESOLVE_LIVE=true selects Bedrock for local demos.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from cosmic_resolve.bedrock_agent import BedrockAgentProvider, select_provider
from cosmic_resolve.model_provider import ProviderError, RuleBasedModelProvider
from cosmic_resolve.tracing import read_trace_events
from cosmic_resolve.tools import DomainLookupError, _load_json_list, get_case
from cosmic_resolve import config, customer
from cosmic_resolve.customer import CustomerOrderSummary, CustomerSupportReceipt, SupportIntakeRequest
from cosmic_resolve.checkpoint import CheckpointError, decide, proposal_fingerprint, remember_run
from cosmic_resolve.models import DecisionRequest, DecisionResult
from cosmic_resolve.voice import store as voice_store
from cosmic_resolve.voice.routes import register as register_voice_routes
from cosmic_resolve.workflow import AWAITING_APPROVAL, propose_resolution, recommended_action_for

API_PREFIX = "/api"


def _without_api_prefix(path: str) -> str | None:
    """Return path with one leading "/api" removed, or None if it has no such segment."""
    if path == API_PREFIX:
        return "/"
    if path.startswith(API_PREFIX + "/"):
        return path[len(API_PREFIX):]
    return None


class StripApiPrefix:
    """Remove one leading /api segment from HTTP and WebSocket paths before FastAPI routes them.

    Vercel Services forwards the original public path (for example /api/cases) to the backend service, but
    the routes in this module are declared without the prefix. Local development is unaffected because the
    Vite proxy already removes /api. Only an exact "/api" segment is removed, so /apiary and /api-v2 are
    left alone, and a nested /api/api/... loses only its first prefix. Lifespan and other scope types pass
    through unchanged.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            stripped = _without_api_prefix(scope["path"])
            if stripped is not None:
                updates = {"path": stripped}
                raw_path = scope.get("raw_path")
                if raw_path is not None:
                    stripped_raw = _without_api_prefix(raw_path.decode("latin-1"))
                    if stripped_raw is not None:
                        updates["raw_path"] = stripped_raw.encode("latin-1")
                scope = {**scope, **updates}  # copy; never mutate the server's scope in place
        await self.app(scope, receive, send)


app = FastAPI(title="Cosmic Resolve")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(StripApiPrefix)
register_voice_routes(app)  # local voice demo: /voice/*; every dependency is optional and imported lazily


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/cases")
def list_cases() -> list[dict]:
    # Cases created by a voice call come first, newest on top, so a call's case appears right away.
    voice_cases = [case.model_dump(mode="json") for case in reversed(voice_store.list_cases())]
    return voice_cases + _load_json_list("cases.json")


@app.get("/cases/{case_id}")
def read_case(case_id: str) -> dict:
    try:
        return get_case(case_id).model_dump(mode="json")
    except DomainLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _pipeline_name(provider: object) -> str:
    if isinstance(provider, BedrockAgentProvider):
        return "agent"
    return "offline" if isinstance(provider, RuleBasedModelProvider) else "bedrock"


@app.post("/cases/{case_id}/propose")
def propose(case_id: str) -> dict:
    """Read-only: returns a validated proposal awaiting a human decision. Never writes."""
    live = config.live_provider_enabled()
    try:
        provider = select_provider(live)
    except ProviderError as exc:  # live requested but Bedrock is not configured
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        run = propose_resolution(case_id, provider)
    except DomainLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if live:
        remember_run(run)  # /decision acts only on the proposal this server generated and the human saw
    awaiting = run.status == AWAITING_APPROVAL and run.proposal is not None
    return {
        "case_id": case_id,
        "status": run.status,
        "error": run.error,
        # Which path produced the proposal: "offline", "bedrock" (fixed pipeline) or "agent" (model-chosen tools).
        "pipeline": _pipeline_name(provider),
        "proposal": run.proposal.model_dump(mode="json") if run.proposal else None,
        # Integrity identifier for the decision endpoint; not a credential.
        "proposal_fingerprint": proposal_fingerprint(run.proposal) if run.proposal else None,
        # Deterministic, backend-derived next step for an escalation awaiting a human. Null otherwise.
        "recommended_action": recommended_action_for(run.proposal) if awaiting else None,
        # Capability discovery: the frontend shows checkpoint controls only when this is true.
        "checkpoint_writes_enabled": config.checkpoint_writes_enabled(),
    }


@app.post("/cases/{case_id}/decision", response_model=DecisionResult)
def decide_case(case_id: str, body: DecisionRequest) -> DecisionResult:
    """Human checkpoint decision: APPROVE, EDIT_AND_APPROVE (message only) or REJECT.

    Disabled unless CHECKPOINT_WRITES_ENABLED is set (403, no writes). Stateless: the server rebuilds the
    proposal, checks the fingerprint, revalidates, and only then runs the gated write path.
    """
    try:
        return decide(case_id, body)
    except DomainLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CheckpointError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


# Customer-facing routes. Public URLs are /api/support/...; the /api prefix is removed by StripApiPrefix.
# DEMO CUSTOMER MODE only: an allowlist of three synthetic orders, no authentication (see customer.py).
@app.get("/support/demo/orders", response_model=list[CustomerOrderSummary])
def demo_orders_for_customers() -> list[CustomerOrderSummary]:
    return customer.demo_orders()


@app.post("/support/requests", response_model=CustomerSupportReceipt)
def submit_customer_request(body: SupportIntakeRequest) -> CustomerSupportReceipt:
    """Validate and acknowledge one support request. Nothing is persisted, executed or resolved here."""
    try:
        return customer.receive_intake(body)
    except customer.CustomerError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.get("/traces")
def traces(case_id: str | None = None, limit: int | None = Query(default=None, ge=1)) -> list[dict]:
    """Audit trail, oldest first. Filter by case_id; limit keeps the most recent N events."""
    return [e.model_dump(mode="json") for e in read_trace_events(case_id=case_id, limit=limit)]


@app.get("/cases/{case_id}/trace")
def case_trace(case_id: str) -> list[dict]:
    try:
        get_case(case_id)
    except DomainLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [e.model_dump(mode="json") for e in read_trace_events(case_id=case_id)]
