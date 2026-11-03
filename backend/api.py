"""Minimal FastAPI app (T05 skeleton). Read-only: lists cases and produces proposals.

Run from backend/:  uvicorn api:app --reload --port 8000
The approval endpoint is added in T25. Uses the offline provider; no AWS calls.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from cosmic_resolve.model_provider import RuleBasedModelProvider
from cosmic_resolve.tracing import read_trace_events
from cosmic_resolve.tools import DomainLookupError, _load_json_list, get_case
from cosmic_resolve.workflow import propose_resolution

app = FastAPI(title="Cosmic Resolve")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)


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
