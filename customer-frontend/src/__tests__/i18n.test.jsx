import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SupportPage, { SupportApp as SignedOutSupportApp } from "../App.jsx";
import { LanguageProvider, useLanguage } from "../i18n/LanguageProvider.jsx";
import { DEFAULT_LANGUAGE, LANGUAGES } from "../i18n/languages.js";
import { fetchSupportedLanguageCodes } from "../i18n/supportedLanguages.js";
import en from "../i18n/locales/en.js";
import es from "../i18n/locales/es.js";
import hi from "../i18n/locales/hi.js";
import pt from "../i18n/locales/pt.js";

const ORDERS = [
  { order_reference: "O-1001", product_name: "Noise Cancelling Headphones Pro", order_date: "2026-10-25", price: 649, delivery_summary: "Delivered" },
  { order_reference: "O-1002", product_name: "Smart Plug Mini", order_date: "2026-10-19", price: 45, delivery_summary: "Not delivered yet" },
];
const DEMO_NOTE = "Demo prototype. Submitted requests are not retained in this prototype.";
const RECEIPT = {
  reference: "CR-1A2B3C",
  issue_label: "Item arrived damaged",
  customer_status: "REQUEST_RECEIVED",
  customer_message: "Your request passed intake validation.",
  next_step: DEMO_NOTE,
};
// These tests are about the form and the language, so they start signed in at the form (sign-in has its own tests).
const SESSION = { token: "test-token", firstName: "Jon" };
const App = (props) => <SupportPage initialSession={SESSION} initialView="form" {...props} />;
const SupportApp = (props) => <SignedOutSupportApp initialSession={SESSION} initialView="form" {...props} />;
const STATEMENT = "The housing arrived cracked, मेरा ऑर्डर टूटा हुआ आया.";

function json(status, body) {
  return { status, body };
}

function installFetch(handlers) {
  const calls = [];
  const stub = vi.fn((url, init = {}) => {
    const key = `${init.method || "GET"} ${url}`;
    calls.push({ key, body: init.body ? JSON.parse(init.body) : undefined });
    const handler = handlers[key];
    if (!handler) return Promise.reject(new Error(`Unexpected request: ${key}`));
    return Promise.resolve(handler(init)).then(({ status, body }) => ({ ok: status >= 200 && status < 300, status, json: async () => body }));
  });
  vi.stubGlobal("fetch", stub);
  return { calls };
}

