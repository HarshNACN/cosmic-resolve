# Tool contracts

Source of truth: `cosmic_resolve/tools.py` (functions) and `cosmic_resolve/models.py` (return shapes). This document describes the current code. The PRD (§6.2) defines the intended tool set.

Status: **draft for sign-off** (T06). Owners to confirm: Architect, Builders, Data lead.

## Conventions

- **Read tools (7)** are deterministic and read JSON fixtures from `/data`.
  - A missing record raises `DomainLookupError` (a `ValueError`). This includes `get_policy` when no clause matches.
  - Return values are pydantic models with `extra="forbid"`.
- **Write tools (6)** are gated. Each takes a trailing `approval: ApprovalDecision | None` argument.
  - If approval is missing, not an `ApprovalDecision`, not approved, or has no token, the call raises `MockWriteError` and nothing is recorded.
  - On success, the call appends a `mock_action` trace event (`cosmic_resolve/tracing.py`) and returns a plain `dict`.
- No tool calls the LLM. Tools are mock-only: no live AWS, no real OMS or carrier calls.

## Read tools

| Tool | Signature | Returns | Notes |
|---|---|---|---|
| `get_case` | `get_case(case_id: str)` | `SupportCase` | `data/cases.json` |
| `get_order` | `get_order(order_id: str)` | `Order` | `data/orders.json` |
| `get_customer` | `get_customer(customer_id: str)` | `Customer` | `data/customers.json` |
| `get_shipment` | `get_shipment(tracking_id: str)` | `Shipment` | `data/shipments.json` |
| `check_inventory` | `check_inventory(sku: str, region: str)` | `InventoryRecord` | Raises if no matching sku + region |
| `get_policy` | `get_policy(market: str, category: str, case_type: str)` | `list[PolicyClause]` | `data/policies.json`; raises `DomainLookupError` if no clause matches |
| `get_product_listing` | `get_product_listing(sku: str)` | `Product` | `data/products.json`; listing claims for root-cause tagging |

## Write tools (approval-gated)

All write tools share the signature pattern `(..., approval: ApprovalDecision | None)`.

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

**Shipment**: `tracking_id`, `order_id`, `carrier`, `status`, `events` (list of strings), `delivered` (default false), `signature_required` (default false), `customer_photo_provided` (default false)

**InventoryRecord**: `sku`, `region`, `available_quantity` (≥ 0)

**Product**: `sku`, `title`, `category`, `market`, `price` (≥ 0), `listing_claims` (list of strings)

**PolicyClause**: `clause_id`, `market`, `category`, `case_type`, `text`

**RootCause**: `category`, `detail`

**ApprovalDecision**: `approved` (bool), `approved_by` (str), `approval_token` (non-empty str), `decision` (optional `Decision`), `notes` (default `""`)

**ResolutionProposal** (agent output, validated by `validators.validate_proposal`): `case_id`, `decision` (`REPLACE | REFUND | STORE_CREDIT | GOODWILL_CREDIT | ESCALATE`), `amount` (≥ 0), `policy_clause_ids` (non-empty), `evidence`, `confidence` (0–1), `escalation_reasons`, `customer_message_draft`, `root_cause` (`RootCause`)

## Open items for sign-off

These are questions, not changes. Nothing in code has been altered.

1. **Shipment events** are plain strings (`list[str]`). PRD §6.2 says "carrier events". **Open: team undecided** on whether structured events (timestamp, status, location) are needed.
2. **Goodwill caps** are not in any tool or model. PRD §16 leaves per-tier caps open, so the Data lead's policy book needs to decide them.
3. **`get_policy` raises `DomainLookupError` on no match.** Decided: raise, not return `[]`. The agent should catch this and emit `ESCALATE` with the reason "no applicable policy clause" (PRD §6.1 fallback). **Note:** the code still returns `[]`; the change to `tools.py` is not yet made.
4. **`escalate` and `tag_root_cause` are approval-gated.** This matches PRD §5 ("every write passes the checkpoint") but means the agent can't tag root causes without a human approval. Confirm that's intended.
5. **Names:** the PRD and tracker reference `llm_client.py` (T15), while the repo has `model_provider.py`. Not a tool issue, but it affects where tools are called from.
