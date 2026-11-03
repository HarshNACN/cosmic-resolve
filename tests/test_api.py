from fastapi.testclient import TestClient

from api import app

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_cases_and_propose():
    cases = client.get("/cases").json()
    assert len(cases) == 30
    body = client.post("/cases/C-1001/propose").json()
    assert body["status"] == "AWAITING_APPROVAL"
    assert body["proposal"]["policy_clause_ids"]


def test_unknown_case_404():
    assert client.get("/cases/NOPE").status_code == 404
    assert client.post("/cases/NOPE/propose").status_code == 404


def test_trace_endpoints(tmp_path, monkeypatch):
    from cosmic_resolve.config import SETTINGS

    monkeypatch.setattr(SETTINGS, "trace_path", tmp_path / "trace.jsonl")
    assert client.get("/traces").json() == []
    client.post("/cases/C-1001/propose")
    client.post("/cases/C-1002/propose")
    one = client.get("/cases/C-1001/trace").json()
    assert one and all(e["details"]["case_id"] == "C-1001" for e in one)
    assert {"case_loaded", "proposal_generated", "validation_passed"} <= {e["event_type"] for e in one}
    assert len(client.get("/traces").json()) > len(one)
    assert len(client.get("/traces?limit=2").json()) == 2
    assert client.get("/cases/NOPE/trace").status_code == 404