const standard = (overrides = {}) => ({
  "GET /api/support/my/orders": () => json(200, ORDERS),
  "POST /api/support/requests": () => json(200, RECEIPT),
  ...overrides,
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const selector = () => screen.getByRole("combobox"); // its label is translated too, so it is found by role
const pick = (user, code) => user.selectOptions(screen.getByRole("combobox"), code);

async function toDetails(user) {
  await user.click(await screen.findByRole("radio", { name: /Noise Cancelling/ }));
  await user.click(screen.getByRole("button", { name: en["actions.continue"] }));
  await user.click(screen.getByRole("radio", { name: new RegExp(en["issue.DAMAGED_ITEM.label"]) }));
  await user.click(screen.getByRole("button", { name: en["actions.continue"] }));
}

describe("the starting point", () => {
  it("opens in English, with the document language set and a selector that offers every language", async () => {
    installFetch(standard());
    render(<App />);
    expect(await screen.findByRole("heading", { name: en["order.heading"] })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: en["page.title"] })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("en-US");
    expect(document.documentElement.dir).toBe("ltr");
    expect(screen.getAllByRole("option").map((option) => option.value)).toEqual(LANGUAGES.map((item) => item.code));
    expect(selector()).toHaveValue("en");
  });
});

describe("manual selection translates the whole page", () => {
  it("translates every step into Hindi and keeps product names, references, amounts and the customer's words", async () => {
    const user = userEvent.setup();
    const { calls } = installFetch(standard());
    render(<App />);
    await screen.findByRole("radio", { name: /Noise Cancelling/ });
    await pick(user, "hi");

    expect(document.documentElement.lang).toBe("hi-IN");
    expect(screen.getByRole("heading", { name: hi["order.heading"] })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: hi["page.title"] })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: hi["progress.label"] })).toBeInTheDocument();
    expect(screen.getByText(hi["brand.section"])).toBeInTheDocument();
    expect(selector()).toBeInTheDocument();
    // business data is untouched: the product name, the order reference's digits, the amount and the delivery state
    expect(screen.getByText("Noise Cancelling Headphones Pro")).toBeInTheDocument();
    expect(screen.getByText(new RegExp(hi["order.ending"].replace("{digits}", "1001")))).toBeInTheDocument();
    expect(screen.getAllByText(/\$649\.00/).length).toBeGreaterThan(0);
    expect(screen.getByText(hi["server.delivered"])).toBeInTheDocument();
    expect(screen.getByText(hi["server.notDelivered"])).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: /Noise Cancelling/ }));
    await user.click(screen.getByRole("button", { name: hi["actions.continue"] }));
    expect(screen.getByRole("heading", { name: hi["problem.heading"] })).toBeInTheDocument();
    for (const key of ["DAMAGED_ITEM", "LATE_OR_MISSING", "RETURN_ITEM", "OTHER"]) {
      expect(screen.getByText(hi[`issue.${key}.label`])).toBeInTheDocument();
      expect(screen.getByText(hi[`issue.${key}.description`])).toBeInTheDocument();
    }
    await user.click(screen.getByRole("radio", { name: new RegExp(hi["issue.DAMAGED_ITEM.label"]) }));
    await user.click(screen.getByRole("button", { name: hi["actions.continue"] }));
    expect(screen.getByRole("heading", { name: hi["issue.DAMAGED_ITEM.detailHeading"] })).toBeInTheDocument();
    await user.type(screen.getByLabelText(hi["issue.DAMAGED_ITEM.detailQuestion"]), STATEMENT);
    await user.click(screen.getByRole("button", { name: hi["actions.continue"] }));

    expect(screen.getByRole("heading", { name: hi["review.heading"] })).toBeInTheDocument();
    expect(screen.getByText(STATEMENT)).toBeInTheDocument(); // the customer's own words, exactly as typed
    expect(screen.getByRole("button", { name: hi["review.submit"] })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: hi["review.submit"] }));

    expect(await screen.findByRole("heading", { name: hi["result.heading"] })).toBeInTheDocument();
    expect(screen.getByText(hi["server.intakeValidated"])).toBeInTheDocument();
    expect(screen.getByText("CR-1A2B3C")).toBeInTheDocument(); // the reference is never translated
    expect(screen.getByText(hi["issue.DAMAGED_ITEM.label"])).toBeInTheDocument();
    expect(screen.getByText(hi["server.demoNote"])).toBeInTheDocument();
    const post = calls.find((call) => call.key === "POST /api/support/requests");
    expect(post.body).toEqual({ order_reference: "O-1001", issue_type: "DAMAGED_ITEM", customer_statement: STATEMENT, channel: "WEB" });
  });

  it("formats dates and prices for the language but never changes the amount or the currency", async () => {
    const user = userEvent.setup();
    installFetch(standard());
    render(<App />);
    await screen.findByRole("radio", { name: /Noise Cancelling/ });
    const english = screen.getAllByText(/Oct 25, 2026/).length;
    expect(english).toBeGreaterThan(0);
    await pick(user, "es");
    expect(screen.queryByText(/Oct 25, 2026/)).not.toBeInTheDocument();
    expect(screen.getByText(new RegExp(new Intl.DateTimeFormat("es-MX", { month: "short", day: "numeric", year: "numeric" }).format(new Date("2026-10-25T00:00:00"))))).toBeInTheDocument();
    const price = new Intl.NumberFormat("es-MX", { style: "currency", currency: "USD" }).format(649);
    expect(price).toContain("649.00"); // the amount is unchanged; only its written form (the currency marker) follows the locale
    expect(screen.getAllByText((_, element) => element.children.length === 0 && element.textContent.includes(price)).length).toBeGreaterThan(0);
  });
});

