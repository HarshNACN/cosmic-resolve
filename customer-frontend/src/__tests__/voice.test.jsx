import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SupportPage from "../App.jsx";
import en from "../i18n/locales/en.js";
import es from "../i18n/locales/es.js";
import hi from "../i18n/locales/hi.js";
import pt from "../i18n/locales/pt.js";

// The existing Cosmo voice UI (imported from frontend/src/voice, not copied) mounted on the customer page. The browser
// speaker is replaced by a recording stand-in; everything else (the hooks, the panel, the API client) is the real code.
vi.mock("@cosmo-voice/pcmPlayer.js", () => ({
  PcmPlayer: class {
    async unlock() {
      return true;
    }
    enqueue() {}
    stop() {}
    whenIdle() {
      return Promise.resolve();
    }
    close() {}
  },
}));

const TOKEN = "tok_demo_123";
const encoder = new TextEncoder();
const stream = (events) => ({
  ok: true,
  status: 200,
  body: new ReadableStream({
    start(controller) {
      events.forEach((event) => controller.enqueue(encoder.encode(`${JSON.stringify(event)}\n`)));
      controller.close();
    },
  }),
});
const json = (body, status = 200) => ({ ok: status < 300, status, json: async () => body });

const ORDERS = [
  { order_id: "O-1002", title: "Smart Plug Mini", price: 45, order_date: "2026-10-19", delivery_status: "LOST_IN_TRANSIT" },
  { order_id: "O-1301", title: "GPS Luggage Tag", price: 29, order_date: "2026-10-11", delivery_status: "DELIVERED" },
];
const snapshot = (overrides = {}) => ({
  session_id: "s1",
  customer: { customer_id: "C-002", first_name: "Jon" },
  state: "PICK_ORDER",
  language: "en",
  orders: ORDERS,
  selected_order_id: null,
  case_id: null,
  transcript: [],
  outcome: null,
  ...overrides,
});
const said = (...texts) => texts.map((text) => ({ role: "agent", text }));
const GREETING = "Hi Jon, this is Cosmo from Cosmic Mart. Which order can I help you with?";
const WARMUP = { llm: true, stt: true, tts: true, problems: [], agent: "Cosmo", multilingual: true, languages: { en: true, es: true, pt: true, hi: true } };

let calls;
function installFetch(extra = {}) {
  calls = [];
  const routes = {
    "POST /api/voice/warmup": () => json(WARMUP),
    "POST /api/voice/sessions": () => json(snapshot()),
    "POST /api/voice/sessions/s1/speak": () =>
      stream([
        { type: "agent_sentence", text: GREETING, lang: "en" },
        { type: "state", session: snapshot({ transcript: said(GREETING) }) },
        { type: "done" },
      ]),
    ...extra,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url, init = {}) => {
      const key = `${init.method || "GET"} ${url}`;
      calls.push({ key, url, init, headers: init.headers ?? {}, body: typeof init.body === "string" ? JSON.parse(init.body) : init.body });
      const handler = routes[key];
      if (!handler) throw new Error(`Unexpected request in test: ${key}`);
      return handler(init);
    }),
  );
}

beforeEach(() => {
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn() } });
});
afterEach(() => {
  vi.unstubAllGlobals();
});

const SESSION = { token: TOKEN, firstName: "Jon" };
const App = (props) => <SupportPage initialSession={SESSION} initialView="voice" {...props} />;
const sessionPost = () => calls.find((call) => call.key === "POST /api/voice/sessions");
const languagePosts = () => calls.filter((call) => call.key === "POST /api/voice/sessions/s1/language");

async function startCall(user, label = en["voice.start"]) {
  await user.click(await screen.findByRole("button", { name: label }));
}

describe("opening the call from the customer home page", () => {
  it("is the second of two equal choices, and opens the existing Cosmo panel", async () => {
    const user = userEvent.setup();
    installFetch({
      "POST /api/support/identify": () => json({ token: TOKEN, first_name: "Jon" }),
    });
    render(<SupportPage />);
    await user.type(screen.getByLabelText(en["identify.name"]), "Jon Park");
    await user.type(screen.getByLabelText(en["identify.code"]), "COSMO-DEMO");
    await user.click(screen.getByRole("button", { name: en["identify.submit"] }));
    await user.click(await screen.findByRole("button", { name: new RegExp(en["home.voice.title"]) }));
    expect(await screen.findByRole("heading", { name: en["voice.title"] })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: en["voice.start"] })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: en["home.back"] }));
    expect(await screen.findByRole("heading", { name: /Jon/ })).toBeInTheDocument();
  });
});

