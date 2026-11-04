"""Model-callable READ tools: name -> implementation, Bedrock toolSpec, and a safe invoke.

Only the 7 read tools from docs/tools.md are registered. Write tools are deliberately absent:
they stay behind the human checkpoint in `workflow.apply_approval`.

`invoke_read_tool` never raises for model-caused problems (unknown name, bad arguments,
missing record). It returns a Bedrock-shaped result with status "error" so the model can recover.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from . import tools
from .tools import DomainLookupError


@dataclass(frozen=True)
class ReadTool:
    name: str
    func: Callable[..., Any]
    description: str
    parameters: dict[str, str]  # parameter name -> description; every parameter is a string
    # Fields removed from the result before the model sees it (e.g. customer PII the prompt omits on purpose).
    hide_fields: frozenset[str] = frozenset()

    def tool_spec(self) -> dict[str, Any]:
        return {
            "toolSpec": {
                "name": self.name,
                "description": self.description,
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            name: {"type": "string", "description": text}
                            for name, text in self.parameters.items()
                        },
                        "required": list(self.parameters),
                        "additionalProperties": False,
                    }
                },
            }
        }


READ_TOOLS: dict[str, ReadTool] = {
    tool.name: tool
    for tool in [
        ReadTool(
            "get_case",
            tools.get_case,
            "Fetch the support case (complaint, order, customer, tracking, market, category, case type).",
            {"case_id": "Support case identifier, e.g. C-1001."},
        ),
        ReadTool(
            "get_order",
            tools.get_order,
            "Fetch an order: SKU, price, order date, status, fulfillment region.",
            {"order_id": "Order identifier."},
        ),
        ReadTool(
            "get_customer",
            tools.get_customer,
            "Fetch the customer: loyalty tier, lifetime value, prior claims in the last 12 months, region.",
            {"customer_id": "Customer identifier."},
            hide_fields=frozenset({"name"}),
        ),
        ReadTool(
            "get_shipment",
            tools.get_shipment,
            "Fetch shipment status, carrier, delivery dates, scan events and delivery flags.",
            {"tracking_id": "Carrier tracking identifier."},
        ),
        ReadTool(
            "check_inventory",
            tools.check_inventory,
            "Check available stock for a SKU in a region.",
            {"sku": "Product SKU.", "region": "Region code, e.g. US."},
        ),
        ReadTool(
            "get_policy",
            tools.get_policy,
            "List policy clauses (with clause IDs) for a market, category and case type.",
            {"market": "Market code, e.g. US.", "category": "Product or case category.", "case_type": "Case type."},
        ),
        ReadTool(
            "get_product_listing",
            tools.get_product_listing,
            "Fetch the product listing and its claims, used when tagging root causes.",
            {"sku": "Product SKU."},
        ),
    ]
}


def read_tool_specs() -> list[dict[str, Any]]:
    """Bedrock `toolConfig.tools` entries for every read tool, in registry order."""
    return [tool.tool_spec() for tool in READ_TOOLS.values()]


def _error(message: str) -> dict[str, Any]:
    return {"status": "error", "content": [{"json": {"error": message}}]}


def invoke_read_tool(name: str, arguments: Any) -> dict[str, Any]:
    """Run one read tool requested by the model.

    Returns {"status": "success", "content": [{"json": <result>}]} on success, or the same shape
    with status "error" for an unknown tool, bad arguments, or a missing record.
    """
    tool = READ_TOOLS.get(name)
    if tool is None:
        return _error(f"Unknown tool '{name}'. Available tools: {', '.join(READ_TOOLS)}.")

    if not isinstance(arguments, dict):
        return _error(f"Arguments for '{name}' must be a JSON object.")
    missing = [key for key in tool.parameters if key not in arguments]
    extra = [key for key in arguments if key not in tool.parameters]
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"missing {', '.join(missing)}")
        if extra:
            parts.append(f"unexpected {', '.join(extra)}")
        return _error(f"Bad arguments for '{name}': {'; '.join(parts)}.")
    bad_types = [key for key in tool.parameters if not isinstance(arguments[key], str)]
    if bad_types:
        return _error(f"Arguments must be strings for '{name}': {', '.join(bad_types)}.")

    try:
        result = tool.func(**{key: arguments[key] for key in tool.parameters})
    except DomainLookupError as exc:
        return _error(str(exc))

    return {"status": "success", "content": [{"json": _to_json(result, tool.hide_fields)}]}


def _to_json(result: Any, hide_fields: frozenset[str]) -> Any:
    if isinstance(result, list):
        return [_to_json(item, hide_fields) for item in result]
    if hasattr(result, "model_dump"):
        data = result.model_dump(mode="json")
        return {key: value for key, value in data.items() if key not in hide_fields}
    return result
