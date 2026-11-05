import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import CaseStatus from "../components/CaseStatus.jsx";
import ResultStep from "../components/ResultStep.jsx";
import YourRequests from "../components/YourRequests.jsx";
import { LanguageProvider, useLanguage } from "../i18n/LanguageProvider.jsx";
import en from "../i18n/locales/en.js";
import es from "../i18n/locales/es.js";
import pt from "../i18n/locales/pt.js";
import hi from "../i18n/locales/hi.js";

// The tracker shows only what the server has verified. These tests protect that: the status words, what each state may
// reveal (an outcome only once the resolution is confirmed done), polling that stops only when nothing will change, the
// header-only token, and the same behaviour in every language.
const TOKEN = "tok_demo_123";
const REQUEST = {
  reference: "W-0001",
  issue_type: "LATE_OR_MISSING",
  issue_label: "Order is late or missing",
  order_reference: "O-1002",
  product_name: "Smart Plug Mini",
  status: "RECEIVED",
  decision: null,
  amount: null,
  message: null,
};
const RESOLVED_REFUND = { ...REQUEST, status: "RESOLVED", decision: "REFUND", amount: 45, message: "Your refund is on its way. Gracias por su paciencia." };

const reply = (body, status = 200) => ({ ok: status < 300, status, json: async () => body });

// answers is a function of the call number (1, 2, 3...) returning a body, "fail", or { http, body } for an error response
function installFetch(answers) {
  const calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url, init = {}) => {
      calls.push({ url, headers: init.headers ?? {}, method: init.method || "GET" });
      const answer = answers(calls.length, url);
      if (answer === "fail") throw new Error("network down");
      return answer?.http ? reply(answer.body, answer.http) : reply(answer);
    }),
  );
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function LanguageButtons() {
  const { setLanguage } = useLanguage();
  return (
    <>
      <button onClick={() => setLanguage("hi")}>to-hindi</button>
      <button onClick={() => setLanguage("es")}>to-spanish</button>
    </>
  );
}
const withLanguage = (ui) => (
  <LanguageProvider>
    {ui}
    <LanguageButtons />
  </LanguageProvider>
);
const status = (name) => screen.findByText(en[`track.status.${name}`]);

