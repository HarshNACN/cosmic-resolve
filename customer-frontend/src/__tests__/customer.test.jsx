import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App.jsx";

// Test-only fetch stub. The fixtures mirror the customer-safe response shapes from backend/cosmic_resolve/customer.py.
const ORDERS = [
  {
    order_reference: "O-1001",
    product_name: "Noise Cancelling Headphones Pro",
    order_date: "2026-10-25",
    price: 649,
    delivery_summary: "Delivered",
  },
  {
    order_reference: "O-1002",
    product_name: "Smart Plug Mini",
    order_date: "2026-10-19",
    price: 45,
    delivery_summary: "Not delivered yet",
  },
  {
    order_reference: "O-1003",
    product_name: "Fitness Watch Elite",
    order_date: "2026-10-18",
    price: 299,
    delivery_summary: "Delivered",
  },
];

const DEMO_NOTE = "Demo prototype. Submitted requests are not retained in this prototype.";

const RECEIPT = {
  reference: "CR-1A2B3C",
  issue_label: "Item arrived damaged",
  customer_status: "REQUEST_RECEIVED",
  customer_message: "Your request passed intake validation.",
  next_step: DEMO_NOTE,
};

const OTHER_RECEIPT = {
  ...RECEIPT,
  reference: "CR-4D5E6F",
  issue_label: "Something else",
};

// Words that would promise a review, a queue, a notification, a lookup or a response time.
const PROMISE = /associate|specialist|review|queue|notif|track|look ?up|later|get back|respond|within|24 hours|business day|\bSLA\b|tracking number|case number/i;

function json(status, body) {
  return { status, body };
}