describe("a signed-in customer's call", () => {
  it("has no caller picker, never asks for the callers list, and opens the call with a header token and no customer id", async () => {
    const user = userEvent.setup();
    installFetch();
    const { container } = render(<App />);
    expect(screen.queryByText("Who is calling?")).not.toBeInTheDocument();
    expect(container.querySelector("#caller-select")).toBeNull();
    await startCall(user);
    await screen.findByText(GREETING, { selector: "li" });

    const post = sessionPost();
    expect(post.headers.Authorization).toBe(`Bearer ${TOKEN}`);
    expect(post.body).not.toHaveProperty("customer_id");
    expect(JSON.stringify(post.body)).not.toMatch(/C-\d{3}|token/i);
    for (const call of calls) {
      expect(call.key).not.toMatch(/\/voice\/callers|\/api\/cases|\/decision|\/propose|\/trace/);
      expect(call.url).not.toContain(TOKEN);
      if (call.key !== "POST /api/voice/sessions") expect(call.headers.Authorization).toBeUndefined(); // the token goes with that one request only
    }
    expect(container.textContent).not.toMatch(/C-0\d\d/);
  });

  it("runs the real hooks on this page's single React: the call starts, speaks, and listens", async () => {
    const user = userEvent.setup();
    installFetch();
    render(<App />);
    await startCall(user);
    await screen.findByText(GREETING, { selector: "li" });
    await waitFor(() => expect(screen.getByRole("status", { name: "" })).toHaveTextContent(en["voice.phase.listening"]));
    expect(screen.getByRole("button", { name: en["voice.mic.start"] })).toBeEnabled();
    expect(screen.getByRole("img", { name: /Cosmo, the voice assistant/ })).toBeInTheDocument();
  });

  it("starts in the language the page is in", async () => {
    const user = userEvent.setup();
    installFetch({ "POST /api/voice/sessions": () => json(snapshot({ language: "hi" })) });
    render(<App initialLanguage="hi" />);
    await startCall(user, hi["voice.start"]);
    await screen.findByRole("button", { name: hi["voice.endCall"] });
    expect(sessionPost().body).toEqual({ language: "hi" });
    expect(screen.getByRole("heading", { name: hi["voice.title"] })).toBeInTheDocument();
  });

  it("shows the order cards in the customer's wording, never the internal shipment code", async () => {
    const user = userEvent.setup();
    installFetch();
    const { container } = render(<App />);
    await startCall(user);
    const cards = await screen.findByRole("list", { name: en["voice.orders"] });
    expect(cards).toHaveTextContent(`Order ending in 1002 · $45.00 · ${en["server.notDelivered"]}`);
    expect(cards).toHaveTextContent(en["server.delivered"]);
    expect(container.textContent).not.toMatch(/LOST_IN_TRANSIT|Lost in transit/);
  });
});

describe("one language for the page and the call", () => {
  async function startAndSend(user, reply, events) {
    installFetch({ "POST /api/voice/sessions/s1/turn": () => stream(events) });
    render(<App />);
    await startCall(user);
    await screen.findByText(GREETING, { selector: "li" });
    await waitFor(() => expect(screen.getByRole("button", { name: en["voice.mic.start"] })).toBeEnabled());
    await user.type(screen.getByLabelText(en["voice.type.label"]), reply);
    await user.click(screen.getByRole("button", { name: en["voice.send"] }));
  }

  it("a language the customer speaks changes the whole page, and the transcript and order choice stay", async () => {
    const user = userEvent.setup();
    const reply = "Hola, quiero ayuda con mi enchufe inteligente";
    await startAndSend(user, reply, [
      { type: "customer_text", text: reply },
      { type: "language", language: "es", previous: "en", source: "speech" },
      { type: "agent_sentence", text: "Entendido, tu Smart Plug Mini.", lang: "es" },
      { type: "state", session: snapshot({ language: "es", state: "DESCRIBE", selected_order_id: "O-1002", transcript: [...said(GREETING), { role: "customer", text: reply }, ...said("Entendido, tu Smart Plug Mini.")] }) },
      { type: "done" },
    ]);
    await screen.findByText("Entendido, tu Smart Plug Mini.", { selector: "li" });
    await waitFor(() => expect(document.documentElement.lang).toBe("es-MX"));
    expect(screen.getByRole("combobox")).toHaveValue("es"); // the page's one selector followed the call
    expect(screen.getByRole("heading", { name: es["voice.title"] })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: es["voice.endCall"] })).toBeInTheDocument();
    expect(screen.getByText(GREETING, { selector: "li" })).toBeInTheDocument(); // earlier transcript lines are kept
    expect(screen.getByText(reply, { selector: "li" })).toBeInTheDocument(); // the customer's own words, untouched
    expect(languagePosts()).toHaveLength(0); // a call-driven change is never sent back to the call
  });

  it("the page selector changes the call once, the echo changes nothing, and the page and call stay together", async () => {
    const user = userEvent.setup();
    installFetch({
      "POST /api/voice/sessions/s1/language": () =>
        stream([
          { type: "language", language: "pt", previous: "en", source: "manual" },
          { type: "agent_sentence", text: "Claro, vamos continuar em português.", lang: "pt" },
          { type: "state", session: snapshot({ language: "pt", transcript: said(GREETING, "Claro, vamos continuar em português.") }) },
          { type: "done" },
        ]),
    });
    render(<App />);
    await startCall(user);
    await screen.findByText(GREETING, { selector: "li" });
    await waitFor(() => expect(screen.getByRole("button", { name: en["voice.mic.start"] })).toBeEnabled());

    await user.selectOptions(screen.getByRole("combobox"), "pt");
    await screen.findByText("Claro, vamos continuar em português.", { selector: "li" });
    expect(languagePosts()).toHaveLength(1);
    expect(languagePosts()[0].body).toEqual({ language: "pt" });
    expect(screen.getByRole("button", { name: pt["voice.endCall"] })).toBeInTheDocument();
    expect(screen.getByText(GREETING, { selector: "li" })).toBeInTheDocument();
    expect(calls.some((call) => call.key.endsWith("/turn"))).toBe(false); // switching never sends a turn or creates a case
  });

  it("shows no panel language selector of its own: the page has the single one", async () => {
    const user = userEvent.setup();
    installFetch();
    render(<App />);
    await startCall(user);
    await screen.findByText(GREETING, { selector: "li" });
    expect(screen.getAllByRole("combobox")).toHaveLength(1);
    expect(screen.queryByTestId("language-indicator")).not.toBeInTheDocument();
  });
});

