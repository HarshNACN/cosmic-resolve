"""Static checks for the customer routing configuration.

These check configuration text and first-match ordering only. They do not prove Vercel's runtime routing or static
serving. Only a Vercel Preview deployment does that.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _vercel() -> dict:
    return json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))


def _first_match(path: str) -> str | None:
    """Vercel evaluates rewrites in order and uses the first match. Approximated here with full-path regex matches."""
    for rewrite in _vercel()["rewrites"]:
        if re.fullmatch(rewrite["source"], path):
            return rewrite["destination"]["service"]
    return None


def test_customer_service_is_a_vite_app_rooted_in_customer_frontend():
    customer = _vercel()["services"]["customer"]
    assert customer["root"] == "customer-frontend"
    assert customer["framework"] == "vite"
    assert (ROOT / "customer-frontend" / "package.json").is_file()


def test_customer_output_directory_is_declared_and_contains_the_support_prefix():
    customer = _vercel()["services"]["customer"]
    assert customer["outputDirectory"] == "dist"
    config = (ROOT / "customer-frontend" / "vite.config.js").read_text(encoding="utf-8")
    assert 'base: "/support/"' in config
    assert 'outDir: "dist/support"' in config


def test_existing_services_are_unchanged_in_location():
    services = _vercel()["services"]
    assert services["backend"]["root"] == "backend"
    assert services["backend"]["entrypoint"] == "api:app"
    assert services["frontend"]["root"] == "frontend"
    assert services["frontend"]["framework"] == "vite"


def test_api_is_matched_first_then_support_then_employee_catch_all_last():
    sources = [rewrite["source"] for rewrite in _vercel()["rewrites"]]
    assert sources == ["/api/(.*)", "/support(/.*)?", "/(.*)"]


def test_public_api_paths_reach_the_backend():
    for path in ["/api/health", "/api/cases", "/api/cases/C-1001", "/api/support/demo/orders", "/api/support/requests"]:
        assert _first_match(path) == "backend", path


def test_customer_paths_reach_the_customer_service():
    for path in ["/support", "/support/", "/support/assets/index-abc.js", "/support/assets/index-abc.css"]:
        assert _first_match(path) == "customer", path


def test_the_employee_catch_all_cannot_intercept_support_paths():
    for path in ["/support", "/support/", "/support/assets/x.js", "/support/anything/else"]:
        assert _first_match(path) != "frontend", path


def test_similar_prefixes_are_not_routed_to_the_customer_service():
    for path in ["/supportive", "/support-x", "/supporters"]:
        assert _first_match(path) == "frontend", path


def test_employee_root_still_reaches_the_employee_frontend():
    assert _first_match("/") == "frontend"
    assert _first_match("/cases/C-1001") == "frontend"


def test_no_bindings_or_environment_secrets_were_added():
    text = (ROOT / "vercel.json").read_text(encoding="utf-8")
    assert "bindings" not in text
    assert '"env"' not in text
    assert "AWS_" not in text and "ANTHROPIC" not in text and "BEDROCK" not in text


def test_customer_api_stays_on_the_backend_route():
    customer_src = (ROOT / "customer-frontend" / "src" / "api.js").read_text(encoding="utf-8")
    assert 'const BASE = "/api/support";' in customer_src
    assert "vercel.app" not in customer_src and "localhost" not in customer_src


def _redirect_for(path: str) -> str | None:
    for redirect in _vercel().get("redirects", []):
        if re.fullmatch(redirect["source"], path):
            return redirect["destination"]
    return None


def test_bare_support_redirects_to_the_trailing_slash_form():
    assert _redirect_for("/support") == "/support/"
    assert _vercel()["redirects"][0]["permanent"] is False


def test_the_trailing_slash_form_is_not_redirected_and_goes_to_customer():
    assert _redirect_for("/support/") is None
    assert _first_match("/support/") == "customer"


def test_lookalike_paths_are_not_redirected_and_are_not_customer():
    for path in ["/supportive", "/supporters", "/support-tools", "/support-x"]:
        assert _redirect_for(path) is None, path
        assert _first_match(path) != "customer", path


def test_customer_assets_under_support_select_the_customer_service():
    for path in ["/support/assets/index-Bjo3xkT1.js", "/support/assets/index-BrKSDcw6.css"]:
        assert _redirect_for(path) is None
        assert _first_match(path) == "customer", path


def test_api_support_selects_backend_not_customer():
    assert _first_match("/api/support/demo/orders") == "backend"
    assert _first_match("/api/support/requests") == "backend"
    assert _first_match("/api/support") == "backend"


def test_built_artifact_matches_the_declared_output_when_present():
    """Checks the real build output if it exists. dist/ is git-ignored, so this skips on a clean checkout."""
    import pytest

    dist = ROOT / "customer-frontend" / "dist"
    index = dist / "support" / "index.html"
    if not index.is_file():
        pytest.skip("customer-frontend has not been built; run npm run build to check the artifact")
    html = index.read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="(/support/assets/[^"]+)"', html)
    assert refs, "index.html must reference /support/assets/*"
    for ref in refs:
        assert (dist / ref.removeprefix("/")).is_file() or (dist / "support" / ref.removeprefix("/support/")).is_file(), ref
    assert "localhost" not in html and "vercel.app" not in html
    assert not (dist / "index.html").exists(), "root-level index.html would mean the build is not under support/"


def test_redirects_contain_only_the_support_redirect():
    redirects = _vercel().get("redirects", [])
    assert [r["source"] for r in redirects] == ["/support"]
    assert all(set(r) <= {"source", "destination", "permanent"} for r in redirects)
