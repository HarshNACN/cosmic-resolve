"""Integrity checks for the JSON fixtures in /data.

Covers schema, uniqueness, cross-file references, business-rule consistency, PRD size targets,
and an end-to-end smoke test that every case can be investigated with the read tools.
Eval-file checks live in test_eval_data.py.
"""

import json
from collections import Counter
from datetime import datetime

import pytest
from pydantic import ValidationError

from cosmic_resolve.config import DATA_DIR, GOODWILL_CAPS_USD
from cosmic_resolve.models import Customer, InventoryRecord, Order, PolicyClause, Product, Shipment, SupportCase
from cosmic_resolve.tools import (
    check_inventory,
    get_case,
    get_customer,
    get_order,
    get_policy,
    get_product_listing,
    get_shipment,
)


def _load(file_name: str) -> list[dict]:
    return json.loads((DATA_DIR / file_name).read_text(encoding="utf-8"))


CUSTOMERS = _load("customers.json")
ORDERS = _load("orders.json")
SHIPMENTS = _load("shipments.json")
INVENTORY = _load("inventory.json")
PRODUCTS = _load("products.json")
POLICIES = _load("policies.json")
CASES = _load("cases.json")

CUSTOMER_BY_ID = {c["customer_id"]: c for c in CUSTOMERS}
ORDER_BY_ID = {o["order_id"]: o for o in ORDERS}
SHIPMENT_BY_TRACKING = {s["tracking_id"]: s for s in SHIPMENTS}
PRODUCT_BY_SKU = {p["sku"]: p for p in PRODUCTS}

MODELS = {
    "customers.json": Customer,
    "orders.json": Order,
    "shipments.json": Shipment,
    "inventory.json": InventoryRecord,
    "products.json": Product,
    "policies.json": PolicyClause,
    "cases.json": SupportCase,
}
UNIQUE_KEYS = {
    "customers.json": ("customer_id",),
    "orders.json": ("order_id",),
    "shipments.json": ("tracking_id",),
    "inventory.json": ("sku", "region"),
    "products.json": ("sku",),
    "policies.json": ("clause_id",),
    "cases.json": ("case_id",),
}

CASE_TYPES = {"DAMAGED_ON_ARRIVAL", "LATE_DELIVERY", "RETURN_REQUEST"}
SHIPMENT_STATUSES = {"DELIVERED", "IN_TRANSIT", "LOST_IN_TRANSIT", "DELAYED", "RETURNED_TO_SENDER"}
CHANNELS = {"EMAIL", "CHAT", "PHONE"}


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------- schema ----------


@pytest.mark.parametrize("file_name", MODELS)
def test_every_record_matches_its_model(file_name: str) -> None:
    model = MODELS[file_name]
    records = _load(file_name)
    assert records, f"{file_name} is empty"
    errors = []
    for index, record in enumerate(records):
        try:
            model.model_validate(record)
        except ValidationError as exc:
            errors.append(f"{file_name}[{index}]: {exc.errors()[0]['msg']}")
    assert not errors, errors[:5]


@pytest.mark.parametrize("file_name", UNIQUE_KEYS)
def test_record_keys_are_unique(file_name: str) -> None:
    keys = [tuple(r[k] for k in UNIQUE_KEYS[file_name]) for r in _load(file_name)]
    duplicates = [k for k, n in Counter(keys).items() if n > 1]
    assert not duplicates, duplicates[:5]


# ---------- cross-file references ----------


def test_orders_reference_real_customers_and_products() -> None:
    bad = [o["order_id"] for o in ORDERS if o["customer_id"] not in CUSTOMER_BY_ID or o["sku"] not in PRODUCT_BY_SKU]
    assert not bad, bad[:5]


def test_every_order_has_exactly_one_shipment() -> None:
    shipment_counts = Counter(s["order_id"] for s in SHIPMENTS)
    assert set(shipment_counts) == set(ORDER_BY_ID), "orders and shipments do not line up"
    assert all(n == 1 for n in shipment_counts.values())


def test_tracking_id_number_matches_order_id_number() -> None:
    bad = [s["tracking_id"] for s in SHIPMENTS if s["tracking_id"][2:] != s["order_id"][2:]]
    assert not bad, bad[:5]


def test_inventory_covers_every_product_and_nothing_else() -> None:
    inventory_skus = {r["sku"] for r in INVENTORY if r["region"] == "US"}
    assert inventory_skus == set(PRODUCT_BY_SKU)


@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_case_references_agree_with_each_other(case: dict) -> None:
    order = ORDER_BY_ID[case["order_id"]]
    shipment = SHIPMENT_BY_TRACKING[case["tracking_id"]]
    assert shipment["order_id"] == case["order_id"]
    assert order["customer_id"] == case["customer_id"]
    assert case["customer_id"] in CUSTOMER_BY_ID


