"""Read-only order lookup for the voice agent, plus deterministic matching of what a customer says to an order.

Product titles are English, so Spanish and Portuguese product words map onto the English title words below. Anything
this cannot match is left to the model, which may only choose among the customer's own order IDs.
"""
from __future__ import annotations

import re
from typing import Any

from ..tools import DomainLookupError, _load_json_list, get_customer
from . import agent_config as cfg
from .agent_config import MAX_ORDER_CARDS
from .languages import fold, words

_ORDINALS = {
    "first": 0, "1st": 0, "primero": 0, "primera": 0, "primeiro": 0, "primeira": 0,
    "second": 1, "2nd": 1, "segundo": 1, "segunda": 1,
    "third": 2, "3rd": 2, "tercero": 2, "tercera": 2, "terceiro": 2, "terceira": 2,
    "fourth": 3, "4th": 3, "cuarto": 3, "cuarta": 3, "quarto": 3, "quarta": 3,
    "fifth": 4, "5th": 4, "quinto": 4, "quinta": 4,
}
# Bare "one" or "two" is ordinary speech ("I have one problem"), so numbers only count after "number" or "option".
_NUMBERED = re.compile(
    r"\b(?:number|option|order|item|numero|opcion|opcao|pedido)\s*"
    r"(one|two|three|four|five|uno|dos|tres|cuatro|cinco|um|dois|quatro|[1-5])\b"
)
_NUMBER_VALUES = {
    "one": 0, "uno": 0, "um": 0, "1": 0,
    "two": 1, "dos": 1, "dois": 1, "2": 1,
    "three": 2, "tres": 2, "3": 2,
    "four": 3, "cuatro": 3, "quatro": 3, "4": 3,
    "five": 4, "cinco": 4, "5": 4,
}
_STOP = {"the", "and", "pro", "mini", "lite", "elite", "plus", "max", "air", "kit", "pack", "for", "with", "inch"}

# Spanish and Portuguese product words, and the English title word each one stands for. (Accents are stripped.)
_SYNONYMS = {
    "enchufe": ("plug",), "tomada": ("plug",),
    "audifonos": ("headphones", "earbuds"), "auriculares": ("headphones", "earbuds"), "cascos": ("headphones",),
    "fones": ("headphones", "earbuds"), "fone": ("headphones", "earbuds"),
    "reloj": ("watch",), "relogio": ("watch",),
    "cargador": ("charger",), "carregador": ("charger",),
    "bocina": ("speaker",), "altavoz": ("speaker",), "parlante": ("speaker",),
    "teclado": ("keyboard",), "raton": ("mouse",),
    "dron": ("drone",), "termostato": ("thermostat",),
    "aspiradora": ("vacuum",), "aspirador": ("vacuum",),
    "cerradura": ("lock",), "fechadura": ("lock",),
    "proyector": ("projector",), "projetor": ("projector",),
    "bombilla": ("bulb",), "foco": ("bulb",), "lampada": ("bulb",),
    "maleta": ("luggage",), "mala": ("luggage",),
    "tripode": ("tripod",), "tripe": ("tripod",),
    "camara": ("camera",), "tableta": ("tablet",),
}
_PHRASES = {
    "caixa de som": ("speaker",),
    "alto falante": ("speaker",),
    "fone de ouvido": ("headphones", "earbuds"),
}


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


def _utterance_tokens(utterance: str) -> set[str]:
    """The words said, plus the English title words that Spanish or Portuguese product words stand for."""
    tokens = set(words(utterance))
    for token in list(tokens):
        tokens.update(_SYNONYMS.get(token, ()))
    folded = fold(utterance)
    for phrase, english in _PHRASES.items():
        if phrase in folded:
            tokens.update(english)
    return tokens


def match_order(utterance: str, orders: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick an order from plain words, or return None when it is missing or ambiguous (the caller then asks)."""
    if not orders:
        return None
    tokens = _utterance_tokens(utterance)
    # An exact order ID said or tapped.
    for order in orders:
        if order["order_id"].lower() in utterance.lower():
            return order
    # Distinctive product words: exactly one order must score best.
    scores = []
    for order in orders:
        title_words = {w for w in words(order["title"]) if len(w) >= 4 and w not in _STOP}
        scores.append(len(title_words & tokens))
    best = max(scores)
    if best > 0 and scores.count(best) == 1:
        return orders[scores.index(best)]
    # "the first one", "number two", "el segundo", "o terceiro".
    numbered = _NUMBERED.search(fold(utterance))
    if numbered:
        index = _NUMBER_VALUES[numbered.group(1)]
        return orders[index] if index < len(orders) else None
    spoken = words(utterance)
    for word in spoken:
        index = _ORDINALS.get(word)
        if index is not None and index < len(orders) and len(spoken) <= 6:
            return orders[index]
    if len(orders) == 1 and tokens & {"it", "that", "this", "yes", "yeah", "si", "sim", "ese", "esse", "eso", "isso"}:
        return orders[0]
    return None


def spoken_options(orders: list[dict[str, Any]], language: str = cfg.DEFAULT_LANGUAGE) -> str:
    if not orders:
        return ""
    return cfg.text("OPTIONS", language).format(titles=", ".join(o["title"] for o in orders))


__all__ = [
    "DomainLookupError",
    "customer_first_name",
    "match_order",
    "recent_orders",
    "spoken_options",
]
