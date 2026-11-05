import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SupportPage from "../App.jsx";
import en from "../i18n/locales/en.js";
import es from "../i18n/locales/es.js";
import hi from "../i18n/locales/hi.js";
import pt from "../i18n/locales/pt.js";

// What the call says it is doing must be true: "Ready" while the microphone is off, "Listening" only while it records,
// and the verified outcome shown in the customer's language. Also: the brand link, and an old case never shown as the
// new call's. The speaker and microphone are stand-ins; the hooks, panel, tracker and page are the real code.
const gate = vi.hoisted(() => ({ hold: false, release: null, wait: null }));
vi.mock("@cosmo-voice/pcmPlayer.js", () => ({
  PcmPlayer: class {
    async unlock() {
      return true;
    }
    enqueue() {}
    stop() {}
    whenIdle() {
      if (!gate.hold) return Promise.resolve();
      gate.wait = new Promise((resolve) => {
        gate.release = () => {
          gate.hold = false;
          resolve();
        };
      });
      return gate.wait;
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

const ORDERS = [{ order_id: "O-1002", title: "Smart Plug Mini", price: 45, order_date: "2026-10-19", delivery_status: "LOST_IN_TRANSIT" }];
const said = (...texts) => texts.map((text) => ({ role: "agent", text }));
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
const GREETING = "Hi Jon, this is Cosmo from Cosmic Mart. Which order can I help you with?";
const PENDING_DRAFT = "Hello, and thank you for contacting Cosmic Mart. We have proposed sending you a replacement, pending final approval.";
const WARMUP = { llm: true, stt: true, tts: true, problems: [], agent: "Cosmo", multilingual: true, languages: { en: true, es: true, pt: true, hi: true } };
const tracked = (status) => ({
  reference: "V-0001",
  issue_type: "LATE_OR_MISSING",
  issue_label: "Order is late or missing",
  order_reference: "O-1002",
  product_name: "Smart Plug Mini",
  status,
  decision: status === "RESOLVED" ? "REPLACE" : null,
  amount: null,
  message: status === "RESOLVED" ? PENDING_DRAFT : null,
});

let calls;
let tracks;
let verified; // the status the server reports for the call's case
let turn; // optional gate for the turn request
function installFetch(extra = {}) {
  calls = [];
  const routes = {
    "POST /api/voice/warmup": () => json(WARMUP),
    "POST /api/voice/sessions": (init, body) => json(snapshot({ language: body?.language ?? "en" })),
    "POST /api/voice/sessions/s1/speak": (init, body) =>
      body?.kind === "outcome" ? stream(extra.outcomeEvents) : stream([{ type: "agent_sentence", text: GREETING, lang: "en" }, { type: "state", session: snapshot({ transcript: said(GREETING) }) }, { type: "done" }]),
    "GET /api/support/my/requests/V-0001": () => json(tracked(verified)),
    ...extra.routes,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url, init = {}) => {
      const key = `${init.method || "GET"} ${url}`;
      const body = typeof init.body === "string" ? JSON.parse(init.body) : init.body;
      calls.push({ key, url, init, body });
      const handler = routes[key];
      if (!handler) throw new Error(`Unexpected request in test: ${key}`);
      if (key.endsWith("/turn") && turn) await turn;
      return handler(init, body);
    }),
  );
}

class FakeRecorder {
  static isTypeSupported() {
    return true;
  }
  constructor(mediaStream, options) {
    this.state = "inactive";
    this.mimeType = options?.mimeType || "audio/webm";
  }
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob([new Uint8Array(4000)]) });
    this.onstop?.();
  }
}

beforeEach(() => {
  tracks = [];
  verified = "UNDER_REVIEW";
  turn = null;
  gate.hold = false;
  vi.stubGlobal("MediaRecorder", FakeRecorder);
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: vi.fn(async () => {
        const track = { stop: vi.fn() };
        tracks.push(track);
        return { getTracks: () => [track] };
      }),
    },
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
});

