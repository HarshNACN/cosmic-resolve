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
  human_decision: { category: "human", label: "Human checkpoint" },
  mock_action: { category: "write", label: "Write action" },
  provider_error: { category: "error", label: "Error", status: "Error" },
  no_policy: { category: "error", label: "Error", status: "No policy found" },
};

export function classifyEvent(eventType) {
  return EVENTS[eventType] || { category: "other", label: "Other" };
}