describe("what each status says and reveals", () => {
  it.each([
    ["RECEIVED", "Request received", "Your request is with the support team."],
    ["UNDER_REVIEW", "Under review", "A member of the support team is reviewing your request."],
    ["FOLLOW_UP", "Follow-up required", "A member of the support team needs to follow up on your request."],
  ])("%s shows its words and no outcome", async (code, label, note) => {
    installFetch(() => ({ ...REQUEST, status: code }));
    render(withLanguage(<CaseStatus token={TOKEN} reference="W-0001" intervalMs={10} />));
    expect(await screen.findByText(label)).toBeInTheDocument();
    expect(screen.getByText(note)).toBeInTheDocument();
    expect(screen.queryByText(/refund|replacement|credit/i)).not.toBeInTheDocument();
  });

  it("an approved but unconfirmed resolution says so plainly and claims nothing was done", async () => {
    installFetch(() => ({ ...REQUEST, status: "APPROVED" }));
    render(withLanguage(<CaseStatus token={TOKEN} reference="W-0001" intervalMs={10} />));
    expect(await screen.findByText("Resolution approved")).toBeInTheDocument();
    expect(screen.getByText(/not confirmed as completed yet/)).toBeInTheDocument();
    expect(screen.queryByText(/refund|replacement|credit|issued|arranged/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Resolved")).not.toBeInTheDocument();
  });

  it("a confirmed resolution shows the decision, the exact amount, the approved message and the demo disclosure", async () => {
    installFetch(() => RESOLVED_REFUND);
    render(withLanguage(<CaseStatus token={TOKEN} reference="W-0001" intervalMs={10} />));
    expect(await screen.findByText("Resolved")).toBeInTheDocument();
    expect(screen.getByText("Your request was approved and a refund of $45.00 was issued for your Smart Plug Mini.")).toBeInTheDocument();
    // the associate's words are kept exactly as written, out of the way in a collapsed control
    expect(screen.getByText(RESOLVED_REFUND.message).closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText(en["server.caseNote"])).toBeInTheDocument();
  });

  it("each confirmed decision has its own wording", async () => {
    for (const [decision, amount, text] of [
      ["REPLACE", null, "Your request was approved and a replacement was arranged for your Smart Plug Mini."],
      ["STORE_CREDIT", 10, "Your request was approved and a store credit of $10.00 was added to your account for your Smart Plug Mini."],
      ["GOODWILL_CREDIT", 5.5, "Your request was approved and a goodwill credit of $5.50 was added to your account for your Smart Plug Mini."],
    ]) {
      installFetch(() => ({ ...REQUEST, status: "RESOLVED", decision, amount }));
      const { unmount } = render(withLanguage(<CaseStatus token={TOKEN} reference="W-0001" intervalMs={10} />));
      expect(await screen.findByText(text)).toBeInTheDocument();
      unmount();
    }
  });
});

describe("polling", () => {
  it("follows a request from received to resolved, then stops asking", async () => {
    const sequence = [REQUEST, { ...REQUEST, status: "UNDER_REVIEW" }, { ...REQUEST, status: "APPROVED" }, RESOLVED_REFUND];
    const calls = installFetch((n) => sequence[Math.min(n, sequence.length) - 1]);
    render(withLanguage(<CaseStatus token={TOKEN} reference="W-0001" intervalMs={15} />));
    await status("RESOLVED");
    const settled = calls.length;
    expect(settled).toBe(4);
    await new Promise((resolve) => setTimeout(resolve, 120));
    expect(calls.length).toBe(settled); // a confirmed resolution does not change by itself
  });

  it("keeps asking while approved, because the actions are not confirmed done", async () => {
    const calls = installFetch(() => ({ ...REQUEST, status: "APPROVED" }));
    render(withLanguage(<CaseStatus token={TOKEN} reference="W-0001" intervalMs={15} />));
    await screen.findByText("Resolution approved");
    await waitFor(() => expect(calls.length).toBeGreaterThan(3));
  });

  it("stops asking for a follow-up too, and recovers from a dropped connection", async () => {
    const calls = installFetch((n) => (n === 1 ? "fail" : { ...REQUEST, status: "FOLLOW_UP" }));
    render(withLanguage(<CaseStatus token={TOKEN} reference="W-0001" intervalMs={15} />));
    expect(await screen.findByText(en["track.error"])).toBeInTheDocument();
    await status("FOLLOW_UP");
    const settled = calls.length;
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(calls.length).toBe(settled);
  });

  it("does not keep retrying when the request is not theirs or the session ended", async () => {
    const calls = installFetch(() => ({ http: 404, body: { detail: "That request is not available." } }));
    render(withLanguage(<CaseStatus token={TOKEN} reference="W-0099" intervalMs={10} />));
    await screen.findByText(en["track.error"]);
    await new Promise((resolve) => setTimeout(resolve, 80));
    expect(calls).toHaveLength(1);
  });

  it("sends the token in a header only, to the customer's own request path", async () => {
    const calls = installFetch(() => REQUEST);
    render(withLanguage(<CaseStatus token={TOKEN} reference="W-0001" intervalMs={10} />));
    await status("RECEIVED");
    expect(calls[0].url).toBe("/api/support/my/requests/W-0001");
    expect(calls[0].headers.Authorization).toBe(`Bearer ${TOKEN}`);
    expect(calls[0].url).not.toContain(TOKEN);
  });
});

describe("language", () => {
  it("a status already on screen changes language, and the approved message and the reference are never translated", async () => {
    const user = userEvent.setup();
    installFetch(() => RESOLVED_REFUND);
    render(withLanguage(<CaseStatus token={TOKEN} reference="W-0001" intervalMs={10} />));
    await screen.findByText("Resolved");
    await user.click(screen.getByText("to-hindi"));
    expect(screen.getByText(hi["track.status.RESOLVED"])).toBeInTheDocument();
    expect(screen.getByText(hi["track.note.RESOLVED"])).toBeInTheDocument();
    const amount = new Intl.NumberFormat("hi-IN", { style: "currency", currency: "USD" }).format(45);
    expect(screen.getByText(hi["track.summary.REFUND"].replace("{amount}", amount).replace("{product}", "Smart Plug Mini"))).toBeInTheDocument();
    expect(screen.getByText(RESOLVED_REFUND.message)).toBeInTheDocument(); // the associate's words, exactly as approved
    await user.click(screen.getByText("to-spanish"));
    expect(screen.getByText(es["track.status.RESOLVED"])).toBeInTheDocument();
  });

  it("every status, note, decision and message label exists in every language", () => {
    for (const messages of [en, es, hi]) {
      for (const status of ["RECEIVED", "UNDER_REVIEW", "APPROVED", "RESOLVED", "FOLLOW_UP"]) {
        expect(messages[`track.status.${status}`]).toBeTruthy();
        expect(messages[`track.note.${status}`]).toBeTruthy();
      }
      for (const decision of ["REPLACE", "REFUND", "STORE_CREDIT", "GOODWILL_CREDIT"]) expect(messages[`track.decision.${decision}`]).toBeTruthy();
    }
  });
});

describe("the result screen and the home list", () => {
  const receipt = (reference) => ({ reference, issue_label: "Order is late or missing", customer_status: "REQUEST_RECEIVED", customer_message: en["server.requestSent"], next_step: en["server.caseNote"] });

  it("tracks a real case reference on the result screen and shows nothing to track for an old validation-only reference", async () => {
    const calls = installFetch(() => REQUEST);
    const { unmount } = render(withLanguage(<ResultStep receipt={receipt("W-0001")} issueType="LATE_OR_MISSING" token={TOKEN} onStartAnother={() => {}} />));
    await status("RECEIVED");
    expect(calls[0].url).toBe("/api/support/my/requests/W-0001");
    unmount();

    const before = calls.length;
    render(withLanguage(<ResultStep receipt={receipt("CR-1A2B3C")} issueType="LATE_OR_MISSING" token={TOKEN} onStartAnother={() => {}} />));
    await screen.findByText("CR-1A2B3C");
    expect(calls.length).toBe(before); // nothing is fetched and no tracker is drawn
    expect(screen.queryByText(en["track.heading"])).not.toBeInTheDocument();
  });

  it("lists the customer's own requests with their verified statuses, in the active language", async () => {
    const user = userEvent.setup();
    installFetch(() => [
      { ...REQUEST, reference: "V-0002", status: "UNDER_REVIEW", issue_type: "DAMAGED_ITEM" },
      { ...RESOLVED_REFUND, reference: "W-0001" },
    ]);
    render(withLanguage(<YourRequests token={TOKEN} intervalMs={10} />));
    expect(await screen.findByText("Under review")).toBeInTheDocument();
    expect(screen.getByText("Resolved")).toBeInTheDocument();
    expect(screen.getAllByText("Smart Plug Mini")).toHaveLength(2);
    await user.click(screen.getByText("to-hindi"));
    expect(screen.getByText(hi["track.status.UNDER_REVIEW"])).toBeInTheDocument();
    expect(screen.getByText(new RegExp(hi["issue.DAMAGED_ITEM.label"]))).toBeInTheDocument();
  });

  it("shows nothing at all when there are no requests or the service cannot be reached", async () => {
    installFetch(() => []);
    const { container, unmount } = render(withLanguage(<YourRequests token={TOKEN} intervalMs={10} />));
    await new Promise((resolve) => setTimeout(resolve, 40));
    expect(container.querySelector(".your-requests")).toBeNull();
    unmount();
    installFetch(() => "fail");
    const second = render(withLanguage(<YourRequests token={TOKEN} intervalMs={10} />));
    await new Promise((resolve) => setTimeout(resolve, 40));
    expect(second.container.querySelector(".your-requests")).toBeNull();
  });
});

// The English message the associate approved was drafted before the decision and can say the outcome is still pending.
// The customer reads a summary built from the verified decision, in the active language; the original is never altered.
const PENDING_DRAFT = "Hello, and thank you for contacting Cosmic Mart. We have proposed sending you a replacement, pending final approval.";
const RESOLVED_REPLACE = { ...REQUEST, status: "RESOLVED", decision: "REPLACE", amount: null, message: PENDING_DRAFT };

describe("the resolution summary follows the active language and never rewrites the approved message", () => {
  it.each([
    ["en", "Your request was approved and a replacement was arranged for your Smart Plug Mini."],
    ["es", "Tu solicitud fue aprobada y se gestionó un reemplazo para tu Smart Plug Mini."],
    ["pt", "Sua solicitação foi aprovada e uma substituição foi providenciada para o seu Smart Plug Mini."],
    ["hi", "आपका अनुरोध स्वीकृत हुआ और आपके Smart Plug Mini के लिए रिप्लेसमेंट की व्यवस्था की गई।"],
  ])("a verified resolution reads in %s, and the stored English draft is shown unchanged", async (code, expected) => {
    installFetch(() => RESOLVED_REPLACE);
    render(
      <LanguageProvider initial={code}>
        <CaseStatus token={TOKEN} reference="W-0001" intervalMs={10} />
      </LanguageProvider>,
    );
    expect(await screen.findByText(expected)).toBeInTheDocument();
    expect(screen.getByText(PENDING_DRAFT).textContent).toBe(PENDING_DRAFT);
  });

  it("changing the language after the resolution is shown updates the summary and leaves the stored message byte-identical", async () => {
    const user = userEvent.setup();
    installFetch(() => RESOLVED_REPLACE);
    render(withLanguage(<CaseStatus token={TOKEN} reference="W-0001" intervalMs={10} />));
    await screen.findByText(en["track.summary.REPLACE"].replace("{product}", "Smart Plug Mini"));
    await user.click(screen.getByText("to-spanish"));
    expect(screen.getByText(es["track.summary.REPLACE"].replace("{product}", "Smart Plug Mini"))).toBeInTheDocument();
    expect(screen.queryByText(en["track.summary.REPLACE"].replace("{product}", "Smart Plug Mini"))).not.toBeInTheDocument();
    const original = screen.getByText(PENDING_DRAFT);
    expect(original.textContent).toBe(PENDING_DRAFT);
    expect(original.closest("details")).toBeTruthy();
    expect(screen.getByText(es["track.original"])).toBeInTheDocument(); // labelled as the original, as written
    await user.click(screen.getByText("to-hindi"));
    expect(screen.getByText(PENDING_DRAFT).textContent).toBe(PENDING_DRAFT);
  });

  it("never claims completion unless the server says RESOLVED", async () => {
    for (const status of ["RECEIVED", "UNDER_REVIEW", "APPROVED", "FOLLOW_UP"]) {
      installFetch(() => ({ ...REQUEST, status, decision: "REPLACE", message: PENDING_DRAFT }));
      const { unmount } = render(withLanguage(<CaseStatus token={TOKEN} reference="W-0001" intervalMs={10} />));
      await screen.findByText(en[`track.status.${status}`]);
      expect(screen.queryByText(/was approved and a replacement/)).not.toBeInTheDocument();
      expect(screen.queryByText(PENDING_DRAFT)).not.toBeInTheDocument();
      expect(screen.queryByText("Resolved")).not.toBeInTheDocument();
      unmount();
    }
  });

  it("every language has every summary, the original label and the brand label", () => {
    for (const messages of [en, es, pt, hi]) {
      for (const decision of ["REPLACE", "REFUND", "STORE_CREDIT", "GOODWILL_CREDIT"]) expect(messages[`track.summary.${decision}`]).toContain("{product}");
      for (const key of ["track.original", "track.summaryLabel", "voice.who.summary", "brand.home"]) expect(messages[key]).toBeTruthy();
    }
  });
});