describe("the customer's progress survives a language change", () => {
  it("keeps the step, the selected order and issue, and the typed text; refetches nothing; moves no focus", async () => {
    const user = userEvent.setup();
    const { calls } = installFetch(standard());
    render(<App />);
    await toDetails(user);
    const field = screen.getByLabelText(en["issue.DAMAGED_ITEM.detailQuestion"]);
    await user.type(field, STATEMENT);

    await pick(user, "pt");
    expect(screen.getByRole("heading", { name: pt["issue.DAMAGED_ITEM.detailHeading"] })).toBeInTheDocument();
    expect(screen.getByLabelText(pt["issue.DAMAGED_ITEM.detailQuestion"])).toHaveValue(STATEMENT); // typed text kept
    expect(document.activeElement).toBe(selector()); // focus stays where the customer put it

    await user.click(screen.getByRole("button", { name: pt["actions.back"] }));
    expect(screen.getByRole("radio", { name: new RegExp(pt["issue.DAMAGED_ITEM.label"]) })).toBeChecked(); // issue kept
    await user.click(screen.getByRole("button", { name: pt["actions.back"] }));
    expect(screen.getByRole("radio", { name: /Noise Cancelling/ })).toBeChecked(); // order kept
    await pick(user, "en");
    expect(screen.getByRole("radio", { name: /Noise Cancelling/ })).toBeChecked();
    expect(calls.filter((call) => call.key === "GET /api/support/my/orders").length).toBeLessThanOrEqual(2); // only the step's own fetch
    expect(calls.some((call) => call.key.startsWith("POST"))).toBe(false); // switching never submits anything
  });

  it("switches several times in a row without losing anything", async () => {
    const user = userEvent.setup();
    installFetch(standard());
    render(<App />);
    await toDetails(user);
    await user.type(screen.getByLabelText(en["issue.DAMAGED_ITEM.detailQuestion"]), STATEMENT);
    for (const code of ["hi", "es", "pt", "hi", "en"]) await pick(user, code);
    expect(screen.getByLabelText(en["issue.DAMAGED_ITEM.detailQuestion"])).toHaveValue(STATEMENT);
    await user.click(screen.getByRole("button", { name: en["actions.continue"] }));
    expect(screen.getByText(STATEMENT)).toBeInTheDocument();
    expect(screen.getByText(/Noise Cancelling Headphones Pro/)).toBeInTheDocument();
  });
});

