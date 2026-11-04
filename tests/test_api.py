"""API contract tests against the real FastAPI app.

Every trace write goes to a temporary file (autouse fixture), so these tests never touch traces/.
Both unprefixed routes (local development) and /api-prefixed routes (Vercel) are exercised.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

from api import StripApiPrefix, app
from cosmic_resolve.config import SETTINGS

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_trace(tmp_path, monkeypatch):
    path = tmp_path / "trace.jsonl"
    monkeypatch.setattr(SETTINGS, "trace_path", path)
    return path


# --- /api-prefixed routes (what Vercel forwards) ---------------------------------------------------------------

def test_api_health_returns_ok():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_cases_returns_all_thirty():
    response = client.get("/api/cases")
    assert response.status_code == 200
    cases = response.json()
    assert len(cases) == 30
    assert all("case_id" in case for case in cases)


def test_api_case_detail_returns_case():
    response = client.get("/api/cases/C-1001")
    assert response.status_code == 200
    assert response.json()["case_id"] == "C-1001"


def test_api_unknown_case_is_404():
    response = client.get("/api/cases/NOPE")
    assert response.status_code == 404
    assert "NOPE" in response.json()["detail"]


def test_api_case_trace_returns_list():
    response = client.get("/api/cases/C-1001/trace")
    assert response.status_code == 200
    assert response.json() == []  # nothing has run yet in the isolated trace file


def test_api_propose_reaches_the_offline_endpoint():
    response = client.post("/api/cases/C-1001/propose")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "case_id",
        "status",
        "error",
        "pipeline",
        "provider",
        "execution_mode",
        "proposal",
        "proposal_fingerprint",
        "recommended_action",
        "checkpoint_writes_enabled",
    }
    assert body["case_id"] == "C-1001"
    assert body["status"] == "AWAITING_APPROVAL"
    assert body["pipeline"] == "offline"
    assert body["provider"] == "offline"
    assert body["execution_mode"] == "rule_based"
    assert body["proposal"]["policy_clause_ids"]


def test_api_docs_page_is_served():
    response = client.get("/api/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_api_openapi_schema_lists_the_case_paths():
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert {"/cases", "/cases/{case_id}", "/cases/{case_id}/propose", "/cases/{case_id}/trace", "/health"} <= set(paths)
    assert not any(path.startswith("/api") for path in paths)


def test_api_trace_query_string_survives_the_middleware():
    client.post("/api/cases/C-1001/propose")
    client.post("/api/cases/C-1002/propose")
    limited = client.get("/api/traces?limit=2")
    assert limited.status_code == 200
    assert len(limited.json()) == 2
    filtered = client.get("/api/traces?case_id=C-1001").json()
    assert filtered and all(event["details"]["case_id"] == "C-1001" for event in filtered)


def test_bare_api_maps_to_root_without_crashing():
    response = client.get("/api")
    assert response.status_code == 404  # the app has no "/" route; the point is no 500


def test_only_one_api_prefix_is_removed():
    assert client.get("/api/api/cases").status_code == 404


# --- unprefixed routes (local development) -------------------------------------------------------------

def test_unprefixed_health_still_works():
    assert client.get("/health").json() == {"status": "ok"}


def test_unprefixed_cases_still_returns_thirty():
    cases = client.get("/cases").json()
    assert len(cases) == 30


def test_unprefixed_unknown_case_is_404():
    assert client.get("/cases/NOPE").status_code == 404
    assert client.post("/cases/NOPE/propose").status_code == 404


def test_unprefixed_docs_and_openapi_still_work():
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


# --- similar-but-invalid prefixes must not be rewritten ---------------------------------------------------

@pytest.mark.parametrize("path", ["/apiary", "/apiculture", "/api-v2"])
def test_similar_prefixes_are_not_stripped(path):
    assert client.get(path).status_code == 404


def _record_scope(path: str, raw_path: bytes | None = None, query: bytes = b"", extra: dict | None = None):
    """Run the middleware directly and return the scope the inner app received."""
    seen: dict = {}

    async def inner(scope, receive, send):
        seen.update(scope)

    scope = {"type": "http", "path": path, "query_string": query, "method": "GET", "root_path": "", "headers": []}
    if raw_path is not None:
        scope["raw_path"] = raw_path
    scope.update(extra or {})
    original = dict(scope)
    asyncio.run(StripApiPrefix(inner)(scope, None, None))
    assert scope == original, "middleware mutated the caller's scope"
    return seen


def test_middleware_rewrites_path_and_raw_path_consistently():
    seen = _record_scope("/api/cases/C-1001", raw_path=b"/api/cases/C-1001")
    assert seen["path"] == "/cases/C-1001"
    assert seen["raw_path"] == b"/cases/C-1001"


def test_middleware_maps_bare_api_to_root():
    assert _record_scope("/api")["path"] == "/"


def test_middleware_preserves_query_string_and_unrelated_fields():
    seen = _record_scope("/api/traces", query=b"limit=2&case_id=C-1001", extra={"root_path": "/x"})
    assert seen["query_string"] == b"limit=2&case_id=C-1001"
    assert seen["method"] == "GET"
    assert seen["root_path"] == "/x"
    assert seen["headers"] == []


@pytest.mark.parametrize("path", ["/apiary", "/apiculture", "/api-v2", "/cases"])
def test_middleware_leaves_non_prefix_paths_unchanged(path):
    assert _record_scope(path)["path"] == path


def test_middleware_removes_only_the_first_prefix():
    assert _record_scope("/api/api/cases")["path"] == "/api/cases"


def test_middleware_passes_lifespan_through_untouched():
    received: dict = {}

    async def inner(scope, receive, send):
        received["scope"] = scope

    scope = {"type": "lifespan"}
    asyncio.run(StripApiPrefix(inner)(scope, None, None))
    assert received["scope"] is scope


# --- trace isolation -------------------------------------------------------------------------------------------

def test_api_tests_write_traces_only_to_the_temporary_path(isolated_trace):
    client.post("/api/cases/C-1003/propose")
    assert SETTINGS.trace_path == isolated_trace
    assert isolated_trace.exists()
