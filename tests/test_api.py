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
