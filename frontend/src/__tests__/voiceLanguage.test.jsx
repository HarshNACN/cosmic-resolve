import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import CallPanel from "../voice/CallPanel.jsx";

vi.mock("../voice/pcmPlayer.js", () => ({
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

const ORDERS = [{ order_id: "O-1002", title: "Smart Plug Mini", price: 45, order_date: "2026-10-19", delivery_status: "LOST_IN_TRANSIT" }];
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
const greetingEvents = () => [
  { type: "agent_sentence", text: GREETING, lang: "en" },
  { type: "state", session: snapshot({ transcript: [{ role: "agent", text: GREETING }] }) },
  { type: "done" },
];
const CALLERS = { callers: [{ customer_id: "C-002", name: "Jon Park", tier: "SILVER", orders: 5 }] };
const LABELS = { en: "English", es: "Español", pt: "Português (Brasil)" };
const MULTILINGUAL = {
  llm: true,
  stt: true,
  tts: true,
  problems: [],
  agent: "Cosmo",
  multilingual: true,
  languages: { en: true, es: true, pt: true },
  language_labels: LABELS,
  browser_locales: { en: "en-US", es: "es-MX", pt: "pt-BR" },
};
const ENGLISH_ONLY = { llm: true, stt: true, tts: true, problems: [], agent: "Cosmo", multilingual: false };

let calls;
function installFetch(warmup, extra = {}) {
  calls = [];
  const routes = {
    "GET /api/voice/callers": () => json(CALLERS),
    "POST /api/voice/warmup": () => json(warmup),
    "POST /api/voice/sessions": () => json(snapshot()),
    "POST /api/voice/sessions/s1/speak": () => stream(greetingEvents()),
    ...extra,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url, init = {}) => {
      const key = `${init.method || "GET"} ${url}`;
      calls.push({ key, init });
      const handler = routes[key];
      if (!handler) throw new Error(`Unexpected request in test: ${key}`);
      return handler(init);
    }),
  );
}

async function startCall(user) {
  await user.click(await screen.findByRole("button", { name: "Start call" }));
  await screen.findByText(GREETING, { selector: "li" });
  await waitFor(() => expect(screen.getByRole("button", { name: "Start speaking" })).toBeEnabled());
}

const indicator = () => screen.getByTestId("language-indicator");

beforeEach(() => {
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn() } });
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("language indicator and selector", () => {
  it("is absent with the feature off, so the panel is exactly the English one", async () => {
    const user = userEvent.setup();
    installFetch(ENGLISH_ONLY);
    render(<CallPanel />);
    await startCall(user);
    expect(screen.queryByTestId("language-indicator")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Call language")).not.toBeInTheDocument();
    expect(JSON.parse(calls.find((c) => c.key === "POST /api/voice/sessions").init.body)).toEqual({ customer_id: "C-002" });
  });

  it("shows the call language and updates it when the server reports a switch", async () => {
    const user = userEvent.setup();
    installFetch(MULTILINGUAL, {
      "POST /api/voice/sessions/s1/turn": () =>
        stream([
          { type: "customer_text", text: "Hola, quiero ayuda con mi enchufe inteligente" },
          { type: "language", language: "es", previous: "en", source: "speech" },
          { type: "agent_sentence", text: "Entendido, tu Smart Plug Mini.", lang: "es" },
          { type: "state", session: snapshot({ language: "es", state: "DESCRIBE", transcript: said("Entendido, tu Smart Plug Mini.") }) },
          { type: "done" },
        ]),
    });
    render(<CallPanel />);
    await startCall(user);
    expect(indicator()).toHaveTextContent("English");

    await user.type(screen.getByLabelText("Type a reply to the agent"), "Hola, quiero ayuda con mi enchufe inteligente");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("Entendido, tu Smart Plug Mini.", { selector: "li" });
    await waitFor(() => expect(indicator()).toHaveTextContent("Español"));
  });

  it("the manual selector asks the server to switch and shows the re-asked step", async () => {
    const user = userEvent.setup();
    const onCaseCreated = vi.fn();
    installFetch(MULTILINGUAL, {
      "POST /api/voice/sessions/s1/language": () =>
        stream([
          { type: "language", language: "pt", previous: "en", source: "manual" },
          { type: "agent_sentence", text: "Claro, vamos continuar em português.", lang: "pt" },
          { type: "state", session: snapshot({ language: "pt", transcript: said("Claro, vamos continuar em português.") }) },
          { type: "done" },
        ]),
    });
    render(<CallPanel onCaseCreated={onCaseCreated} />);
    await startCall(user);

    await user.selectOptions(screen.getByLabelText("Call language"), "pt");
    await screen.findByText("Claro, vamos continuar em português.", { selector: "li" });
    expect(JSON.parse(calls.find((c) => c.key === "POST /api/voice/sessions/s1/language").init.body)).toEqual({ language: "pt" });
    await waitFor(() => expect(indicator()).toHaveTextContent("Português (Brasil)"));
    expect(onCaseCreated).not.toHaveBeenCalled(); // switching language never creates a case
    expect(calls.some((c) => c.key.endsWith("/turn"))).toBe(false);
  });

  it("a language picked before the call is sent when the session is created", async () => {
    const user = userEvent.setup();
    installFetch(MULTILINGUAL);
    render(<CallPanel />);
    await screen.findByRole("button", { name: "Start call" });
    await user.selectOptions(screen.getByLabelText("Call language"), "es");
    await startCall(user);
    expect(JSON.parse(calls.find((c) => c.key === "POST /api/voice/sessions").init.body)).toEqual({ customer_id: "C-002", language: "es" });
  });
});

describe("speech and voices", () => {
  it("says a voice is missing, keeps the text, and marks a language without a voice as text only", async () => {
    const user = userEvent.setup();
    installFetch(
      { ...MULTILINGUAL, languages: { en: true, es: true, pt: false }, problems: ["The Portuguese voice was not found."] },
      {
        "POST /api/voice/sessions/s1/language": () =>
          stream([
            { type: "language", language: "pt", previous: "en", source: "manual" },
            { type: "agent_sentence", text: "Claro, vamos continuar em português.", lang: "pt" },
            { type: "voice_unavailable", language: "pt", label: "Português (Brasil)" },
            { type: "state", session: snapshot({ language: "pt", transcript: said("Claro, vamos continuar em português.") }) },
            { type: "done" },
          ]),
      },
    );
    render(<CallPanel />);
    await startCall(user);
    expect(screen.getByRole("option", { name: "Português (Brasil) (text only)" })).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Call language"), "pt");
    expect(await screen.findByText(/No Português \(Brasil\) voice is installed/)).toBeInTheDocument();
    expect(screen.getByText("Claro, vamos continuar em português.", { selector: "li" })).toBeInTheDocument();
  });

  it("uses the browser voice for the right locale when the server has no voice at all", async () => {
    const user = userEvent.setup();
    const spoken = [];
    vi.stubGlobal(
      "SpeechSynthesisUtterance",
      class {
        constructor(text) {
          this.text = text;
        }
      },
    );
    vi.stubGlobal("speechSynthesis", { speak: (u) => spoken.push(u), cancel: vi.fn() });
    installFetch(
      { ...MULTILINGUAL, tts: false, languages: { en: false, es: false, pt: false } },
      {
        "POST /api/voice/sessions/s1/language": () =>
          stream([
            { type: "language", language: "es", previous: "en", source: "manual" },
            { type: "agent_sentence", text: "Claro, sigamos en español.", lang: "es" },
            { type: "state", session: snapshot({ language: "es", transcript: said(GREETING, "Claro, sigamos en español.") }) },
            { type: "done" },
          ]),
      },
    );
    render(<CallPanel />);
    await startCall(user);
    await user.selectOptions(screen.getByLabelText("Call language"), "es");
    await screen.findByText("Claro, sigamos en español.", { selector: "li" });
    expect(spoken.map((u) => [u.text, u.lang])).toEqual(expect.arrayContaining([[GREETING, "en-US"], ["Claro, sigamos en español.", "es-MX"]]));
  });

  it("shows the associate's approved message as a labelled note, in its original wording", async () => {
    const user = userEvent.setup();
    installFetch(MULTILINGUAL, {
      "POST /api/voice/sessions/s1/turn": () =>
        stream([
          { type: "agent_sentence", text: "Buenas noticias: tu reemplazo está en camino.", lang: "es" },
          { type: "agent_text", text: "Your replacement ships today.", lang: "en" },
          {
            type: "state",
            session: snapshot({
              language: "es",
              transcript: [...said("Buenas noticias: tu reemplazo está en camino."), { role: "agent", text: "Your replacement ships today.", note: true }],
            }),
          },
          { type: "done" },
        ]),
    });
    render(<CallPanel />);
    await startCall(user);
    await user.type(screen.getByLabelText("Type a reply to the agent"), "hola");
    await user.click(screen.getByRole("button", { name: "Send" }));
    const note = await screen.findByText("Your replacement ships today.", { selector: "li" });
    expect(note).toHaveTextContent("Cosmo (approved message)");
  });
});
