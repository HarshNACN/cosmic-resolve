// Single place for talking to the Cosmic Resolve backend.
// The browser only calls the backend, through the same-origin /api proxy defined in vite.config.js.
// Nothing here calls AWS or Bedrock. The only consequential call is submitDecision, and the backend refuses
// it unless checkpoint writes are enabled there. The browser is never the security boundary.

const BASE = "/api";

export class ApiError extends Error {
  constructor(message, status = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const UNEXPECTED = "The response was not in the expected format.";

const isObject = (value) => typeof value === "object" && value !== null && !Array.isArray(value);

// Human-readable message from a FastAPI error body. Handled errors send {detail: "..."}; request validation
// errors send {detail: [{msg, ...}]}. Only plain text is returned; it is always rendered as text.
function errorDetail(body) {
  if (!isObject(body)) return null;
  if (typeof body.detail === "string") return body.detail;
  if (Array.isArray(body.detail) && body.detail.length > 0 && typeof body.detail[0]?.msg === "string") {
    return body.detail[0].msg.replace(/^Value error, /, "");
  }
  return null;
}

async function request(path, { method = "GET", signal, body: payload } = {}) {
  const headers = { Accept: "application/json" };
  const init = { method, signal, headers };
  if (payload !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(payload);
  }

  let response;
  try {
    response = await fetch(`${BASE}${path}`, init);
  } catch (error) {
    if (error && error.name === "AbortError") throw error;
    throw new ApiError("The service did not respond. Retry.");
  }

  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (!response.ok) {
    throw new ApiError(errorDetail(body) || `The backend returned an error (${response.status}).`, response.status);
  }
  if (body === null) throw new ApiError(UNEXPECTED, response.status);
  return body;
}

const encode = (caseId) => encodeURIComponent(caseId);

export async function fetchCases(signal) {
  const body = await request("/cases", { signal });
  if (!Array.isArray(body) || !body.every((item) => isObject(item) && typeof item.case_id === "string")) {
    throw new ApiError(UNEXPECTED);
  }
  return body;
}

export async function fetchCase(caseId, signal) {
  const body = await request(`/cases/${encode(caseId)}`, { signal });
  if (!isObject(body) || typeof body.case_id !== "string") throw new ApiError(UNEXPECTED);
  return body;
}

export async function fetchTrace(caseId, signal) {
  const body = await request(`/cases/${encode(caseId)}/trace`, { signal });
  if (!Array.isArray(body) || !body.every((event) => isObject(event) && typeof event.event_type === "string")) {
    throw new ApiError(UNEXPECTED);
  }
  return body.map((event) => ({ ...event, details: isObject(event.details) ? event.details : {} }));
}

// Asks the backend for a recommendation. The backend runs the provider its configuration selects (offline rules or
// Amazon Bedrock), validates the result and returns it, with the provider labels, for a human decision.
// It does not execute anything.
export async function generateProposal(caseId, signal) {
  const body = await request(`/cases/${encode(caseId)}/propose`, { method: "POST", signal });
  if (!isObject(body) || typeof body.status !== "string") throw new ApiError(UNEXPECTED);
  if (body.proposal !== null && body.proposal !== undefined && !isObject(body.proposal)) {
    throw new ApiError(UNEXPECTED);
  }
  return {
    ...body,
    proposal: body.proposal ?? null,
    error: typeof body.error === "string" ? body.error : null,
    // Checkpoint capability and integrity identifier come from the backend; the UI never decides these itself.
    checkpoint_writes_enabled: body.checkpoint_writes_enabled === true,
    proposal_fingerprint: typeof body.proposal_fingerprint === "string" ? body.proposal_fingerprint : null,
    recommended_action: typeof body.recommended_action === "string" ? body.recommended_action : null,
    // Operational labels from the backend ("offline" or "bedrock"; "rule_based", "single_shot" or "agentic").
    provider: typeof body.provider === "string" ? body.provider : null,
    execution_mode: typeof body.execution_mode === "string" ? body.execution_mode : null,
    tool_calls: Number.isInteger(body.tool_calls) ? body.tool_calls : null,
  };
}

// Only the documented decision fields are ever sent. The server rejects any other field.
const DECISION_FIELDS = ["action", "proposal_fingerprint", "reviewer", "note", "edited_message"];

export async function submitDecision(caseId, decision, signal) {
  const payload = Object.fromEntries(
    Object.entries(decision).filter(([key, value]) => DECISION_FIELDS.includes(key) && value !== undefined && value !== null),
  );
  const body = await request(`/cases/${encode(caseId)}/decision`, { method: "POST", signal, body: payload });
  if (!isObject(body) || typeof body.status !== "string" || !Array.isArray(body.executed_actions)) {
    throw new ApiError(UNEXPECTED);
  }
  return body;
}

export function errorMessage(error, fallback) {
  return error instanceof ApiError && error.message ? error.message : fallback;
}