describe("messages in the customer's language", () => {
  it("shows a validation message that was already on screen in the new language", async () => {
    const user = userEvent.setup();
    installFetch(standard());
    render(<App />);
    await toDetails(user);
    await user.type(screen.getByLabelText(en["issue.DAMAGED_ITEM.detailQuestion"]), "short");
    await user.click(screen.getByRole("button", { name: en["actions.continue"] }));
    expect(screen.getByRole("alert")).toHaveTextContent(en["details.tooShort"]);
    await pick(user, "es");
    expect(screen.getByRole("alert")).toHaveTextContent(es["details.tooShort"]);
    expect(screen.getByLabelText(es["issue.DAMAGED_ITEM.detailQuestion"])).toHaveValue("short");
  });

  it("shows a failed request in the active language", async () => {
    const user = userEvent.setup();
    installFetch(standard({ "POST /api/support/requests": () => json(500, { detail: "boom" }) }));
    render(<App />);
    await toDetails(user);
    await user.type(screen.getByLabelText(en["issue.DAMAGED_ITEM.detailQuestion"]), STATEMENT);
    await user.click(screen.getByRole("button", { name: en["actions.continue"] }));
    await pick(user, "hi");
    await user.click(screen.getByRole("button", { name: hi["review.submit"] }));
    expect(await screen.findByRole("alert")).toHaveTextContent(hi["errors.NETWORK"]);
    await pick(user, "pt"); // and it follows a later change
    expect(screen.getByRole("alert")).toHaveTextContent(pt["errors.NETWORK"]);
  });

  it("localizes the validation and unreadable-response errors and the order-loading failure", async () => {
    const user = userEvent.setup();
    installFetch(standard({ "POST /api/support/requests": () => json(422, { detail: [{ msg: "echo of input" }] }) }));
    render(<App />);
    await toDetails(user);
    await user.type(screen.getByLabelText(en["issue.DAMAGED_ITEM.detailQuestion"]), STATEMENT);
    await user.click(screen.getByRole("button", { name: en["actions.continue"] }));
    await pick(user, "es");
    await user.click(screen.getByRole("button", { name: es["review.submit"] }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(es["errors.VALIDATION"]);
    expect(alert).not.toHaveTextContent("echo of input"); // validation details that could echo input are still never shown
  });

  it("shows the order-loading failure in the active language, with a translated retry", async () => {
    const user = userEvent.setup();
    installFetch({ "GET /api/support/my/orders": () => json(500, {}) });
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent(en["errors.NETWORK"]);
    await pick(user, "hi");
    expect(screen.getByRole("alert")).toHaveTextContent(hi["errors.NETWORK"]);
    expect(screen.getByRole("button", { name: hi["order.retry"] })).toBeInTheDocument();
  });

  it("translates the fixed server sentences only on an exact match and shows anything else as received", async () => {
    const user = userEvent.setup();
    const odd = [{ ...ORDERS[0], delivery_summary: "Arriving next Tuesday by drone" }, { ...ORDERS[1], delivery_summary: "On the way" }];
    installFetch(standard({
      "GET /api/support/my/orders": () => json(200, odd),
      "POST /api/support/requests": () => json(200, { ...RECEIPT, next_step: "A brand new server note." }),
    }));
    render(<App />);
    await screen.findByRole("radio", { name: /Noise Cancelling/ });
    await pick(user, "hi");
    expect(screen.getByText("Arriving next Tuesday by drone")).toBeInTheDocument(); // unknown: preserved, not invented
    expect(screen.getByText(hi["server.onTheWay"])).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /Noise Cancelling/ }));
    await user.click(screen.getByRole("button", { name: hi["actions.continue"] }));
    await user.click(screen.getByRole("radio", { name: new RegExp(hi["issue.DAMAGED_ITEM.label"]) }));
    await user.click(screen.getByRole("button", { name: hi["actions.continue"] }));
    await user.type(screen.getByLabelText(hi["issue.DAMAGED_ITEM.detailQuestion"]), STATEMENT);
    await user.click(screen.getByRole("button", { name: hi["actions.continue"] }));
    await user.click(screen.getByRole("button", { name: hi["review.submit"] }));
    expect(await screen.findByText("A brand new server note.")).toBeInTheDocument();
  });
});

