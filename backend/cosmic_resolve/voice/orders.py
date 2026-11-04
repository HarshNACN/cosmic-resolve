"""Read-only order lookup for the voice agent, plus deterministic matching of what a customer says to an order."""
from __future__ import annotations

import re
from typing import Any

from ..tools import DomainLookupError, _load_json_list, get_customer
from .agent_config import MAX_ORDER_CARDS

_ORDINALS = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3, "fifth": 4, "5th": 4}
# Bare "one" or "two" is ordinary speech ("I have one problem"), so numbers only count after "number" or "option".
_NUMBERED = re.compile(r"\b(?:number|option|order|item|#)\s*(one|two|three|four|five|[1-5])\b", re.I)
_NUMBER_VALUES = {"one": 0, "two": 1, "three": 2, "four": 3, "five": 4, "1": 0, "2": 1, "3": 2, "4": 3, "5": 4}
_STOP = {"the", "and", "pro", "mini", "lite", "elite", "plus", "max", "air", "kit", "pack", "for", "with", "inch"}
_TOKEN = re.compile(r"[a-z0-9]+")


def customer_first_name(customer_id: str) -> str:
    """First name for the greeting. Raises DomainLookupError for an unknown customer."""
    return get_customer(customer_id).name.split()[0]


def recent_orders(customer_id: str, limit: int = MAX_ORDER_CARDS) -> list[dict[str, Any]]:
    """The customer's most recent orders with product title and delivery status, newest first."""
    products = {p["sku"]: p for p in _load_json_list("products.json")}
    shipments = {s["order_id"]: s for s in _load_json_list("shipments.json")}
    mine = [o for o in _load_json_list("orders.json") if o["customer_id"] == customer_id]
    mine.sort(key=lambda o: o["order_date"], reverse=True)
    cards = []
    for order in mine[:limit]:
        shipment = shipments.get(order["order_id"])
        if shipment is None:
            continue  # a case needs a shipment to be investigated
        cards.append(
            {
                "order_id": order["order_id"],
                "title": products.get(order["sku"], {}).get("title", order["sku"]),
                "price": order["price"],
                "order_date": order["order_date"][:10],
                "delivery_status": shipment["status"],
                "tracking_id": shipment["tracking_id"],
            }
        )
    return cards


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


def match_order(utterance: str, orders: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick an order from plain words, or return None when it is missing or ambiguous (the caller then asks)."""
    if not orders:
        return None
    words = _tokens(utterance)
    # An exact order ID said or tapped.
    for order in orders:
        if order["order_id"].lower() in utterance.lower():
            return order
    # Distinctive product words: exactly one order must score best.
    scores = []
    for order in orders:
        title_words = {w for w in _tokens(order["title"]) if len(w) >= 4 and w not in _STOP}
        scores.append(len(title_words & words))
    best = max(scores)
    if best > 0 and scores.count(best) == 1:
        return orders[scores.index(best)]
    # "the first one", "number two".
    numbered = _NUMBERED.search(utterance)
    if numbered:
        index = _NUMBER_VALUES[numbered.group(1).lower()]
        return orders[index] if index < len(orders) else None
    for word in words:
        index = _ORDINALS.get(word)
        if index is not None and index < len(orders) and len(words) <= 6:
            return orders[index]
    if len(orders) == 1 and words & {"it", "that", "this", "yes", "yeah"}:
        return orders[0]
    return None


def spoken_options(orders: list[dict[str, Any]]) -> str:
    if not orders:
        return ""
    return "Your orders are: " + ", ".join(o["title"] for o in orders) + "."


__all__ = [
    "DomainLookupError",
    "customer_first_name",
    "match_order",
    "recent_orders",
    "spoken_options",
]