const SESSION = { token: TOKEN, firstName: "Jon" };
const App = (props) => <SupportPage initialSession={SESSION} initialView="voice" {...props} />;
const statusLine = () => document.querySelector(".call-status");
const startCall = async (user, messages = en) => {
  await user.click(await screen.findByRole("button", { name: messages["voice.start"] }));
  await screen.findByText(GREETING, { selector: "li" });
};
const submitEvents = [
  { type: "customer_text", text: "yes" },
  { type: "case_created", case_id: "V-0001" },
  { type: "agent_sentence", text: "Thank you.", lang: "en" },
  { type: "state", session: snapshot({ state: "SUBMITTED", case_id: "V-0001", transcript: said(GREETING, "Thank you.") }) },
  { type: "done" },
];
const typeAndSend = async (user, messages = en, text = "yes") => {
  await user.type(screen.getByLabelText(messages["voice.type.label"]), text);
  await user.click(screen.getByRole("button", { name: messages["voice.send"] }));
};

describe("the call status tells the truth about the microphone", () => {
  it("shows Ready, not Listening, while the call is open and the microphone is off", async () => {
    const user = userEvent.setup();
    installFetch();
    render(<App />);
    await startCall(user);
    await waitFor(() => expect(statusLine()).toHaveTextContent("Ready"));
    expect(statusLine()).not.toHaveTextContent(/Listening/);
    expect(tracks).toHaveLength(0); // starting a call never opens the microphone
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
  });

  it("goes Ready, Listening, Processing, Speaking, Ready, and Listening only while the microphone records", async () => {
    const user = userEvent.setup();
    let open;
    turn = new Promise((resolve) => {
      open = resolve;
    });
    installFetch({
      routes: {
        "POST /api/voice/sessions/s1/turn": () => stream([{ type: "agent_sentence", text: "Which order?", lang: "en" }, { type: "state", session: snapshot({ transcript: said(GREETING, "Which order?") }) }, { type: "done" }]),
      },
    });
    render(<App />);
    await startCall(user);
    await waitFor(() => expect(statusLine()).toHaveTextContent("Ready"));

    await user.click(screen.getByRole("button", { name: en["voice.mic.start"] }));
    await waitFor(() => expect(statusLine()).toHaveTextContent("Listening"));
    expect(tracks).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: en["voice.mic.stop"] }));
    await waitFor(() => expect(statusLine()).toHaveTextContent("Processing"));
    expect(tracks[0].stop).toHaveBeenCalled(); // the microphone is released as soon as recording stops

    gate.hold = true; // the speaker is busy once Cosmo's reply arrives
    open();
    await waitFor(() => expect(statusLine()).toHaveTextContent("Speaking"));
    gate.release();
    await waitFor(() => expect(statusLine()).toHaveTextContent("Ready"));
    expect(statusLine()).not.toHaveTextContent(/Speaking|Listening|Processing/);
  });

  it("shows Waiting for specialist once the request is with the team, and Call ended after End call", async () => {
    const user = userEvent.setup();
    installFetch({ routes: { "POST /api/voice/sessions/s1/turn": () => stream(submitEvents) } });
    render(<App />);
    await startCall(user);
    await typeAndSend(user);
    await waitFor(() => expect(statusLine()).toHaveTextContent("Waiting for specialist"));
    expect(statusLine()).not.toHaveTextContent(/Ready|Listening|Resolved/);
    await user.click(screen.getByRole("button", { name: en["voice.endCall"] }));
    await waitFor(() => expect(statusLine()).toHaveTextContent("Call ended"));
  });

  it.each([
    ["en", en, "Ready", "Waiting for specialist"],
    ["es", es, "Lista", "Esperando al especialista"],
    ["pt", pt, "Pronto", "Aguardando o especialista"],
    ["hi", hi, "तैयार", "विशेषज्ञ की प्रतीक्षा"],
  ])("the labels are localized in %s", async (code, messages, ready, waiting) => {
    const user = userEvent.setup();
    expect(messages["voice.phase.listening"]).toBe(ready);
    expect(messages["voice.phase.waiting"]).toBe(waiting);
    installFetch({ routes: { "POST /api/voice/sessions/s1/turn": () => stream(submitEvents) } });
    render(<App initialLanguage={code} />);
    await user.click(await screen.findByRole("button", { name: messages["voice.start"] }));
    await waitFor(() => expect(statusLine()).toHaveTextContent(ready));
    expect(statusLine()).not.toHaveTextContent(messages["voice.phase.recording"]);
    await typeAndSend(user, messages);
    await waitFor(() => expect(statusLine()).toHaveTextContent(waiting));
  });
});