# ---------- business-rule consistency ----------


def test_order_price_matches_product_price() -> None:
    bad = [o["order_id"] for o in ORDERS if o["price"] != PRODUCT_BY_SKU[o["sku"]]["price"]]
    assert not bad, bad[:5]


def test_products_are_us_gadgets_in_the_prd_price_range() -> None:
    for product in PRODUCTS:
        assert (product["market"], product["category"]) == ("US", "GADGETS"), product["sku"]
        assert 19 <= product["price"] <= 1499, product["sku"]
        assert product["listing_claims"], f"{product['sku']} has no listing claims"


def test_customers_have_known_tiers() -> None:
    bad = [c["customer_id"] for c in CUSTOMERS if c["loyalty_tier"] not in GOODWILL_CAPS_USD]
    assert not bad, bad[:5]


def test_shipment_fields_are_internally_consistent() -> None:
    for s in SHIPMENTS:
        tid = s["tracking_id"]
        assert s["status"] in SHIPMENT_STATUSES, tid
        assert s["events"], f"{tid} has no events"
        assert s["delivered"] == (s["status"] == "DELIVERED"), tid
        if s["customer_photo_provided"]:
            assert s["delivered"], f"{tid} has a damage photo but was never delivered"


def test_timestamps_parse_and_cases_follow_their_orders() -> None:
    for order in ORDERS:
        _timestamp(order["order_date"])
    for case in CASES:
        created = _timestamp(case["created_at"])
        ordered = _timestamp(ORDER_BY_ID[case["order_id"]]["order_date"])
        assert created >= ordered, f"{case['case_id']} was created before its order"


@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_case_fields_and_shipment_status_fit_the_case_type(case: dict) -> None:
    assert case["case_type"] in CASE_TYPES
    assert case["channel"] in CHANNELS
    assert case["status"] == "OPEN"
    assert case["complaint_text"].strip()

    shipment = SHIPMENT_BY_TRACKING[case["tracking_id"]]
    if case["case_type"] in {"DAMAGED_ON_ARRIVAL", "RETURN_REQUEST"}:
        assert shipment["status"] == "DELIVERED", "damage and return claims need a delivered package"
    else:
        lost_or_late = shipment["status"] in {"LOST_IN_TRANSIT", "DELAYED"}
        signed_delivery_conflict = shipment["status"] == "DELIVERED" and shipment["signature_required"]
        assert lost_or_late or signed_delivery_conflict, shipment["status"]


# ---------- sizes and coverage (PRD sections 7 and 8) ----------


def test_fixture_sizes_match_prd_targets() -> None:
    assert 140 <= len(CUSTOMERS) <= 160
    assert 35 <= len(PRODUCTS) <= 45
    assert 350 <= len(ORDERS) <= 450
    assert len(SHIPMENTS) == len(ORDERS)
    assert len(POLICIES) >= 12
    assert 25 <= len(CASES) <= 35


def test_cases_cover_all_three_case_types() -> None:
    counts = Counter(c["case_type"] for c in CASES)
    assert set(counts) == CASE_TYPES
    assert min(counts.values()) >= 5


def test_data_includes_the_edge_scenarios_the_demo_needs() -> None:
    serial_claimers = [c for c in CUSTOMERS if c["prior_claims_12m"] >= 4]
    assert len(serial_claimers) >= 3, "PRD calls for a few serial claimers"
    assert {c["loyalty_tier"] for c in CUSTOMERS} == set(GOODWILL_CAPS_USD)
    assert any("ignore" in c["complaint_text"].lower() for c in CASES), "no prompt-injection case"
    assert any(r["available_quantity"] == 0 for r in INVENTORY), "no out-of-stock SKU for the no-replacement path"
    assert {s["status"] for s in SHIPMENTS} == SHIPMENT_STATUSES
    assert any(s["signature_required"] and s["delivered"] for s in SHIPMENTS)


# ---------- end-to-end smoke test over the read tools ----------


@pytest.mark.parametrize("case_id", [c["case_id"] for c in CASES])
def test_every_case_can_be_fully_investigated_with_the_read_tools(case_id: str) -> None:
    case = get_case(case_id)
    order = get_order(case.order_id)
    customer = get_customer(case.customer_id)
    shipment = get_shipment(case.tracking_id)
    inventory = check_inventory(order.sku, order.fulfillment_region)
    policy = get_policy(case.market, case.category, case.case_type)
    listing = get_product_listing(order.sku)

    assert order.customer_id == customer.customer_id
    assert shipment.order_id == order.order_id
    assert inventory.sku == order.sku
    assert listing.sku == order.sku
    assert (listing.market, listing.category) == (case.market, case.category)
    assert policy, "no policy clauses returned"
