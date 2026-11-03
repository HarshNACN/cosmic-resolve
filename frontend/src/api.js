// Single place for talking to the Cosmic Resolve backend.
// The browser only calls the backend, through the same-origin /api proxy defined in vite.config.js.
// Nothing here calls AWS or Bedrock, and nothing here performs a write other than the
// read-only "propose" endpoint, which the backend documents as never executing an action.

const BASE = "/api";

export class ApiError extends Error {
  constructor(message, status = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const UNEXPECTED = "The backend returned an unexpected response.";

const isObject = (value) => typeof value === "object" && value !== null && !Array.isArray(value);

async function request(path, { method = "GET", signal } = {}) {
  let response;
  try {
    response = await fetch(`${BASE}${path}`, { method, signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (error && error.name === "AbortError") throw error;
    throw new ApiError("Cannot reach the backend.");
  }

  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (!response.ok) {
    // FastAPI sends {detail: "..."} for handled errors; anything else is shown generically.
    const detail = isObject(body) && typeof body.detail === "string" ? body.detail : null;
    throw new ApiError(detail || `The backend returned an error (${response.status}).`, response.status);
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

// Asks the backend for a recommendation. The backend runs its offline provider, validates the result
// and returns it for a human decision. It does not execute anything.
export async function generateProposal(caseId, signal) {
  const body = await request(`/cases/${encode(caseId)}/propose`, { method: "POST", signal });
  if (!isObject(body) || typeof body.status !== "string") throw new ApiError(UNEXPECTED);
  if (body.proposal !== null && body.proposal !== undefined && !isObject(body.proposal)) {
    throw new ApiError(UNEXPECTED);
  }
  return { ...body, proposal: body.proposal ?? null, error: typeof body.error === "string" ? body.error : null };
}

export function errorMessage(error, fallback) {
  return error instanceof ApiError && error.message ? error.message : fallback;
}