describe("the verified resolution, in the customer's language", () => {
  const outcomeSnapshot = (language) =>
    snapshot({
      language,
      state: "CLOSED",
      case_id: "V-0001",
      outcome: { status: "APPROVED", decision: "REPLACE", text: "Good news." },
      transcript: [...said(GREETING, "Thank you."), { role: "agent", text: PENDING_DRAFT, note: true }],
    });

  async function reachResolved(user, language = "en", messages = en) {
    verified = "RESOLVED";
    installFetch({
      outcomeEvents: [
        { type: "agent_sentence", text: "Good news.", lang: language },
        { type: "agent_text", text: PENDING_DRAFT, lang: "en" },
        { type: "state", session: outcomeSnapshot(language) },
        { type: "done" },
      ],
      routes: {
        "POST /api/voice/sessions/s1/turn": () => stream(submitEvents),
        "GET /api/voice/sessions/s1": () => json(outcomeSnapshot(language)),
      },
    });
    render(<App initialLanguage={language} />);
    await user.click(await screen.findByRole("button", { name: messages["voice.start"] }));
    await screen.findByText(GREETING, { selector: "li" });
    await typeAndSend(user, messages);
    await waitFor(() => expect(statusLine()).toHaveTextContent(messages["voice.phase.resolved"]), { timeout: 6000 });
  }

  it("shows Resolved, a Spanish summary in the transcript, and the original message untouched and collapsed", async () => {
    const user = userEvent.setup();
    await reachResolved(user, "es", es);
    const transcript = document.querySelector(".call-transcript");
    expect(transcript).toHaveTextContent(es["voice.who.summary"]);
    expect(transcript).toHaveTextContent(es["track.summary.REPLACE"].replace("{product}", "Smart Plug Mini"));
    expect(transcript).not.toHaveTextContent(es["voice.who.note"]); // a summary is never labelled as the approved message
    const original = transcript.querySelector("details.original-message p");
    expect(original.textContent).toBe(PENDING_DRAFT);
    expect(screen.getAllByText(es["track.original"]).length).toBeGreaterThan(0);
    // the tracker below the call shows the same verified outcome, not the English draft as its resolution
    expect(document.querySelector(".tracker-decision")).toHaveTextContent(es["track.summary.REPLACE"].replace("{product}", "Smart Plug Mini"));
  }, 15000);

  it("switching the page language after the resolution updates the summary, not the stored message", async () => {
    const user = userEvent.setup();
    await reachResolved(user, "es", es);
    await user.selectOptions(screen.getByRole("combobox"), "hi");
    const transcript = document.querySelector(".call-transcript");
    await waitFor(() => expect(transcript).toHaveTextContent(hi["track.summary.REPLACE"].replace("{product}", "Smart Plug Mini")));
    expect(transcript).toHaveTextContent(hi["voice.who.summary"]);
    expect(transcript.querySelector("details.original-message p").textContent).toBe(PENDING_DRAFT);
    expect(statusLine()).toHaveTextContent(hi["voice.phase.resolved"]);
  }, 15000);

  it("a new call does not show the last call's case as its own", async () => {
    const user = userEvent.setup();
    await reachResolved(user);
    expect(document.querySelector(".tracker")).not.toBeNull();
    await user.click(screen.getByRole("button", { name: en["voice.newCall"] }));
    expect(document.querySelector(".tracker")).toBeNull(); // nothing to show until this call creates a case
    await user.click(screen.getByRole("button", { name: en["voice.start"] }));
    await screen.findByText(GREETING, { selector: "li" });
    expect(document.querySelector(".tracker")).toBeNull();
    expect(screen.queryByText("Resolved", { selector: ".status-badge" })).not.toBeInTheDocument();
  }, 15000);
});

