"""Deployment checks: vercel.json configuration, the self-contained backend/data copy, and best-effort /tmp tracing.

All checks run offline and verify configuration syntax and packaged data only. They do not prove Vercel
runtime routing. The application-level /api compatibility is provided by StripApiPrefix in backend/api.py
and is tested in tests/test_api.py. A Vercel preview deployment is the definitive routing proof.
"""
import filecmp
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from cosmic_resolve import config, tracing, workflow
from cosmic_resolve.config import SETTINGS
from cosmic_resolve.model_provider import RuleBasedModelProvider
from cosmic_resolve.tools import get_case, get_customer, get_order, get_policy, get_product_listing, get_shipment

ROOT = Path(__file__).resolve().parents[1]
ROOT_DATA = ROOT / "data"
BACKEND_DATA = ROOT / "backend" / "data"
FIXTURES = ["cases", "customers", "orders", "shipments", "products", "inventory", "policies"]


def _load(directory: Path, name: str):
    return json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))


# --- vercel.json -----------------------------------------------------------------------------------------------

def _vercel() -> dict:
    return json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))


def test_vercel_json_defines_backend_and_frontend_services():
    services = _vercel()["services"]
    assert set(services) == {"backend", "frontend", "customer"}
    assert services["backend"]["root"] == "backend"
    assert services["frontend"]["root"] == "frontend"
    assert services["customer"]["root"] == "customer-frontend"
    assert (ROOT / "backend").is_dir() and (ROOT / "frontend").is_dir()


def test_backend_entrypoint_is_api_app_and_module_exists():
    backend = _vercel()["services"]["backend"]
    assert backend["entrypoint"] == "api:app"
    assert backend["framework"] == "fastapi"
    assert (ROOT / "backend" / "api.py").is_file()


def test_rewrites_route_api_then_support_then_employee_catch_all():
    rewrites = _vercel()["rewrites"]
    assert rewrites == [
        {"source": "/api/(.*)", "destination": {"service": "backend"}},
        {"source": "/support(/.*)?", "destination": {"service": "customer"}},
        {"source": "/(.*)", "destination": {"service": "frontend"}},
    ]


def test_no_bindings_env_or_credentials_in_vercel_json():
    text = (ROOT / "vercel.json").read_text(encoding="utf-8")
    for forbidden in ("bindings", '"env"', "AWS_", "ANTHROPIC", "BEDROCK"):
        assert forbidden not in text, forbidden


def test_vercel_transform_config_text_is_present_but_not_relied_on():
    """Configuration presence only. A production probe showed the transform does not change the path FastAPI
    routes on, so compatibility comes from StripApiPrefix (tested in tests/test_api.py). This test does not
    prove Vercel runtime behavior; a preview deployment does."""
    route = _vercel()["services"]["backend"]["routes"][0]
    assert route["src"] == "/api/(.*)"
    assert route["transforms"] == [{"type": "request.path", "op": "set", "args": "/$1"}]
    # Apply the documented semantics: the captured group replaces $1 in args.
    match = re.fullmatch(route["src"], "/api/cases")
    assert match is not None
    assert route["transforms"][0]["args"].replace("$1", match.group(1)) == "/cases"


def test_fastapi_app_imports_with_unprefixed_routes():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI

    import api

    assert isinstance(api.app, FastAPI)
    paths = {route.path for route in api.app.routes}
    assert "/cases" in paths and "/cases/{case_id}/trace" in paths
    assert not any(path.startswith("/api") for path in paths)


# --- backend/data ----------------------------------------------------------------------------------------------

def test_backend_data_contains_exactly_the_required_fixtures():
    assert sorted(p.name for p in BACKEND_DATA.glob("*.json")) == sorted(f"{name}.json" for name in FIXTURES)


@pytest.mark.parametrize("name", FIXTURES)
def test_backend_data_is_byte_identical_to_root_data(name):
    assert filecmp.cmp(ROOT_DATA / f"{name}.json", BACKEND_DATA / f"{name}.json", shallow=False)


def test_app_loads_fixtures_from_backend_data():
    assert config.DATA_DIR.resolve() == BACKEND_DATA.resolve()
    assert get_case("C-1002").order_id == "O-1002"


