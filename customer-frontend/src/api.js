// Customer API client. Calls only the two customer-safe routes under /api/support.
// It never calls /api/cases, /api/traces, any decision route, or any propose route.
// The browser holds no credentials. This is DEMO CUSTOMER MODE: the orders are a server-side allowlist of
// synthetic records, and there is no customer authentication.

const BASE = "/api/support";
const GENERIC_FAILURE = "We couldn't reach support just now. Please try again.";
const UNEXPECTED = "We couldn't read the response. Please try again.";

export class SupportApiError extends Error {
  // code is a stable identifier ("NETWORK", "UNEXPECTED", "VALIDATION") the page translates; it is null for the one
  // server-written message that is shown as received (a plain 404 detail), which cannot be safely translated.
  constructor(message, status = null, code = null) {
    super(message);
    this.name = "SupportApiError";
    this.status = status;
    this.code = code;
  }
}

const isObject = (value) => typeof value === "object" && value !== null && !Array.isArray(value);
const isText = (value) => typeof value === "string" && value.length > 0;

// Only the server's plain 404 message is shown, because the API writes it for customers.
// Validation details, which can echo input, are never shown.
function plainDetail(body, status) {
  if (status === 404 && isObject(body) && typeof body.detail === "string") return body.detail;
  return null;
}

async function request(path, { method = "GET", body, signal } = {}) {
  const headers = { Accept: "application/json" };
  const init = { method, headers, signal };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(`${BASE}${path}`, init);
  } catch (error) {
    if (error && error.name === "AbortError") throw error;
    throw new SupportApiError(GENERIC_FAILURE, null, "NETWORK");
  }

  let parsed = null;
  try {
    parsed = await response.json();
  } catch {
    parsed = null;
  }

  if (!response.ok) {
    const plain = plainDetail(parsed, response.status);
    throw new SupportApiError(
      plain || (response.status === 422 ? "Check your details and try again." : GENERIC_FAILURE),
      response.status,
      plain ? null : response.status === 422 ? "VALIDATION" : "NETWORK",
    );
  }
  if (parsed === null) throw new SupportApiError(UNEXPECTED, response.status, "UNEXPECTED");
  return parsed;
}

const ORDER_FIELDS = ["order_reference", "product_name", "order_date", "delivery_summary"];

export async function fetchDemoOrders(signal) {
  const body = await request("/demo/orders", { signal });
  if (
    !Array.isArray(body) ||
    !body.every(
      (order) =>
        isObject(order) &&
        ORDER_FIELDS.every((field) => isText(order[field])) &&
        typeof order.price === "number",
    )
  ) {
    throw new SupportApiError(UNEXPECTED, null, "UNEXPECTED");
  }
  return body.map((order) => ({
    order_reference: order.order_reference,
    product_name: order.product_name,
    order_date: order.order_date,
    price: order.price,
    delivery_summary: order.delivery_summary,
  }));
}

// The only status is intake validation. The demo does not route, store or notify anyone.
const STATUSES = ["REQUEST_RECEIVED"];

export async function submitSupportRequest(payload, signal) {
  // Only the documented intake fields are sent.
  const { order_reference, issue_type, customer_statement, channel } = payload;
  const body = await request("/requests", {
    method: "POST",
    body: { order_reference, issue_type, customer_statement, channel },
    signal,
  });
  if (
    !isObject(body) ||
    !isText(body.reference) ||
    !isText(body.issue_label) ||
    !STATUSES.includes(body.customer_status) ||
    !isText(body.customer_message) ||
    !isText(body.next_step)
  ) {
    throw new SupportApiError(UNEXPECTED, null, "UNEXPECTED");
  }
  return {
    reference: body.reference,
    issue_label: body.issue_label,
    customer_status: body.customer_status,
    customer_message: body.customer_message,
    next_step: body.next_step,
  };
}