// Records every request so tests can check which endpoints were called and with which body.
function installFetch(handlers) {
  const calls = [];
  const stub = vi.fn((url, init = {}) => {
    const method = init.method || "GET";
    const key = `${method} ${url}`;
    calls.push({ key, body: init.body ? JSON.parse(init.body) : undefined });
    const handler = handlers[key];
    if (!handler) return Promise.reject(new Error(`Unexpected request: ${key}`));
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
  return { calls, stub };
}

const standard = (overrides = {}) => ({
  "GET /api/support/demo/orders": () => json(200, ORDERS),
  "POST /api/support/requests": () => json(200, RECEIPT),
  ...overrides,
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function chooseOrder(user, reference = "O-1001") {
  const radio = await screen.findByRole("radio", { name: new RegExp(ORDERS.find((o) => o.order_reference === reference).product_name) });
  await user.click(radio);
  await user.click(screen.getByRole("button", { name: "Continue" }));
}

async function chooseIssue(user, label) {
  await user.click(screen.getByRole("radio", { name: new RegExp(label) }));
  await user.click(screen.getByRole("button", { name: "Continue" }));
}

describe("order step", () => {
  it("loads only the demo orders and never calls the internal case or trace endpoints", async () => {
    const { calls } = installFetch(standard());
    render(<App />);
    await screen.findByRole("radio", { name: /Noise Cancelling/ });
    expect(screen.getAllByRole("radio")).toHaveLength(3);
    expect(calls.map((c) => c.key)).toEqual(["GET /api/support/demo/orders"]);
  });

  it("shows only the last four digits of an order reference, never the internal ID", async () => {
    installFetch(standard());
    render(<App />);
    await screen.findByRole("radio", { name: /Noise Cancelling/ });
    expect(screen.getByText(/Order ending in 1001/)).toBeInTheDocument();
    expect(screen.queryByText(/O-1001/)).not.toBeInTheDocument();
    expect(screen.queryByText(/C-001|C-002|C-003/)).not.toBeInTheDocument();
  });

  it("disables Continue until an order is chosen", async () => {
    installFetch(standard());
    render(<App />);
    await screen.findByRole("radio", { name: /Noise Cancelling/ });
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  });

  it("shows a loading state and then a retryable error", async () => {
    let attempt = 0;
    installFetch(standard({ "GET /api/support/demo/orders": () => (++attempt === 1 ? json(500, {}) : json(200, ORDERS)) }));
    render(<App />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading your orders");
    expect(await screen.findByRole("alert")).toHaveTextContent("We couldn't reach support just now");
    await userEvent.setup().click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("radio", { name: /Noise Cancelling/ })).toBeInTheDocument();
  });

  it("treats a malformed order response as a generic failure", async () => {
    installFetch(standard({ "GET /api/support/demo/orders": () => json(200, [{ product_name: "x" }]) }));
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("We couldn't read the response");
  });
});

describe("guided flow", () => {
  it("moves through order, problem, details, review and result", async () => {
    const user = userEvent.setup();
    installFetch(standard());
    render(<App />);
    await chooseOrder(user);
    expect(screen.getByRole("heading", { name: "What happened?" })).toBeInTheDocument();
    await chooseIssue(user, "Item arrived damaged");
    expect(screen.getByRole("heading", { name: "Tell us about the damage" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("What happened?"), "The housing arrived cracked.");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByRole("heading", { name: "Review your request" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Submit request" }));
    expect(await screen.findByRole("heading", { name: "Request received" })).toBeInTheDocument();
    expect(screen.getByText("CR-1A2B3C")).toBeInTheDocument();
  });

  it("asks only the question for the chosen issue", async () => {
    const user = userEvent.setup();
    installFetch(standard());
    render(<App />);
    await chooseOrder(user);
    await chooseIssue(user, "Order is late or missing");
    expect(screen.getByRole("heading", { name: "Tell us about the delivery" })).toBeInTheDocument();
    expect(screen.queryByText("Tell us about the damage")).not.toBeInTheDocument();
    expect(screen.queryByText("Why are you returning it?")).not.toBeInTheDocument();
  });

  it("keeps answers when moving back", async () => {
    const user = userEvent.setup();
    installFetch(standard());
    render(<App />);
    await chooseOrder(user, "O-1003");
    await chooseIssue(user, "Return an item");
    await user.type(screen.getByLabelText("Why are you returning it?"), "The strap is too small.");
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByRole("radio", { name: /Return an item/ })).toBeChecked();
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByRole("radio", { name: /Fitness Watch Elite/ })).toBeChecked();
  });

  it("shows the progress indicator with completed, current and upcoming steps as text", async () => {
    const user = userEvent.setup();
    installFetch(standard());
    render(<App />);
    const current = screen.getByRole("navigation", { name: "Progress" });
    expect(within(current).getByText("Order").closest("li")).toHaveAttribute("aria-current", "step");
    await chooseOrder(user);
    expect(within(screen.getByRole("navigation", { name: "Progress" })).getByText("Order").closest("li")).toHaveTextContent("(completed)");
  });
});

describe("details validation and review", () => {
  it("shows an inline error for an empty or too-short statement and does not advance", async () => {
    const user = userEvent.setup();
    installFetch(standard());
    render(<App />);
    await chooseOrder(user);
    await chooseIssue(user, "Item arrived damaged");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Add a few more details so we can help.");
    expect(screen.getByLabelText("What happened?")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("heading", { name: "Tell us about the damage" })).toBeInTheDocument();
  });

  it("rejects a statement longer than the maximum", async () => {
    const user = userEvent.setup();
    installFetch(standard());
    render(<App />);
    await chooseOrder(user);
    await chooseIssue(user, "Item arrived damaged");
    const field = screen.getByLabelText("What happened?");
    await user.click(field);
    await user.paste("x".repeat(1001));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Keep your details to 1000 characters or fewer.");
  });

  it("edits from review return to the owning step with the answer kept", async () => {
    const user = userEvent.setup();
    installFetch(standard());
    render(<App />);
    await chooseOrder(user);
    await chooseIssue(user, "Item arrived damaged");
    await user.type(screen.getByLabelText("What happened?"), "The housing arrived cracked.");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: /Edit\s*details/ }));
    expect(screen.getByLabelText("What happened?")).toHaveValue("The housing arrived cracked.");
  });

  it("sends only the four documented intake fields, with the statement trimmed", async () => {
    const user = userEvent.setup();
    const { calls } = installFetch(standard());
    render(<App />);
    await chooseOrder(user);
    await chooseIssue(user, "Item arrived damaged");
    await user.type(screen.getByLabelText("What happened?"), "   The housing arrived cracked.   ");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Submit request" }));
    await screen.findByRole("heading", { name: "Request received" });
    const post = calls.find((c) => c.key === "POST /api/support/requests");
    expect(Object.keys(post.body).sort()).toEqual(["channel", "customer_statement", "issue_type", "order_reference"]);
    expect(post.body).toEqual({
      order_reference: "O-1001",
      issue_type: "DAMAGED_ITEM",
      customer_statement: "The housing arrived cracked.",
      channel: "WEB",
    });
  });
});

describe("submission", () => {
  async function reachReview(user, handlers) {
    installFetch(standard(handlers));
    render(<App />);
    await chooseOrder(user);
    await chooseIssue(user, "Item arrived damaged");
    await user.type(screen.getByLabelText("What happened?"), "The housing arrived cracked.");
    await user.click(screen.getByRole("button", { name: "Continue" }));
  }

  it("shows the sending state and blocks a repeat submission", async () => {
    const user = userEvent.setup();
    let release;
    const pending = new Promise((resolve) => {
      release = resolve;
    });
    const { calls } = installFetch(standard({ "POST /api/support/requests": () => pending }));
    render(<App />);
    await chooseOrder(user);
    await chooseIssue(user, "Item arrived damaged");
    await user.type(screen.getByLabelText("What happened?"), "The housing arrived cracked.");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Submit request" }));
    const sending = screen.getByRole("button", { name: "Sending..." });
    expect(sending).toBeDisabled();
    await user.click(sending);
    expect(calls.filter((c) => c.key === "POST /api/support/requests")).toHaveLength(1);
    release(json(200, RECEIPT));
    expect(await screen.findByRole("heading", { name: "Request received" })).toBeInTheDocument();
  });

  it("keeps the review step and shows a calm error when submission fails", async () => {
    const user = userEvent.setup();
    await reachReview(user, { "POST /api/support/requests": () => json(500, {}) });
    await user.click(screen.getByRole("button", { name: "Submit request" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("We couldn't reach support just now");
    expect(screen.getByRole("heading", { name: "Review your request" })).toBeInTheDocument();
  });

  it("shows a generic message for a validation rejection and never echoes server detail", async () => {
    const user = userEvent.setup();
    await reachReview(user, {
      "POST /api/support/requests": () => json(422, { detail: [{ msg: "internal validator text" }] }),
    });
    await user.click(screen.getByRole("button", { name: "Submit request" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Check your details and try again.");
    expect(screen.queryByText(/internal validator/)).not.toBeInTheDocument();
  });

  it("treats a malformed receipt as a generic failure", async () => {
    const user = userEvent.setup();
    await reachReview(user, { "POST /api/support/requests": () => json(200, { reference: "CR-1" }) });
    await user.click(screen.getByRole("button", { name: "Submit request" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("We couldn't read the response");
  });

  it("gives an other-issue request the same intake-only receipt, with no review promise", async () => {
    const user = userEvent.setup();
    installFetch(standard({ "POST /api/support/requests": () => json(200, OTHER_RECEIPT) }));
    const { container } = render(<App />);
    await chooseOrder(user);
    await chooseIssue(user, "Something else");
    await user.type(screen.getByLabelText("Tell us what you need."), "I need help with a gift receipt.");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Submit request" }));
    expect(await screen.findByRole("heading", { name: "Request received" })).toBeInTheDocument();
    expect(screen.queryByText("We're reviewing your request")).not.toBeInTheDocument();
    expect(container.textContent).not.toMatch(PROMISE);
  });

  it("starts a fresh request from the result", async () => {
    const user = userEvent.setup();
    await reachReview(user, {});
    await user.click(screen.getByRole("button", { name: "Submit request" }));
    await screen.findByRole("heading", { name: "Request received" });
    await user.click(screen.getByRole("button", { name: "Start another request" }));
    expect(screen.getByRole("heading", { name: "Which order do you need help with?" })).toBeInTheDocument();
    expect(await screen.findByRole("radio", { name: /Noise Cancelling/ })).not.toBeChecked();
  });
});

describe("safe rendering and privacy", () => {
  it("renders hostile statement text as text, never as markup", async () => {
    const user = userEvent.setup();
    const hostile = "<img src=x onerror=\"window.__pwned=1\"> <b>bold</b> not a real order";
    installFetch(standard());
    const { container } = render(<App />);
    await chooseOrder(user);
    await chooseIssue(user, "Something else");
    await user.type(screen.getByLabelText("Tell us what you need."), hostile);
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByText(hostile)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(window.__pwned).toBeUndefined();
  });

  it("never shows policy, confidence, trace, internal status or model language on any step", async () => {
    const user = userEvent.setup();
    // Internal words, matched case-insensitively. "AI" is a whole word only, so "again" is not flagged.
    // "Smart Plug Mini" is a fixture product name, not our copy, so the word "smart" is not checked here.
    // Internal words, matched case-insensitively. Internal status tokens are uppercase and matched exactly, so the
    // required customer wording "passed intake validation" is not flagged.
    const forbidden = /policy|confidence|trace|proposal|fingerprint|approval|\bAI\b/i;
    const internalTokens = /AWAITING_APPROVAL|VALIDATION_FAILED|PROVIDER_ERROR|DAMAGED_ON_ARRIVAL|LATE_DELIVERY|RETURN_REQUEST/;
    installFetch(standard());
    const { container } = render(<App />);
    await screen.findByRole("radio", { name: /Noise Cancelling/ });
    expect(container.textContent).not.toMatch(forbidden);
    expect(container.textContent).not.toMatch(internalTokens);
    await chooseOrder(user);
    expect(container.textContent).not.toMatch(forbidden);
    expect(container.textContent).not.toMatch(internalTokens);
    await chooseIssue(user, "Item arrived damaged");
    await user.type(screen.getByLabelText("What happened?"), "The housing arrived cracked.");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(container.textContent).not.toMatch(forbidden);
    expect(container.textContent).not.toMatch(internalTokens);
    await user.click(screen.getByRole("button", { name: "Submit request" }));
    await screen.findByRole("heading", { name: "Request received" });
    expect(container.textContent).not.toMatch(forbidden);
    expect(container.textContent).not.toMatch(internalTokens);
  });

  it("never calls the decision, propose, trace, or internal case endpoints", async () => {
    const user = userEvent.setup();
    const { calls } = installFetch(standard());
    render(<App />);
    await chooseOrder(user);
    await chooseIssue(user, "Return an item");
    await user.type(screen.getByLabelText("Why are you returning it?"), "The strap is too small.");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Submit request" }));
    await screen.findByRole("heading", { name: "Request received" });
    for (const call of calls) {
      expect(call.key).not.toMatch(/\/api\/cases|\/decision|\/propose|\/trace|\/traces/);
    }
  });

  it("uses no em dashes in visible copy", async () => {
    installFetch(standard());
    const { container } = render(<App />);
    await screen.findByRole("radio", { name: /Noise Cancelling/ });
    expect(container.textContent).not.toContain("—");
  });
});

describe("accessibility semantics", () => {
  it("uses native radio groups so the choices are keyboard operable", async () => {
    installFetch(standard());
    render(<App />);
    const radios = await screen.findAllByRole("radio");
    expect(radios.length).toBe(3);
    for (const radio of radios) expect(radio).toHaveAttribute("type", "radio");
  });

  it("names the form fields with real labels, not placeholders", async () => {
    const user = userEvent.setup();
    installFetch(standard());
    render(<App />);
    await chooseOrder(user);
    await chooseIssue(user, "Item arrived damaged");
    expect(screen.getByLabelText("What happened?")).toBeInTheDocument();
    expect(screen.getByLabelText("What happened?")).toHaveAttribute("aria-describedby", "statement-help");
  });

  it("announces the submission state politely", async () => {
    const user = userEvent.setup();
    installFetch(standard());
    render(<App />);
    await chooseOrder(user);
    await chooseIssue(user, "Item arrived damaged");
    await user.type(screen.getByLabelText("What happened?"), "The housing arrived cracked.");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByRole("status", { hidden: true })).toHaveAttribute("aria-live", "polite");
    await waitFor(() => expect(screen.getByRole("button", { name: "Submit request" })).toBeEnabled());
  });
});

describe("result semantics", () => {
  async function submitDamaged(user) {
    installFetch(standard());
    const rendered = render(<App />);
    await chooseOrder(user);
    await chooseIssue(user, "Item arrived damaged");
    await user.type(screen.getByLabelText("What happened?"), "The housing arrived cracked.");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Submit request" }));
    await screen.findByRole("heading", { name: "Request received" });
    return rendered;
  }

  it("shows the reference under the label Reference and says the request passed intake validation", async () => {
    const user = userEvent.setup();
    const { container } = await submitDamaged(user);
    const reference = within(container).getByText("Reference");
    expect(reference.nextElementSibling).toHaveTextContent("CR-1A2B3C");
    expect(within(container).getByText("Your request passed intake validation.")).toBeInTheDocument();
  });

  it("shows the prototype disclosure as a subordinate note", async () => {
    const user = userEvent.setup();
    const { container } = await submitDamaged(user);
    const note = within(container).getByRole("complementary", { name: "Demo note" });
    expect(note).toHaveTextContent("Demo prototype");
    expect(note).toHaveTextContent("Submitted requests are not retained in this prototype.");
  });

  it("makes no promise of review, notification, lookup, timing or a service-level agreement", async () => {
    const user = userEvent.setup();
    const { container } = await submitDamaged(user);
    expect(container.textContent).not.toMatch(PROMISE);
  });

  it("does not offer a way to look the reference up later", async () => {
    const user = userEvent.setup();
    const { container } = await submitDamaged(user);
    expect(within(container).queryByRole("link")).not.toBeInTheDocument();
    expect(within(container).queryByRole("textbox")).not.toBeInTheDocument();
    expect(within(container).queryByText(/look|track|status/i)).not.toBeInTheDocument();
  });

  it("moves focus to the result heading so the outcome is announced", async () => {
    const user = userEvent.setup();
    await submitDamaged(user);
    expect(screen.getByRole("heading", { name: "Request received" })).toHaveFocus();
  });

  it("moves focus to the new step heading when continuing", async () => {
    const user = userEvent.setup();
    installFetch(standard());
    render(<App />);
    await chooseOrder(user);
    expect(screen.getByRole("heading", { name: "What happened?" })).toHaveFocus();
    await chooseIssue(user, "Item arrived damaged");
    expect(screen.getByRole("heading", { name: "Tell us about the damage" })).toHaveFocus();
  });

  it("keeps the prototype disclosure visually secondary to the success state", async () => {
    const user = userEvent.setup();
    const { container } = await submitDamaged(user);
    const heading = within(container).getByRole("heading", { name: "Request received" });
    const note = within(container).getByRole("complementary", { name: "Demo note" });
    expect(heading.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
