// Display helpers. Everything returns plain strings; callers render them as React text nodes.

export function humanize(value) {
  if (typeof value !== "string" || value === "") return "Not available";
  const text = value.replace(/_/g, " ").toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function formatUsd(amount) {
  if (typeof amount !== "number" || Number.isNaN(amount)) return "Not available";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(amount);
}

export function formatConfidence(confidence) {
  if (typeof confidence !== "number" || Number.isNaN(confidence)) return "Not available";
  return `${Math.round(confidence * 100)}%`;
}

export function formatTimestamp(value) {
  if (typeof value !== "string" || value === "") return "Time not available";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

// Compact form for dense metadata, for example "Nov 2, 9:00 AM". Falls back to the raw value if unparseable.
export function formatShortDateTime(value) {
  if (typeof value !== "string" || value === "") return "Not available";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(date);
}

export function asText(value) {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2) ?? "";
  } catch {
    return String(value);
  }
}

// Trace categories come from the backend's event_type values (backend/cosmic_resolve/workflow.py).
// Unknown types fall into "Other" rather than being guessed at.
const EVENTS = {
  case_loaded: { category: "case", label: "Case and context" },
  context_gathered: { category: "tools", label: "Tool calls" },
  provider_request: { category: "provider", label: "Provider" },
  model_exchange: { category: "provider", label: "Provider" },
  proposal_generated: { category: "provider", label: "Provider" },
  validation_passed: { category: "validation", label: "Validation", status: "Passed" },
  validation_failed: { category: "validation", label: "Validation", status: "Failed" },
  voice_case_created: { category: "case", label: "Voice call" },
  voice_turn: { category: "case", label: "Voice call" },
  human_decision: { category: "human", label: "Human checkpoint" },
  mock_action: { category: "write", label: "Write action" },
  actions_executed: { category: "write", label: "Actions executed" },
  provider_error: { category: "error", label: "Error", status: "Error" },
  no_policy: { category: "error", label: "Error", status: "No policy found" },
};

export function classifyEvent(eventType) {
  return EVENTS[eventType] || { category: "other", label: "Other" };
}

// The backend appends a case_loaded event at the start of every run of a case. Grouping on those keeps
// repeated recommendations readable. Events are never reordered; events before the first case_loaded
// (which the backend does not normally produce) go into an earlier-activity group.
export function groupTraceRuns(events) {
  const runs = [];
  for (const event of events) {
    if (event.event_type === "case_loaded" || runs.length === 0) {
      const isRun = event.event_type === "case_loaded";
      runs.push({ isRun, startedAt: isRun ? event.timestamp : null, events: [] });
    }
    runs[runs.length - 1].events.push(event);
  }
  return runs;
}
