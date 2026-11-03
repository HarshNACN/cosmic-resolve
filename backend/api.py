"""Minimal FastAPI app (T05 skeleton). Read-only: lists cases and produces proposals.

Run from backend/:  uvicorn api:app --reload --port 8000
The approval endpoint is added in T25. Uses the offline provider; no AWS calls.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from cosmic_resolve.model_provider import RuleBasedModelProvider
from cosmic_resolve.tracing import read_trace_events
from cosmic_resolve.tools import DomainLookupError, _load_json_list, get_case
from cosmic_resolve.workflow import propose_resolution

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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/cases")
def list_cases() -> list[dict]:
    return _load_json_list("cases.json")


@app.get("/cases/{case_id}")
def read_case(case_id: str) -> dict:
    try:
        return get_case(case_id).model_dump(mode="json")
    except DomainLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/cases/{case_id}/propose")
def propose(case_id: str) -> dict:
    """Read-only: returns a validated proposal awaiting a human decision. Never writes."""
    try:
        run = propose_resolution(case_id, RuleBasedModelProvider())
    except DomainLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "case_id": case_id,
        "status": run.status,
        "error": run.error,
        "proposal": run.proposal.model_dump(mode="json") if run.proposal else None,
    }


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