def test_backend_data_referential_integrity():
    cases = _load(BACKEND_DATA, "cases")
    customers = {c["customer_id"]: c for c in _load(BACKEND_DATA, "customers")}
    orders = {o["order_id"]: o for o in _load(BACKEND_DATA, "orders")}
    shipments = {s["tracking_id"]: s for s in _load(BACKEND_DATA, "shipments")}
    products = {p["sku"] for p in _load(BACKEND_DATA, "products")}
    inventory = {(i["sku"], i["region"]) for i in _load(BACKEND_DATA, "inventory")}
    clause_ids = {c["clause_id"] for c in _load(BACKEND_DATA, "policies")}

    assert len({c["case_id"] for c in cases}) == len(cases) == 30
    assert len(clause_ids) == len(_load(BACKEND_DATA, "policies"))
    for case in cases:
        assert case["customer_id"] in customers, case["case_id"]
        assert case["order_id"] in orders, case["case_id"]
        assert case["tracking_id"] in shipments, case["case_id"]
        assert orders[case["order_id"]]["customer_id"] == case["customer_id"], case["case_id"]
        assert shipments[case["tracking_id"]]["order_id"] == case["order_id"], case["case_id"]
    for order in orders.values():
        assert order["customer_id"] in customers, order["order_id"]
        assert order["sku"] in products, order["order_id"]
        assert (order["sku"], order["fulfillment_region"]) in inventory, order["order_id"]
    for shipment in shipments.values():
        assert shipment["order_id"] in orders, shipment["tracking_id"]


def test_policy_lookups_resolve_from_backend_data():
    for case_type in ("DAMAGED_ON_ARRIVAL", "LATE_DELIVERY", "RETURN_REQUEST"):
        assert len(get_policy("US", "GADGETS", case_type)) >= 3
    assert get_customer("C-001").customer_id == "C-001"
    assert get_shipment("T-1001").order_id == "O-1001"
    assert get_order("O-1001").sku
    assert get_product_listing(get_order("O-1001").sku).sku


# --- trace path ------------------------------------------------------------------------------------------------

def test_default_trace_path_on_vercel_is_tmp():
    assert config.default_trace_path({"VERCEL": "1"}) == Path("/tmp/cosmic-resolve-traces.jsonl")


def test_default_trace_path_local_is_repo_traces_directory():
    expected = config.TRACE_DIR / "mock_actions.jsonl"
    assert config.default_trace_path({}) == expected
    assert config.default_trace_path({"VERCEL": "0"}) == expected


def _trace_path_in_fresh_interpreter(extra_env: dict) -> str:
    env = {k: v for k, v in os.environ.items() if k != "VERCEL"}
    env.update(extra_env)
    env["PYTHONPATH"] = str(ROOT / "backend")
    result = subprocess.run(
        [sys.executable, "-c", "from cosmic_resolve.config import SETTINGS; print(SETTINGS.trace_path)"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return result.stdout.strip()


def test_fresh_interpreter_uses_tmp_trace_path_when_vercel_is_set():
    assert _trace_path_in_fresh_interpreter({"VERCEL": "1"}) == str(Path("/tmp/cosmic-resolve-traces.jsonl"))


def test_fresh_interpreter_keeps_repo_trace_path_locally():
    local = _trace_path_in_fresh_interpreter({})
    assert Path(local) == ROOT / "traces" / "mock_actions.jsonl"


def _blocked_trace_path(tmp_path: Path) -> Path:
    """A path whose parent directory cannot be created, so writing it raises an OSError."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    return blocker / "trace.jsonl"


def test_missing_trace_file_reads_as_empty(tmp_path):
    assert tracing.read_trace_events(trace_path=tmp_path / "absent.jsonl") == []


def test_trace_write_failure_is_dropped_on_vercel(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ON_VERCEL", True)
    path = _blocked_trace_path(tmp_path)
    event = tracing.append_trace_event("case_loaded", "Case loaded", {"case_id": "C-1002"}, trace_path=path)
    assert event.event_type == "case_loaded"
    assert tracing.read_trace_events(trace_path=path) == []


def test_trace_write_failure_still_raises_locally(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ON_VERCEL", False)
    with pytest.raises(OSError):
        tracing.append_trace_event("case_loaded", "Case loaded", {"case_id": "C-1002"}, trace_path=_blocked_trace_path(tmp_path))


def test_recommendation_survives_trace_write_failure_on_vercel(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ON_VERCEL", True)
    monkeypatch.setattr(SETTINGS, "trace_path", _blocked_trace_path(tmp_path))
    run = workflow.propose_resolution("C-1002", RuleBasedModelProvider())
    assert run.status == workflow.AWAITING_APPROVAL
    assert run.proposal is not None


def test_trace_endpoints_return_empty_not_500_when_storage_is_absent(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import api

    monkeypatch.setattr(SETTINGS, "trace_path", tmp_path / "absent.jsonl")
    client = TestClient(api.app)
    assert client.get("/cases/C-1001/trace").json() == []
    assert client.get("/traces").json() == []
    assert client.get("/cases/C-1001/trace").status_code == 200