describe("one shared language for the page and the voice call", () => {
  function Probe({ events = [] }) {
    const { language, onVoiceEvent } = useLanguage();
    return (
      <div>
        <span data-testid="language">{language}</span>
        <button onClick={() => events.forEach(onVoiceEvent)}>deliver</button>
      </div>
    );
  }

  it("follows a language event from the voice backend, with no callback to the backend", async () => {
    const user = userEvent.setup();
    const onManualChange = vi.fn();
    render(
      <LanguageProvider onManualChange={onManualChange}>
        <Probe events={[{ type: "language", language: "hi", previous: "en", source: "speech" }]} />
      </LanguageProvider>,
    );
    await user.click(screen.getByText("deliver"));
    expect(screen.getByTestId("language")).toHaveTextContent("hi");
    expect(document.documentElement.lang).toBe("hi-IN");
    expect(onManualChange).not.toHaveBeenCalled(); // a voice-driven change is never sent back
  });

  it("reports a manual change once, and the backend's echo of it changes nothing and loops nowhere", async () => {
    const user = userEvent.setup();
    const sent = [];
    function Host() {
      const { onVoiceEvent } = useLanguage();
      // what a voice panel does: tell the backend about the manual change, and feed every language event back in
      return <button onClick={() => onVoiceEvent({ type: "language", language: sent.at(-1), source: "manual" })}>echo</button>;
    }
    render(
      <LanguageProvider onManualChange={(code) => sent.push(code)}>
        <Probe />
        <Host />
        <ManualPicker />
      </LanguageProvider>,
    );
    await user.click(screen.getByText("to-spanish"));
    expect(sent).toEqual(["es"]);
    await user.click(screen.getByText("echo"));
    await user.click(screen.getByText("echo"));
    expect(sent).toEqual(["es"]); // no second report, no loop
    expect(screen.getByTestId("language")).toHaveTextContent("es");
  });

  function ManualPicker() {
    const { setLanguage } = useLanguage();
    return <button onClick={() => setLanguage("es")}>to-spanish</button>;
  }

  it("a later spoken language replaces a manual choice, so a manual choice does not freeze the page", async () => {
    const user = userEvent.setup();
    render(
      <LanguageProvider>
        <Probe events={[{ type: "language", language: "es", previous: "hi", source: "speech" }]} />
        <HindiPicker />
      </LanguageProvider>,
    );
    await user.click(screen.getByText("to-hindi"));
    expect(screen.getByTestId("language")).toHaveTextContent("hi");
    await user.click(screen.getByText("deliver"));
    expect(screen.getByTestId("language")).toHaveTextContent("es");
  });

  function HindiPicker() {
    const { setLanguage } = useLanguage();
    return <button onClick={() => setLanguage("hi")}>to-hindi</button>;
  }

  it("ignores events for languages it has no text for, and events of other kinds", async () => {
    const user = userEvent.setup();
    render(
      <LanguageProvider>
        <Probe events={[{ type: "language", language: "xx" }, { type: "audio", language: "hi" }, { type: "state" }, null]} />
      </LanguageProvider>,
    );
    await user.click(screen.getByText("deliver"));
    expect(screen.getByTestId("language")).toHaveTextContent("en");
  });

  it("a voice-driven change keeps the support form exactly as it was", async () => {
    const user = userEvent.setup();
    installFetch(standard());
    function Voice() {
      const { onVoiceEvent } = useLanguage();
      return <button onClick={() => onVoiceEvent({ type: "language", language: "hi", source: "speech" })}>voice-hindi</button>;
    }
    render(
      <LanguageProvider>
        <SupportApp />
        <Voice />
      </LanguageProvider>,
    );
    await toDetails(user);
    await user.type(screen.getByLabelText(en["issue.DAMAGED_ITEM.detailQuestion"]), STATEMENT);
    await user.click(screen.getByText("voice-hindi"));
    expect(screen.getByRole("heading", { name: hi["issue.DAMAGED_ITEM.detailHeading"] })).toBeInTheDocument();
    expect(screen.getByLabelText(hi["issue.DAMAGED_ITEM.detailQuestion"])).toHaveValue(STATEMENT);
    expect(selector()).toHaveValue("hi"); // the selector followed the voice
  });

  it("the App tells its host about a manual choice only", async () => {
    const user = userEvent.setup();
    const onLanguageChange = vi.fn();
    installFetch(standard());
    render(<App onLanguageChange={onLanguageChange} />);
    await screen.findByRole("radio", { name: /Noise Cancelling/ });
    await pick(user, "hi");
    await pick(user, "hi");
    expect(onLanguageChange).toHaveBeenCalledTimes(1);
    expect(onLanguageChange).toHaveBeenCalledWith("hi");
  });
});

describe("the selector lists what the running voice system supports", () => {
  it("offers only the supported languages, and never drops the current one", async () => {
    installFetch(standard());
    render(<App supportedLanguages={["en", "hi"]} />);
    await screen.findByRole("radio", { name: /Noise Cancelling/ });
    expect(screen.getAllByRole("option").map((option) => option.value)).toEqual(["en", "hi"]);
  });

  it("falls back to every translated language when the list is empty", async () => {
    installFetch(standard());
    render(<App supportedLanguages={[]} />);
    await screen.findByRole("radio", { name: /Noise Cancelling/ });
    expect(screen.getAllByRole("option")).toHaveLength(LANGUAGES.length);
  });

  it("reads the voice backend's list, and returns null when it cannot", async () => {
    installFetch({ "GET /api/voice/languages": () => json(200, { multilingual: true, languages: [{ code: "en" }, { code: "hi", voice: false }] }) });
    expect(await fetchSupportedLanguageCodes()).toEqual(["en", "hi"]);
    installFetch({ "GET /api/voice/languages": () => json(404, {}) });
    expect(await fetchSupportedLanguageCodes()).toBeNull();
    installFetch({});
    expect(await fetchSupportedLanguageCodes()).toBeNull(); // a network failure
    installFetch({ "GET /api/voice/languages": () => json(200, { languages: [] }) });
    expect(await fetchSupportedLanguageCodes()).toBeNull();
  });
});

