import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App.jsx";
import en from "../i18n/locales/en.js";
import es from "../i18n/locales/es.js";
import hi from "../i18n/locales/hi.js";

// Demo sign-in is synthetic identification, not authentication. These tests protect what the page promises about it:
// one failure message, a header-only token, no customer id in the browser, and no way to list customers.
const ORDERS = [
  { order_reference: "O-1002", product_name: "Smart Plug Mini", order_date: "2026-10-19", price: 45, delivery_summary: "Not delivered yet" },
];
const TOKEN = "tok_demo_123";

function json(status, body) {
  return { status, body };
}

function installFetch(handlers) {
  const calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url, init = {}) => {
      const key = `${init.method || "GET"} ${url}`;
      calls.push({ key, url, headers: init.headers ?? {}, body: init.body ? JSON.parse(init.body) : undefined });
      const handler = handlers[key];
      if (!handler) return Promise.reject(new Error(`Unexpected request: ${key}`));
      return Promise.resolve(handler(init)).then(({ status, body }) => ({ ok: status >= 200 && status < 300, status, json: async () => body }));
    }),
  );
  return calls;
}

const signedIn = (overrides = {}) => ({
  "POST /api/support/identify": () => json(200, { token: TOKEN, first_name: "Jon" }),
  "POST /api/voice/warmup": () => json(200, { llm: true, stt: true, tts: true, problems: [], agent: "Cosmo" }),
  "GET /api/support/my/orders": () => json(200, ORDERS),
  ...overrides,
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function signIn(user, name = "Jon Park", code = "COSMO-DEMO") {
  await user.type(screen.getByLabelText(en["identify.name"]), name);
  await user.type(screen.getByLabelText(en["identify.code"]), code);
  await user.click(screen.getByRole("button", { name: en["identify.submit"] }));
}

describe("the sign-in screen", () => {
  it("is the first screen, loads nothing, and says plainly that it is a demo sign-in", async () => {
    const calls = installFetch({});
    render(<App />);
    expect(screen.getByRole("heading", { name: en["identify.heading"] })).toBeInTheDocument();
    expect(screen.getByText(en["identify.demoNote"])).toBeInTheDocument();
    expect(screen.getByText(/Jon Park, Maya Rowe, Anita Lee, Penelope Coleman/)).toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(calls).toHaveLength(0); // no orders, customers or voice endpoints are touched before signing in
    expect(screen.getByRole("button", { name: en["identify.submit"] })).toBeDisabled();
  });

  it("shows one failure message for any wrong name or code, in the active language, and keeps what was typed", async () => {
    const user = userEvent.setup();
    installFetch({ "POST /api/support/identify": () => json(401, { detail: "We couldn't find that account." }) });
    render(<App />);
    await signIn(user, "Someone Else", "wrong");
    expect(await screen.findByRole("alert")).toHaveTextContent(en["errors.IDENTIFY"]);
    expect(screen.getByLabelText(en["identify.name"])).toHaveValue("Someone Else");
    await user.selectOptions(screen.getByRole("combobox"), "es");
    expect(screen.getByRole("alert")).toHaveTextContent(es["errors.IDENTIFY"]);
    expect(screen.getByLabelText(es["identify.name"])).toHaveValue("Someone Else");
  });

  it("sends only the name and the code, in the body, and never shows or keeps a customer id", async () => {
    const user = userEvent.setup();
    const calls = installFetch(signedIn());
    const { container } = render(<App />);
    await signIn(user);
    await screen.findByRole("heading", { name: /Jon/ });
    expect(calls[0].key).toBe("POST /api/support/identify");
    expect(calls[0].body).toEqual({ name: "Jon Park", code: "COSMO-DEMO" });
    expect(container.textContent).not.toMatch(/C-0\d\d/);
    expect(container.innerHTML).not.toContain(TOKEN);
  });
});

describe("the home screen", () => {
  it("greets by first name and offers two equally prominent choices, with the voice one explained while unavailable", async () => {
    const user = userEvent.setup();
    installFetch(signedIn());
    render(<App />);
    await signIn(user);
    expect(await screen.findByRole("heading", { name: en["home.heading"].replace("{name}", "Jon") })).toBeInTheDocument();
    const voice = screen.getByRole("button", { name: new RegExp(en["home.voice.title"]) });
    const form = screen.getByRole("button", { name: new RegExp(en["home.form.title"]) });
    expect(voice.className).toBe(form.className); // the same card style: neither is more prominent
    expect(voice).toBeEnabled(); // the voice service answered the warm-up
    expect(voice).toHaveTextContent(en["home.voice.text"]);
    expect(form).toBeEnabled();
    expect(screen.getByText(en["account.signedInAs"].replace("{name}", "Jon"))).toBeInTheDocument();
  });

  it("opens the form with the customer's own orders, sending the token in a header and never in the address", async () => {
    const user = userEvent.setup();
    const calls = installFetch(signedIn());
    render(<App />);
    await signIn(user);
    await user.click(await screen.findByRole("button", { name: new RegExp(en["home.form.title"]) }));
    expect(await screen.findByRole("radio", { name: /Smart Plug Mini/ })).toBeInTheDocument();
    const orders = calls.find((call) => call.key === "GET /api/support/my/orders");
    expect(orders.headers.Authorization).toBe(`Bearer ${TOKEN}`);
    for (const call of calls) {
      expect(call.url).not.toContain(TOKEN);
      expect(call.url).not.toMatch(/token|customer/i);
      expect(call.key).not.toMatch(/\/api\/cases|\/decision|\/propose|\/trace|\/voice\/callers|\/support\/customers/);
    }
  });

  it("goes back to the options and returns to the form with the choice kept", async () => {
    const user = userEvent.setup();
    installFetch(signedIn());
    render(<App />);
    await signIn(user);
    await user.click(await screen.findByRole("button", { name: new RegExp(en["home.form.title"]) }));
    await user.click(await screen.findByRole("radio", { name: /Smart Plug Mini/ }));
    await user.click(screen.getByRole("button", { name: en["home.back"] }));
    expect(await screen.findByRole("heading", { name: /Jon/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: new RegExp(en["home.form.title"]) }));
    expect(await screen.findByRole("radio", { name: /Smart Plug Mini/ })).toBeChecked();
  });
});

describe("when the voice service is not there", () => {
  it("disables only the voice card, says why, and leaves the form working", async () => {
    const user = userEvent.setup();
    installFetch(signedIn({ "POST /api/voice/warmup": () => json(503, { detail: "Set GROQ_API_KEY" }) }));
    render(<App />);
    await signIn(user);
    const voice = await screen.findByRole("button", { name: new RegExp(en["home.voice.title"]) });
    await waitFor(() => expect(voice).toBeDisabled());
    expect(voice).toHaveTextContent(en["home.voice.soon"]);
    expect(screen.queryByText(/GROQ/)).not.toBeInTheDocument(); // server setup detail never reaches a customer
    expect(screen.getByRole("button", { name: new RegExp(en["home.form.title"]) })).toBeEnabled();
  });
});

describe("signing out and the session", () => {
  it("sign out returns to the sign-in screen and forgets the session and any form answers", async () => {
    const user = userEvent.setup();
    const calls = installFetch(signedIn());
    render(<App />);
    await signIn(user);
    await user.click(await screen.findByRole("button", { name: new RegExp(en["home.form.title"]) }));
    await user.click(await screen.findByRole("radio", { name: /Smart Plug Mini/ }));
    await user.click(screen.getByRole("button", { name: en["account.signOut"] }));
    expect(screen.getByRole("heading", { name: en["identify.heading"] })).toBeInTheDocument();
    expect(screen.queryByText(/Signed in as/)).not.toBeInTheDocument();
    expect(screen.getByLabelText(en["identify.name"])).toHaveValue("");
    const before = calls.length;
    await signIn(user);
    await user.click(await screen.findByRole("button", { name: new RegExp(en["home.form.title"]) }));
    expect(await screen.findByRole("radio", { name: /Smart Plug Mini/ })).not.toBeChecked(); // nothing carried over
    expect(calls.length).toBeGreaterThan(before);
  });

  it("shows a session that ended in the active language", async () => {
    const user = userEvent.setup();
    installFetch(signedIn({ "GET /api/support/my/orders": () => json(401, { detail: "Please sign in" }) }));
    render(<App />);
    await signIn(user);
    await user.click(await screen.findByRole("button", { name: new RegExp(en["home.form.title"]) }));
    expect(await screen.findByRole("alert")).toHaveTextContent(en["errors.SESSION"]);
    await user.selectOptions(screen.getByRole("combobox"), "hi");
    expect(screen.getByRole("alert")).toHaveTextContent(hi["errors.SESSION"]);
  });
});

describe("language across sign-in", () => {
  it("keeps the chosen language through sign-in and translates the home screen, with the first name unchanged", async () => {
    const user = userEvent.setup();
    installFetch(signedIn());
    render(<App />);
    await user.selectOptions(screen.getByRole("combobox"), "hi");
    expect(screen.getByRole("heading", { name: hi["identify.heading"] })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("hi-IN");
    await user.type(screen.getByLabelText(hi["identify.name"]), "Jon Park");
    await user.type(screen.getByLabelText(hi["identify.code"]), "COSMO-DEMO");
    await user.click(screen.getByRole("button", { name: hi["identify.submit"] }));
    expect(await screen.findByRole("heading", { name: hi["home.heading"].replace("{name}", "Jon") })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: new RegExp(hi["home.form.title"]) })).toBeEnabled();
    await waitFor(() => expect(screen.getByText(hi["account.signedInAs"].replace("{name}", "Jon"))).toBeInTheDocument());
  });
});

describe("submitting as a signed-in customer", () => {
  const RECEIPT = {
    reference: "W-0001",
    issue_label: "Order is late or missing",
    customer_status: "REQUEST_RECEIVED",
    customer_message: "Your request was sent to our support team.",
    next_step: "Demo prototype with synthetic data. No real money moves and nothing ships.",
  };
  const STATEMENT = "The smart plug never arrived and tracking says it was lost.";

  async function fillAndSubmit(user, calls) {
    await signIn(user);
    await user.click(await screen.findByRole("button", { name: new RegExp(en["home.form.title"]) }));
    await user.click(await screen.findByRole("radio", { name: /Smart Plug Mini/ }));
    await user.click(screen.getByRole("button", { name: en["actions.continue"] }));
    await user.click(screen.getByRole("radio", { name: new RegExp(en["issue.LATE_OR_MISSING.label"]) }));
    await user.click(screen.getByRole("button", { name: en["actions.continue"] }));
    await user.type(screen.getByLabelText(en["issue.LATE_OR_MISSING.detailQuestion"]), STATEMENT);
    await user.click(screen.getByRole("button", { name: en["actions.continue"] }));
    await user.click(screen.getByRole("button", { name: en["review.submit"] }));
    return calls;
  }

  it("sends the token in a header and only the four intake fields, then shows the real case reference", async () => {
    const user = userEvent.setup();
    const calls = installFetch(signedIn({ "POST /api/support/requests": () => json(200, RECEIPT) }));
    render(<App />);
    await fillAndSubmit(user, calls);
    expect(await screen.findByRole("heading", { name: en["result.heading"] })).toBeInTheDocument();
    const post = calls.find((call) => call.key === "POST /api/support/requests");
    expect(post.headers.Authorization).toBe(`Bearer ${TOKEN}`);
    expect(post.body).toEqual({ order_reference: "O-1002", issue_type: "LATE_OR_MISSING", customer_statement: STATEMENT, channel: "WEB" });
    expect(screen.getByText("W-0001")).toBeInTheDocument(); // the same id the employee sees in the queue
    expect(screen.getByText(RECEIPT.customer_message)).toBeInTheDocument();
    expect(screen.getByText(RECEIPT.next_step)).toBeInTheDocument();
  });

  it("shows the receipt's sentences in the active language and never changes the case reference", async () => {
    const user = userEvent.setup();
    const calls = installFetch(signedIn({ "POST /api/support/requests": () => json(200, RECEIPT) }));
    render(<App />);
    await fillAndSubmit(user, calls);
    await screen.findByRole("heading", { name: en["result.heading"] });
    await user.selectOptions(screen.getByRole("combobox"), "hi");
    expect(screen.getByText(hi["server.requestSent"])).toBeInTheDocument();
    expect(screen.getByText(hi["server.caseNote"])).toBeInTheDocument();
    expect(screen.getByText("W-0001")).toBeInTheDocument();
    expect(screen.getByText(hi["issue.LATE_OR_MISSING.label"])).toBeInTheDocument();
  });

  it("refuses with a localized message when the session has ended, and creates nothing", async () => {
    const user = userEvent.setup();
    const calls = installFetch(signedIn({ "POST /api/support/requests": () => json(401, { detail: "Please sign in" }) }));
    render(<App />);
    await fillAndSubmit(user, calls);
    expect(await screen.findByRole("alert")).toHaveTextContent(en["errors.SESSION"]);
    await user.selectOptions(screen.getByRole("combobox"), "es");
    expect(screen.getByRole("alert")).toHaveTextContent(es["errors.SESSION"]);
    expect(screen.queryByRole("heading", { name: es["result.heading"] })).not.toBeInTheDocument();
  });
});
