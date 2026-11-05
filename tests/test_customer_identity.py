"""Demo sign-in for the customer page: SYNTHETIC identification for the showcase, not authentication.

What these tests protect: only the designated demo profiles can sign in, every failure looks the same, no route lists
customers, the session token travels in a header (never a URL), the client never supplies a customer id, and a token
only ever shows its own customer's orders.
"""
import pytest
from fastapi.testclient import TestClient

from api import app
from cosmic_resolve import customer
from cosmic_resolve.tools import _load_json_list

client = TestClient(app)

DEMO_NAMES = {"C-001": "Maya Rowe", "C-002": "Jon Park", "C-003": "Anita Lee", "C-044": "Penelope Coleman"}
ORDER_KEYS = {"order_reference", "product_name", "order_date", "price", "delivery_summary"}


@pytest.fixture(autouse=True)
def fresh_sessions():
    customer.reset_sessions_for_tests()
    yield
    customer.reset_sessions_for_tests()


def sign_in(name="Jon Park", code=customer.DEMO_ACCESS_CODE):
    return client.post("/api/support/identify", json={"name": name, "code": code})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_the_designated_demo_profiles_can_sign_in_and_the_reply_holds_only_a_token_and_a_first_name():
    assert set(DEMO_NAMES) == set(customer.DEMO_CUSTOMER_IDS)
    for customer_id, name in DEMO_NAMES.items():
        response = sign_in(name)
        assert response.status_code == 200, name
        body = response.json()
        assert set(body) == {"token", "first_name"}
        assert body["first_name"] == name.split()[0] and len(body["token"]) >= 20
        assert customer_id not in response.text  # no customer id, tier or claims history ever reaches the browser


@pytest.mark.parametrize("name", ["jon park", "  JON   PARK  ", "Jon Park"])
def test_name_matching_ignores_case_and_extra_spaces_and_so_does_the_code(name):
    assert sign_in(name, "cosmo-demo").status_code == 200


def test_every_failure_has_the_same_status_and_message_so_nothing_is_revealed():
    non_demo = next(c["name"] for c in _load_json_list("customers.json") if c["customer_id"] not in customer.DEMO_CUSTOMER_IDS)
    failures = [
        sign_in("Jon Park", "wrong-code"),  # a demo profile, wrong code
        sign_in("Nobody Atall"),  # unknown name
        sign_in(non_demo),  # a real customer, but not a designated demo profile
        sign_in(non_demo, "wrong-code"),
    ]
    assert {r.status_code for r in failures} == {401}
    assert {r.json()["detail"] for r in failures} == {customer.IDENTIFY_FAILURE}


def test_a_first_name_alone_never_signs_in_and_the_request_takes_no_extra_fields():
    assert sign_in("Jon").status_code == 401
    assert client.post("/api/support/identify", json={"name": "Jon Park", "code": customer.DEMO_ACCESS_CODE, "customer_id": "C-001"}).status_code == 422
    assert client.post("/api/support/identify", json={"name": "", "code": ""}).status_code == 422


def test_no_route_lists_customers_and_sign_in_is_post_only():
    for path in ("/api/support/customers", "/api/support/profiles", "/api/support/demo/customers", "/api/customers"):
        assert client.get(path).status_code == 404, path
    assert client.get("/api/support/identify").status_code == 405


def test_orders_need_a_valid_bearer_token_and_a_token_in_the_url_is_ignored():
    assert client.get("/api/support/my/orders").status_code == 401
    token = sign_in().json()["token"]
    assert client.get("/api/support/my/orders", headers={"Authorization": token}).status_code == 401  # no "Bearer"
    assert client.get("/api/support/my/orders", headers={"Authorization": "Basic " + token}).status_code == 401
    assert client.get("/api/support/my/orders", headers=bearer("not-a-real-token")).status_code == 401
    assert client.get(f"/api/support/my/orders?token={token}").status_code == 401  # a URL token is never accepted
    assert client.get("/api/support/my/orders", headers=bearer(token)).status_code == 200
    assert client.get("/api/support/my/orders", headers=bearer(token)).json() == client.get("/api/support/my/orders", headers={"authorization": f"bearer {token}"}).json()


def test_a_token_shows_only_its_own_customers_orders_in_the_customer_safe_shape():
    owners = {o["order_id"]: o["customer_id"] for o in _load_json_list("orders.json")}
    for customer_id, name in DEMO_NAMES.items():
        token = sign_in(name).json()["token"]
        response = client.get("/api/support/my/orders", headers=bearer(token))
        orders = response.json()
        assert orders and len(orders) <= 5
        assert all(set(order) == ORDER_KEYS for order in orders)
        assert {owners[order["order_reference"]] for order in orders} == {customer_id}
        assert not any(key in response.text for key in ("customer_id", "loyalty", "prior_claims", "lifetime"))


def test_two_sign_ins_get_different_tokens_and_each_keeps_its_own_customer():
    first, second = sign_in("Jon Park").json()["token"], sign_in("Maya Rowe").json()["token"]
    assert first != second
    jon = {o["order_reference"] for o in client.get("/api/support/my/orders", headers=bearer(first)).json()}
    maya = {o["order_reference"] for o in client.get("/api/support/my/orders", headers=bearer(second)).json()}
    assert jon and maya and not jon & maya


def test_the_original_anonymous_demo_orders_route_is_unchanged():
    orders = client.get("/api/support/demo/orders").json()
    assert [o["order_reference"] for o in orders] == ["O-1001", "O-1002", "O-1003"]