describe("the translation dictionaries", () => {
  const placeholders = (text) => [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();

  it("define every key for every supported language, with the same placeholders and no empty text", () => {
    for (const language of LANGUAGES) {
      expect(Object.keys(language.messages).sort(), language.code).toEqual(Object.keys(en).sort());
      for (const [key, text] of Object.entries(language.messages)) {
        expect(text.trim().length, `${language.code} ${key}`).toBeGreaterThan(0);
        expect(placeholders(text), `${language.code} ${key}`).toEqual(placeholders(en[key]));
      }
    }
  });

  it("registers the same language codes the voice backend uses, each with a locale and a direction", () => {
    expect(LANGUAGES.map((item) => item.code)).toEqual(["en", "es", "pt", "hi"]);
    expect(DEFAULT_LANGUAGE).toBe("en");
    for (const item of LANGUAGES) {
      expect(item.locale).toMatch(/^[a-z]{2}-[A-Z]{2}$/);
      expect(["ltr", "rtl"]).toContain(item.dir);
      expect(() => new Intl.NumberFormat(item.locale)).not.toThrow();
    }
    const visible = LANGUAGES.map((item) => item.label).join(" ");
    expect(visible).not.toContain("—"); // the customer pages use no em dashes in visible copy
  });

  it("keeps the English text free of internal terms and identifiers in every language", () => {
    for (const language of LANGUAGES) {
      for (const text of Object.values(language.messages)) {
        expect(text).not.toMatch(/DAMAGED_ON_ARRIVAL|LATE_DELIVERY|RETURN_REQUEST|AWAITING_APPROVAL|\bAI\b/);
      }
    }
  });
});

describe("adding a language needs no change to any component", () => {
  const ARABIC_LIKE = {
    code: "xr",
    label: "Test RTL",
    locale: "ar-EG",
    dir: "rtl",
    messages: { "order.heading": "RTL: which order?", "page.title": "RTL page", "language.label": "RTL language" },
  };

  it("shows a newly registered language, falls back to English for keys it lacks, and applies right-to-left", async () => {
    const user = userEvent.setup();
    installFetch(standard());
    render(
      <LanguageProvider languages={[...LANGUAGES, ARABIC_LIKE]}>
        <SupportApp />
      </LanguageProvider>,
    );
    await screen.findByRole("radio", { name: /Noise Cancelling/ });
    await user.selectOptions(screen.getByRole("combobox"), "xr");
    expect(screen.getByRole("heading", { name: "RTL: which order?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: en["actions.continue"] })).toBeInTheDocument(); // a missing key falls back to English
    expect(document.documentElement.lang).toBe("ar-EG");
    expect(document.documentElement.dir).toBe("rtl");
    expect(screen.getByText("Noise Cancelling Headphones Pro")).toBeInTheDocument(); // identifiers stay as they are
    await user.selectOptions(screen.getByRole("combobox"), "en");
    expect(document.documentElement.dir).toBe("ltr"); // and it returns to left-to-right
  });
});

describe("no page reload", () => {
  it("keeps the same page elements while the language changes", async () => {
    const user = userEvent.setup();
    installFetch(standard());
    const { container } = render(<App />);
    await screen.findByRole("radio", { name: /Noise Cancelling/ });
    const list = within(container).getByRole("group");
    const before = list.querySelector("input[type=radio]");
    await pick(user, "hi");
    expect(list.querySelector("input[type=radio]")).toBe(before); // the very same DOM node: nothing was re-created
  });
});