describe("the Cosmic Mart brand", () => {
  const brand = () => screen.getByRole("button", { name: en["brand.home"] });

  it("is a labelled, keyboard-operable control that returns a signed-in customer to the support options and keeps the session", async () => {
    const user = userEvent.setup();
    installFetch();
    render(<App />);
    await screen.findByRole("heading", { name: en["voice.title"] });
    expect(brand()).toHaveTextContent("Cosmic Mart");
    brand().focus();
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("heading", { name: /Jon/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: new RegExp(en["home.voice.title"]) })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: new RegExp(en["home.form.title"]) })).toBeInTheDocument();
    expect(screen.getByText(en["account.signedInAs"].replace("{name}", "Jon"))).toBeInTheDocument(); // still signed in
    expect(brand().closest("a")).toBeNull(); // not a link to anywhere else, and never the employee dashboard
    expect(window.location.pathname).not.toMatch(/internal/);
    brand().focus();
    await user.keyboard(" "); // Space also activates it, from the home page as well
    expect(await screen.findByRole("heading", { name: /Jon/ })).toBeInTheDocument();
  });

  it("goes to the sign-in screen when nobody is signed in", async () => {
    const user = userEvent.setup();
    installFetch();
    render(<SupportPage />);
    await screen.findByLabelText(en["identify.name"]);
    await user.click(brand());
    expect(screen.getByLabelText(en["identify.name"])).toBeInTheDocument();
  });

  it("stops a recording in progress instead of navigating away while it continues", async () => {
    const user = userEvent.setup();
    installFetch();
    render(<App />);
    await startCall(user);
    await waitFor(() => expect(statusLine()).toHaveTextContent("Ready"));
    await user.click(screen.getByRole("button", { name: en["voice.mic.start"] }));
    await waitFor(() => expect(statusLine()).toHaveTextContent("Listening"));
    expect(tracks[0].stop).not.toHaveBeenCalled();
    await user.click(brand());
    await screen.findByRole("heading", { name: /Jon/ });
    expect(tracks[0].stop).toHaveBeenCalled();
  });

  it("keeps what was typed in the support form when the customer goes home and comes back", async () => {
    const user = userEvent.setup();
    installFetch({
      routes: {
        "GET /api/support/my/orders": () =>
          json([{ order_reference: "O-1002", product_name: "Smart Plug Mini", order_date: "2026-10-19", price: 45, delivery_summary: "x", delivery_status: "LOST_IN_TRANSIT", eligible_issue_types: ["LATE_OR_MISSING"] }]),
      },
    });
    render(<SupportPage initialSession={SESSION} initialView="form" />);
    await user.click(await screen.findByRole("radio", { name: /Smart Plug Mini/ }));
    await user.click(screen.getByRole("button", { name: en["actions.continue"] }));
    await user.click(await screen.findByRole("radio", { name: new RegExp(en["issue.LATE_OR_MISSING.label"]) }));
    await user.click(screen.getByRole("button", { name: en["actions.continue"] }));
    const box = await screen.findByRole("textbox");
    await user.type(box, "My plug never arrived");
    await user.click(brand());
    await screen.findByRole("heading", { name: /Jon/ });
    await user.click(screen.getByRole("button", { name: new RegExp(en["home.form.title"]) }));
    expect(await screen.findByRole("textbox")).toHaveValue("My plug never arrived");
  });
});
