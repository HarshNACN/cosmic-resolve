import { vi } from "vitest";

// Test-only fetch stub. Runtime code always uses the real backend through api.js; these fixtures copy the
// response shapes of backend/api.py (SupportCase, propose result, TraceEvent) so the tests exercise the
// same contract the UI consumes.

export const CASE_1001 = {
  case_id: "C-1001",
  order_id: "O-1001",
  customer_id: "C-001",
  tracking_id: "T-1001",
  case_type: "DAMAGED_ON_ARRIVAL",
  market: "US",
  category: "GADGETS",
  complaint_text: "The headphones arrived with a cracked housing and the box was dented.",
  channel: "EMAIL",
  created_at: "2026-11-02T09:00:00Z",
  status: "OPEN",
};

export const CASE_1002 = {
  ...CASE_1001,
  case_id: "C-1002",
  order_id: "O-1002",
  customer_id: "C-002",
  tracking_id: "T-1002",
  case_type: "LATE_DELIVERY",
  complaint_text: "The package was lost in transit and never arrived on time.",
  channel: "CHAT",
};

export const ESCALATE_RUN = {
  case_id: "C-1001",
  status: "AWAITING_APPROVAL",
  error: null,
  proposal: {
    case_id: "C-1001",
    decision: "ESCALATE",
    amount: 649,
    policy_clause_ids: ["US-GAD-DOA-01"],
    evidence: ["Shipment T-1001 status: DELIVERED", "Customer provided a photo"],
    confidence: 0.86,
    escalation_reasons: ["Value > $200 threshold"],
    customer_message_draft: "We reviewed your order and are proceeding with a policy-approved resolution.",
    root_cause: { category: "CARRIER_DAMAGE", detail: "The headphones arrived with a cracked housing." },
  },
};

export const STORE_CREDIT_RUN = {
  case_id: "C-1002",
  status: "AWAITING_APPROVAL",
  error: null,
  proposal: {
    ...ESCALATE_RUN.proposal,
    case_id: "C-1002",
    decision: "STORE_CREDIT",
    amount: 45,
    policy_clause_ids: ["US-GAD-LD-01"],
    escalation_reasons: [],
    root_cause: { category: "CARRIER_DELAY", detail: "Lost in transit" },
  },
};

export const event = (eventType, message, details = {}, timestamp = "2026-11-02T10:00:00+00:00") => ({
  timestamp,
  event_type: eventType,
  message,
  details: { case_id: "C-1001", ...details },
});

export const TRACE_1001 = [
  event("case_loaded", "Case loaded", { case_type: "DAMAGED_ON_ARRIVAL" }),
  event("context_gathered", "Read tools complete", { loaded: ["order", "customer", "shipment"] }),
  event("validation_passed", "Proposal passed validation; awaiting human approval"),
];

export function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const reply = (status, body) => ({ status, body });
export const ok = (body) => reply(200, body);
export const fail = (status, body = { detail: "Something went wrong." }) => reply(status, body);

// routes: { "GET /cases": () => ok([...]) | Promise<reply> }. A handler may be reassigned between steps.
// bodies records the parsed JSON body of each request, so tests can check exactly what the UI sent.
export function installFetch(routes) {
  const calls = [];
  const bodies = [];
  const stub = vi.fn((url, init = {}) => {
    const method = init.method || "GET";
    const key = `${method} ${url}`;
    calls.push(key);
    bodies.push(init.body ? JSON.parse(init.body) : undefined);
    const handler = routes[key];
    if (!handler) return Promise.reject(new Error(`Unexpected request in test: ${key}`));
    return new Promise((resolve, reject) => {
      const onAbort = () => reject(Object.assign(new Error("Aborted"), { name: "AbortError" }));
      if (init.signal?.aborted) return onAbort();
      init.signal?.addEventListener("abort", onAbort);
      Promise.resolve(handler(init)).then(({ status, body }) =>
        resolve({ ok: status >= 200 && status < 300, status, json: async () => body }),
      );
    });
  });
  vi.stubGlobal("fetch", stub);
  return { calls, bodies, stub };
}

// Response shapes for the checkpoint contract (backend/api.py propose and decision responses).
export const CHECKPOINT_ENABLED_RUN = {
  ...ESCALATE_RUN,
  proposal_fingerprint: "a".repeat(64),
  recommended_action: "Manual review required: Value > $200 threshold",
  checkpoint_writes_enabled: true,
};

export const CHECKPOINT_ENABLED_STORE_CREDIT_RUN = {
  ...STORE_CREDIT_RUN,
  proposal_fingerprint: "b".repeat(64),
  recommended_action: null,
  checkpoint_writes_enabled: true,
};

export const DECISION_APPROVED = {
  case_id: "C-1002",
  action: "APPROVE",
  status: "EXECUTED",
  decision: "STORE_CREDIT",
  executed_actions: [
    { action: "issue_store_credit", amount: 45 },
    { action: "send_customer_message" },
    { action: "tag_root_cause" },
  ],
  outcome: "Mock actions executed. No live system was changed.",
};

export const DECISION_REJECTED = {
  case_id: "C-1002",
  action: "REJECT",
  status: "REJECTED",
  decision: "STORE_CREDIT",
  executed_actions: [],
  outcome: "No resolution action was executed. The case requires manual handling.",
};