describe("what a customer is told when the voice service fails", () => {
  it("a server-side failure becomes one plain sentence, with no configuration detail", async () => {
    const user = userEvent.setup();
    installFetch({ "POST /api/voice/sessions": () => json({ detail: "Set PIPER_VOICE to the path of a Piper voice" }, 503) });
    const { container } = render(<App />);
    await startCall(user);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(en["voice.errors.UNAVAILABLE"]);
    expect(container.textContent).not.toMatch(/PIPER|GROQ|Set /);
    await user.selectOptions(screen.getByRole("combobox"), "hi");
    expect(screen.getByRole("alert")).toHaveTextContent(hi["voice.errors.UNAVAILABLE"]);
  });

  it("a session that ended is reported as such", async () => {
    const user = userEvent.setup();
    installFetch({ "POST /api/voice/sessions": () => json({ detail: "Your demo session ended. Please sign in again." }, 401) });
    render(<App />);
    await startCall(user);
    expect(await screen.findByRole("alert")).toHaveTextContent(en["voice.errors.SESSION"]);
  });

  it("the setup note never shows configuration messages to a customer", async () => {
    const user = userEvent.setup();
    installFetch({ "POST /api/voice/warmup": () => json({ ...WARMUP, stt: false, problems: ["Set GROQ_API_KEY to use speech to text."] }) });
    const { container } = render(<App />);
    await screen.findByText(en["voice.setupPartial"]);
    expect(container.textContent).not.toMatch(/GROQ|Set /);
    await startCall(user);
  });
});

describe("the request tracker under a call", () => {
  it("appears once the call creates a case and shows that case's verified status, fetched with the header token", async () => {
    const user = userEvent.setup();
    installFetch({
      "POST /api/voice/sessions/s1/turn": () =>
        stream([
          { type: "customer_text", text: "yes" },
          { type: "case_created", case_id: "V-0001" },
          { type: "agent_sentence", text: "Thank you.", lang: "en" },
          { type: "state", session: snapshot({ state: "SUBMITTED", case_id: "V-0001", transcript: said(GREETING, "Thank you.") }) },
          { type: "done" },
        ]),
      "GET /api/support/my/requests/V-0001": () =>
        json({ reference: "V-0001", issue_type: "LATE_OR_MISSING", issue_label: "Order is late or missing", order_reference: "O-1002", product_name: "Smart Plug Mini", status: "UNDER_REVIEW", decision: null, amount: null, message: null }),
    });
    render(<App />);
    await startCall(user);
    await screen.findByText(GREETING, { selector: "li" });
    await waitFor(() => expect(screen.getByRole("button", { name: en["voice.mic.start"] })).toBeEnabled());
    expect(screen.queryByText(en["track.heading"])).not.toBeInTheDocument(); // nothing to track before a case exists
    await user.type(screen.getByLabelText(en["voice.type.label"]), "yes");
    await user.click(screen.getByRole("button", { name: en["voice.send"] }));
    expect(await screen.findByText(en["track.status.UNDER_REVIEW"])).toBeInTheDocument();
    const tracked = calls.find((call) => call.key === "GET /api/support/my/requests/V-0001");
    expect(tracked.headers.Authorization).toBe(`Bearer ${TOKEN}`);
    expect(tracked.url).not.toContain(TOKEN);
  });
});
