# Tool contracts

Source of truth: `backend/cosmic_resolve/tools.py` (functions) and `backend/cosmic_resolve/models.py` (return shapes). This document describes the current code. The PRD (§6.2) defines the intended tool set.

Status: **agreed** (T06), 2026-11-03. Signed off by the Architect, builders and Data lead.

## Conventions

- **Read tools (7)** are deterministic and read JSON fixtures from `/data`.
  - A missing record raises `DomainLookupError` (a `ValueError`). This includes `get_policy` when no clause matches.
  - Return values are pydantic models with `extra="forbid"`.
- **Write tools (6)** are gated. Each takes a trailing `approval: ApprovalDecision | None` argument.
  - If approval is missing, not an `ApprovalDecision`, not approved, or has no token, the call raises `MockWriteError` and nothing is recorded.
  - On success, the call appends a `mock_action` trace event (`backend/cosmic_resolve/tracing.py`) and returns a plain `dict`.
- The model can call the **read tools** only, through the agent loop (`bedrock_agent.py`, via `tool_registry.py`). Results are returned to the model as JSON; `get_customer` hides the customer `name`.
- **Write tools are not model-callable.** They are only reachable from `workflow.apply_approval` after a human approves. The model never sees their schemas.
- Tools are mock-only: no live AWS, no real OMS or carrier calls.

## Read tools

| Tool | Model-callable | Signature | Returns | Notes |
|---|---|---|---|---|
| `get_case` | Yes | `get_case(case_id: str)` | `SupportCase` | `data/cases.json` |
| `get_order` | Yes | `get_order(order_id: str)` | `Order` | `data/orders.json` |
| `get_customer` | Yes (name hidden) | `get_customer(customer_id: str)` | `Customer` | `data/customers.json` |
| `get_shipment` | Yes | `get_shipment(tracking_id: str)` | `Shipment` | `data/shipments.json` |
| `check_inventory` | Yes | `check_inventory(sku: str, region: str)` | `InventoryRecord` | Raises if no matching sku + region |
| `get_policy` | Yes | `get_policy(market: str, category: str, case_type: str)` | `list[PolicyClause]` | `data/policies.json`; raises `DomainLookupError` if no clause matches |
| `get_product_listing` | Yes | `get_product_listing(sku: str)` | `Product` | `data/products.json`; listing claims for root-cause tagging |

## Write tools (approval-gated, not model-callable)

All write tools share the signature pattern `(..., approval: ApprovalDecision | None)`. None of them is in the model's tool list.

| Tool | Signature | Returned dict keys |
|---|---|---|
| `issue_refund` | `(order_id: str, amount: float, reason: str, approval)` | `action`, `order_id`, `amount`, `reason`, `approved_by` |
| `create_replacement` | `(order_id: str, sku: str, approval)` | `action`, `order_id`, `sku`, `approved_by` |
| `issue_store_credit` | `(customer_id: str, amount: float, reason: str, approval)` | `action`, `customer_id`, `amount`, `reason`, `approved_by` |
| `send_customer_message` | `(case_id: str, text: str, approval)` | `action`, `case_id`, `text`, `approved_by` |
| `escalate` | `(case_id: str, reasons: list[str], recommended_action: str, approval)` | `action`, `case_id`, `reasons`, `recommended_action`, `approved_by` |
| `tag_root_cause` | `(case_id: str, category: str, detail: str, approval)` | `action`, `case_id`, `root_cause` (dict of `category`, `detail`), `approved_by` |

Every returned dict has `action` set to the function name.

## Return models

**SupportCase**: `case_id`, `order_id`, `customer_id`, `tracking_id`, `case_type`, `market`, `category`, `complaint_text`, `channel`, `created_at`, `status` (default `"OPEN"`)

**Customer**: `customer_id`, `name`, `loyalty_tier`, `lifetime_value` (≥ 0), `prior_claims_12m` (≥ 0), `region`

**Order**: `order_id`, `customer_id`, `sku`, `price` (≥ 0), `order_date`, `status`, `fulfillment_region` (default `"US"`)

**Shipment**: `tracking_id`, `order_id`, `carrier`, `status`, `expected_delivery_date` (ISO date, nullable), `delivered_at` (ISO date, null if not delivered), `events` (list of strings), `delivered` (default false), `signature_required` (default false), `customer_photo_provided` (default false). Delivery windows are measured from `delivered_at` or `expected_delivery_date` against the case `created_at` date.

**InventoryRecord**: `sku`, `region`, `available_quantity` (≥ 0)

**Product**: `sku`, `title`, `category`, `market`, `price` (≥ 0), `listing_claims` (list of strings)

**PolicyClause**: `clause_id`, `market`, `category`, `case_type`, `text`

**RootCause**: `category`, `detail`

**ApprovalDecision**: `approved` (bool), `approved_by` (str), `approval_token` (non-empty str), `decision` (optional `Decision`), `notes` (default `""`)

**ResolutionProposal** (agent output, validated by `validators.validate_proposal`): `case_id`, `decision` (`REPLACE | REFUND | STORE_CREDIT | GOODWILL_CREDIT | ESCALATE`), `amount` (≥ 0), `policy_clause_ids` (non-empty), `evidence`, `confidence` (0–1), `escalation_reasons`, `customer_message_draft`, `root_cause` (`RootCause`)

## Decisions (T06 sign-off)

1. **Shipment events** stay plain strings (`list[str]`). Delivery dates come from `expected_delivery_date` and `delivered_at`; structured events are not needed.
2. **Goodwill caps** are set in the policy book (Bronze $5, Silver $10, Gold $20, Platinum $40) and enforced by the validator.
3. **`get_policy` raises `DomainLookupError` on no match.** The workflow catches it and returns a `NO_POLICY` run for manual handling (PRD §6.1 fallback). Tested in `tests/test_tools.py`.
4. **`escalate` and `tag_root_cause` are approval-gated**, matching PRD §5 (every write passes the checkpoint). Root causes are tagged after a human approves.
5. **Names:** the repo keeps `model_provider.py` and `bedrock_provider.py`. `llm_client.py` in the PRD and tracker is an old name.
