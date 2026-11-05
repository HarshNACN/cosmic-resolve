"""Minimal FastAPI app (T05 skeleton). Read-only: lists cases and produces proposals.

Run from backend/:  uvicorn api:app --reload --port 8000
The approval endpoint is added in T25. Offline provider by default (no AWS calls); COSMIC_RESOLVE_LIVE=true selects Bedrock for local demos.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from cosmic_resolve.model_provider import ProviderError
from cosmic_resolve.provider_factory import (
    build_provider,
    configured_metadata,
    get_provider_diagnostics,
    log_provider_selected,
    pipeline_label,
    provider_metadata,
)
from cosmic_resolve.tracing import append_case_event, read_trace_events
from cosmic_resolve.tools import DomainLookupError, _load_json_list, get_case
from cosmic_resolve import config, customer
from cosmic_resolve.customer import CustomerOrderSummary, CustomerSupportReceipt, SupportIntakeRequest
from cosmic_resolve.checkpoint import CheckpointError, decide, proposal_fingerprint, remember_run
from cosmic_resolve.models import DecisionRequest, DecisionResult
from cosmic_resolve.voice import store as voice_store
from cosmic_resolve.voice.routes import register as register_voice_routes
from cosmic_resolve.workflow import AWAITING_APPROVAL, PROVIDER_ERROR, propose_resolution, recommended_action_for

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


def _propose_response(case_id: str, run: Any, meta: dict[str, str]) -> dict:
    awaiting = run.status == AWAITING_APPROVAL and run.proposal is not None
    return {
        "case_id": case_id,
        "status": run.status,
        "error": run.error,
        # Which provider produced this, and how it reasoned. Labels only; no credentials, accounts or ARNs.
        "provider": meta["provider"],
        "execution_mode": meta["execution_mode"],
        # Older label kept for compatibility: "offline", "bedrock" (single-shot) or "agent" (model-chosen tools).
        "pipeline": pipeline_label(meta["execution_mode"]),
        "proposal": run.proposal.model_dump(mode="json") if run.proposal else None,
        # Integrity identifier for the decision endpoint; not a credential.
        "proposal_fingerprint": proposal_fingerprint(run.proposal) if run.proposal else None,
        # Deterministic, backend-derived next step for an escalation awaiting a human. Null otherwise.
        "recommended_action": recommended_action_for(run.proposal) if awaiting else None,
        # Capability discovery: the frontend shows checkpoint controls only when this is true.
        "checkpoint_writes_enabled": config.checkpoint_writes_enabled(),
    }


def _setup_failure(case_id: str, exc: ProviderError) -> dict:
    """Bedrock was selected but could not be set up. Returns PROVIDER_ERROR; it never substitutes offline rules."""
    try:
        get_case(case_id)
    except DomainLookupError as lookup:
        raise HTTPException(status_code=404, detail=str(lookup)) from lookup
    meta = configured_metadata()
    append_case_event(case_id, "provider_error", "Provider could not be set up", error=str(exc), **meta)
    return _propose_response(case_id, _ErrorRun(status=PROVIDER_ERROR, error=str(exc)), meta)


class _ErrorRun:
    """The fields _propose_response reads, for a request that never reached the workflow."""

    def __init__(self, status: str, error: str) -> None:
        self.status = status
        self.error = error
        self.proposal = None


@app.post("/cases/{case_id}/propose")
def propose(case_id: str) -> dict:
    """Read-only: returns a validated proposal awaiting a human decision. Never writes.

    The provider comes from build_provider (MODEL_PROVIDER). When Bedrock is selected, a failure at any step is
    returned as PROVIDER_ERROR and never replaced by the offline rules.
    """
    try:
        provider = build_provider()
    except config.ProviderConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProviderError as exc:
        return _setup_failure(case_id, exc)
    meta = provider_metadata(provider)
    if meta["provider"] == "bedrock":
        log_provider_selected(meta, get_provider_diagnostics())  # booleans only; no credential is read here
    try:
        run = propose_resolution(case_id, provider, provider_info=meta)
    except DomainLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if meta["provider"] == "bedrock":
        remember_run(run)  # /decision acts only on the proposal this server generated and the human saw
    return _propose_response(case_id, run, meta)


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
    except config.ProviderConfigError as exc:  # contradictory MODEL_PROVIDER / COSMIC_RESOLVE_LIVE
        raise HTTPException(status_code=503, detail=str(exc)) from exc
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


@app.get("/scorecard")
def scorecard() -> dict:
    """Eval scorecard run history (evals/scorecard.json, written by evals/run_evals.py). Read-only, no model calls."""
    path = config.SETTINGS.evals_dir / "scorecard.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="No eval scorecard is available. Run evals/run_evals.py.") from exc
    runs = data.get("runs") if isinstance(data, dict) else None
    if not isinstance(runs, list):
        raise HTTPException(status_code=404, detail="The eval scorecard is not in the expected format.")
    return {"runs": runs}


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
