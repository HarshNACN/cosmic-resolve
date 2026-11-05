import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App.jsx";
import CallPanel from "../voice/CallPanel.jsx";

// A stand-in for the browser speaker: records what would be played and lets a test hold the "still talking" state.
const speaker = vi.hoisted(() => ({ instances: [], hold: false, gate: null }));
vi.mock("../voice/pcmPlayer.js", () => ({
  PcmPlayer: class {
    constructor(options) {
      this.options = options;
      this.enqueued = [];
      this.stopped = 0;
      speaker.instances.push(this);
    }
    async unlock() {
      return true;
    }
    enqueue(pcm, rate) {
      this.enqueued.push([pcm, rate]);
    }
    stop() {
      this.stopped += 1;
    }
    whenIdle() {
      return speaker.hold ? speaker.gate : Promise.resolve();
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

const ORDERS = [
  { order_id: "O-1002", title: "Smart Plug Mini", price: 45, order_date: "2026-10-19", delivery_status: "LOST_IN_TRANSIT" },
  { order_id: "O-1301", title: "GPS Luggage Tag", price: 29, order_date: "2026-10-11", delivery_status: "DELIVERED" },
];
const snapshot = (overrides = {}) => ({
  session_id: "s1",
  customer: { customer_id: "C-002", first_name: "Jon" },
  state: "PICK_ORDER",
  orders: ORDERS,
  selected_order_id: null,
  case_id: null,
  transcript: [],
  outcome: null,
  ...overrides,
});
const agentLine = (text) => ({ type: "agent_sentence", text });
const GREETING = "Hi Jon, this is Cosmo from Cosmic Mart. Which order can I help you with?";
const greetingEvents = () => [
  agentLine(GREETING),
  { type: "audio", rate: 22050, pcm: "AAAA" },
  { type: "state", session: snapshot({ transcript: [{ role: "agent", text: GREETING }] }) },
  { type: "done" },
];
const CALLERS = { callers: [{ customer_id: "C-002", name: "Jon Park", tier: "SILVER", orders: 5 }] };

const controls = { audioBytes: 4000, micDenied: false };
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
    this.ondataavailable?.({ data: new Blob([new Uint8Array(controls.audioBytes)]) });
    this.onstop?.();
  }
}

let calls;
let routes;
function installFetch(extra = {}) {
  calls = [];
  routes = {
    "GET /api/voice/callers": () => json(CALLERS),
    "POST /api/voice/warmup": () => json({ llm: true, stt: true, tts: true, problems: [], agent: "Cosmo" }),
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
const turnCalls = () => calls.filter((call) => call.key === "POST /api/voice/sessions/s1/turn");

beforeEach(() => {
  speaker.instances.length = 0;
  speaker.hold = false;
  controls.audioBytes = 4000;
  vi.stubGlobal("MediaRecorder", FakeRecorder);
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: vi.fn(async () => {
        if (controls.micDenied) throw new Error("denied");
        return { getTracks: () => [{ stop: vi.fn() }] };
      }),
    },
  });
  controls.micDenied = false;
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

async function startCall(user) {
  await user.click(await screen.findByRole("button", { name: "Start call" }));
  await screen.findByText(GREETING, { selector: "li" });
}

const avatar = () => screen.getByRole("img", { name: /Cosmo, the voice assistant/ });

describe("starting a call", () => {
  it("offers the demo cast, and shows the headset only once a call is live", async () => {
    const user = userEvent.setup();
    installFetch();
    render(<CallPanel />);
    expect(await screen.findByRole("option", { name: /Jon Park \(Silver, 5 orders\)/ })).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /voice assistant/ })).not.toBeInTheDocument();

    await startCall(user);
    expect(avatar()).toHaveAccessibleName(/Cosmo, the voice assistant\. /);
  });

  it("warms up, opens the session, speaks the greeting, then listens", async () => {
    const user = userEvent.setup();
    installFetch();
    render(<CallPanel />);
    await startCall(user);

    // The warm-up happened when the page opened; starting the call reuses it instead of waiting again.
    expect(calls.map((c) => c.key)).toEqual([
      "POST /api/voice/warmup",
      "GET /api/voice/callers",
      "POST /api/voice/sessions",
      "POST /api/voice/sessions/s1/speak",
    ]);
    expect(JSON.parse(calls[2].init.body)).toEqual({ customer_id: "C-002" });
    expect(JSON.parse(calls[3].init.body)).toEqual({ kind: "greeting" });
    expect(speaker.instances[0].enqueued).toEqual([["AAAA", 22050]]);
    await waitFor(() => expect(avatar()).toHaveAttribute("data-state", "listening"));
    expect(screen.getByRole("status")).toHaveTextContent("Ready");
    expect(screen.getByRole("button", { name: "Start speaking" })).toBeEnabled();
  });

  it("warms up when the page opens, and retries at call time if that warm-up failed", async () => {
    const user = userEvent.setup();
    let attempts = 0;
    installFetch({
      "POST /api/voice/warmup": () =>
        ++attempts === 1
          ? json({ detail: "not ready" }, 503)
          : json({ llm: true, stt: true, tts: true, problems: [], agent: "Cosmo" }),
    });
    render(<CallPanel />);
    await waitFor(() => expect(attempts).toBe(1)); // at page load, before anyone presses Start call
    await startCall(user);
    expect(attempts).toBe(2);
  });

  it("shows the recent orders as tappable cards and the progress steps", async () => {
    const user = userEvent.setup();
    installFetch();
    render(<CallPanel />);
    await startCall(user);
    const cards = screen.getByRole("list", { name: /Recent orders/ });
    expect(within(cards).getByRole("button", { name: /Smart Plug Mini/ })).toBeInTheDocument();
    expect(within(cards).getByText(/O-1002 · \$45\.00 · Lost in transit/)).toBeInTheDocument();
    expect(screen.getByText("Gather details")).toHaveAttribute("aria-current", "step");
  });

  it("explains a start-up failure and stays ready to try again", async () => {
    const user = userEvent.setup();
    installFetch({ "POST /api/voice/sessions": () => json({ detail: "This customer has no orders to talk about." }, 409) });
    render(<CallPanel />);
    await user.click(await screen.findByRole("button", { name: "Start call" }));
    expect(await screen.findByText("This customer has no orders to talk about.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start call" })).toBeEnabled();
    expect(screen.queryByRole("img", { name: /voice assistant/ })).not.toBeInTheDocument();
  });

  it("does not break the page when the caller list cannot be loaded", async () => {
    installFetch({ "GET /api/voice/callers": () => json({ detail: "nope" }, 500) });
    render(<CallPanel />);
    expect(await screen.findByRole("button", { name: "Reload callers" })).toBeInTheDocument();
  });
});

describe("talking", () => {
  it("records on the first tap and sends the audio on the second", async () => {
    const user = userEvent.setup();
    installFetch({
      "POST /api/voice/sessions/s1/turn": () =>
        stream([
          { type: "customer_text", text: "The smart plug" },
          { type: "stage", stage: "thinking" },
          agentLine("Got it, the Smart Plug Mini. What has gone wrong with it?"),
          { type: "audio", rate: 22050, pcm: "BBBB" },
          { type: "state", session: snapshot({ state: "DESCRIBE", selected_order_id: "O-1002", transcript: [
            { role: "agent", text: GREETING },
            { role: "customer", text: "The smart plug" },
            { role: "agent", text: "Got it, the Smart Plug Mini. What has gone wrong with it?" },
          ] }) },
          { type: "done" },
        ]),
    });
    render(<CallPanel />);
    await startCall(user);
    await waitFor(() => expect(avatar()).toHaveAttribute("data-state", "listening"));

    await user.click(screen.getByRole("button", { name: "Start speaking" }));
    const stop = await screen.findByRole("button", { name: "Stop recording and send" });
    expect(stop).toHaveAttribute("aria-pressed", "true");
    expect(avatar()).toHaveAttribute("data-state", "recording");

    await user.click(stop);
    expect(await screen.findByText("Got it, the Smart Plug Mini. What has gone wrong with it?", { selector: "li" })).toBeInTheDocument();
    const [turn] = turnCalls();
    expect(turn.init.body.get("audio")).toBeInstanceOf(Blob);
    expect(turn.init.body.get("text")).toBeNull();
    expect(screen.getByText("The smart plug", { selector: "li" })).toBeInTheDocument();
    await waitFor(() => expect(avatar()).toHaveAttribute("data-state", "listening"));
    expect(speaker.instances[0].enqueued).toContainEqual(["BBBB", 22050]);
  });

  it("sends a tapped order card as an explicit choice", async () => {
    const user = userEvent.setup();
    installFetch({
      "POST /api/voice/sessions/s1/turn": () => stream([agentLine("Got it, the Smart Plug Mini."), { type: "done" }]),
    });
    render(<CallPanel />);
    await startCall(user);
    await waitFor(() => expect(avatar()).toHaveAttribute("data-state", "listening"));
    await user.click(within(screen.getByRole("list", { name: /Recent orders/ })).getByRole("button", { name: /Smart Plug Mini/ }));
    await screen.findByText("Got it, the Smart Plug Mini.", { selector: "li" });
    expect(turnCalls()[0].init.body.get("order_id")).toBe("O-1002");
  });

  it("sends typed replies as text and clears the box", async () => {
    const user = userEvent.setup();
    installFetch({
      "POST /api/voice/sessions/s1/turn": () => stream([agentLine("Sorry about that."), { type: "done" }]),
    });
    render(<CallPanel />);
    await startCall(user);
    await waitFor(() => expect(avatar()).toHaveAttribute("data-state", "listening"));
    const box = screen.getByRole("textbox", { name: "Type a reply to the agent" });
    await user.type(box, "the smart plug");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("Sorry about that.", { selector: "li" });
    expect(turnCalls()[0].init.body.get("text")).toBe("the smart plug");
    expect(box).toHaveValue("");
  });

  it("lets the customer interrupt the agent by tapping the microphone", async () => {
    const user = userEvent.setup();
    installFetch();
    let release;
    speaker.hold = true;
    speaker.gate = new Promise((resolve) => {
      release = resolve;
    });
    render(<CallPanel />);
    await user.click(await screen.findByRole("button", { name: "Start call" }));
    await screen.findByText(GREETING, { selector: "li" });
    expect(avatar()).toHaveAttribute("data-state", "speaking");

    await user.click(screen.getByRole("button", { name: "Interrupt and speak" }));
    expect(speaker.instances[0].stopped).toBe(1);
    expect(await screen.findByRole("button", { name: "Stop recording and send" })).toBeInTheDocument();
    release();
  });

  it("reports a blocked microphone and keeps the call usable", async () => {
    const user = userEvent.setup();
    installFetch();
    controls.micDenied = true;
    render(<CallPanel />);
    await startCall(user);
    await waitFor(() => expect(avatar()).toHaveAttribute("data-state", "listening"));
    await user.click(screen.getByRole("button", { name: "Start speaking" }));
    expect(await screen.findByText(/Microphone access was blocked/)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Type a reply to the agent" })).toBeEnabled();
  });

  it("ignores a stray tap that recorded almost nothing", async () => {
    const user = userEvent.setup();
    installFetch();
    controls.audioBytes = 100;
    render(<CallPanel />);
    await startCall(user);
    await waitFor(() => expect(avatar()).toHaveAttribute("data-state", "listening"));
    await user.click(screen.getByRole("button", { name: "Start speaking" }));
    await user.click(await screen.findByRole("button", { name: "Stop recording and send" }));
    expect(await screen.findByText(/too short to hear/)).toBeInTheDocument();
    expect(turnCalls()).toHaveLength(0);
  });

  it("shows a problem reported mid-turn without ending the call", async () => {
    const user = userEvent.setup();
    installFetch({
      "POST /api/voice/sessions/s1/turn": () =>
        stream([{ type: "error", message: "The speech service is busy. Please try again in a moment." }, { type: "done" }]),
    });
    render(<CallPanel />);
    await startCall(user);
    await waitFor(() => expect(avatar()).toHaveAttribute("data-state", "listening"));
    await user.type(screen.getByRole("textbox", { name: "Type a reply to the agent" }), "hello");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("The speech service is busy. Please try again in a moment.")).toBeInTheDocument();
    await waitFor(() => expect(avatar()).toHaveAttribute("data-state", "listening"));
  });

  it("reads lines with the browser voice when the server has no speech engine", async () => {
    const user = userEvent.setup();
    const speak = vi.fn();
    vi.stubGlobal("speechSynthesis", { speak, cancel: vi.fn() });
    vi.stubGlobal("SpeechSynthesisUtterance", class { constructor(text) { this.text = text; } });
    installFetch({
      "POST /api/voice/warmup": () => json({ llm: true, stt: true, tts: false, problems: ["Set PIPER_VOICE to a voice."], agent: "Cosmo" }),
      "POST /api/voice/sessions/s1/speak": () => stream([agentLine(GREETING), { type: "done" }]),
    });
    render(<CallPanel />);
    await startCall(user);
    expect(speak).toHaveBeenCalledTimes(1);
    expect(speak.mock.calls[0][0].text).toBe(GREETING);
    expect(await screen.findByText(/Voice is only partly set up: Set PIPER_VOICE/)).toBeInTheDocument();
  });
});

describe("ending and the hand-off to a specialist", () => {
  it("ends the call on request and offers a new one", async () => {
    const user = userEvent.setup();
    installFetch();
    render(<CallPanel />);
    await startCall(user);
    await waitFor(() => expect(avatar()).toHaveAttribute("data-state", "listening"));
    await user.click(screen.getByRole("button", { name: "End call" }));
    expect(avatar()).toHaveAttribute("data-state", "ended");
    expect(speaker.instances[0].stopped).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "New call" }));
    expect(screen.getByRole("button", { name: "Start call" })).toBeInTheDocument();
  });

  it("puts the case in the queue, waits on hold, then speaks the outcome and shows it resolved", async () => {
    const user = userEvent.setup();
    const onCaseCreated = vi.fn();
    const OUTCOME_TEXT = "Good news: a replacement is on its way.";
    const heldLines = [
      { role: "agent", text: GREETING },
      { role: "customer", text: "yes" },
      { role: "agent", text: "Thank you. I have sent this to a specialist." },
    ];
    const submitted = snapshot({ state: "SUBMITTED", case_id: "V-0001", selected_order_id: "O-1002", transcript: heldLines });
    const resolved = {
      ...submitted,
      state: "CLOSED",
      outcome: { status: "APPROVED", decision: "REPLACE", text: OUTCOME_TEXT },
      transcript: [...heldLines, { role: "agent", text: OUTCOME_TEXT }],
    };
    installFetch({
      "POST /api/voice/sessions/s1/turn": () =>
        stream([
          { type: "customer_text", text: "yes" },
          { type: "case_created", case_id: "V-0001" },
          agentLine("Thank you. I have sent this to a specialist."),
          { type: "state", session: submitted },
          { type: "done" },
        ]),
      // The associate has approved by the time the call polls: the session now reports an outcome.
      "GET /api/voice/sessions/s1": () => json(resolved),
      "POST /api/voice/sessions/s1/speak": (init) =>
        JSON.parse(init.body).kind === "greeting"
          ? stream(greetingEvents())
          : stream([
              agentLine(OUTCOME_TEXT),
              { type: "audio", rate: 22050, pcm: "CCCC" },
              { type: "state", session: resolved },
              { type: "done" },
            ]),
    });
    render(<CallPanel onCaseCreated={onCaseCreated} />);
    await startCall(user);
    await waitFor(() => expect(avatar()).toHaveAttribute("data-state", "listening"));

    await user.type(screen.getByRole("textbox", { name: "Type a reply to the agent" }), "yes");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(onCaseCreated).toHaveBeenCalledWith("V-0001"));
    await waitFor(() => expect(avatar()).toHaveAttribute("data-state", "waiting"));
    expect(screen.getByText("Specialist review")).toHaveAttribute("aria-current", "step");
    expect(screen.getByRole("status")).toHaveTextContent("Waiting for specialist");

    // The associate approves (the backend now reports an outcome); the next poll picks it up and the agent speaks.
    await waitFor(() => expect(screen.getByText(OUTCOME_TEXT, { selector: "li" })).toBeInTheDocument(), { timeout: 4000 });
    await waitFor(() => expect(avatar()).toHaveAttribute("data-state", "resolved"), { timeout: 4000 });
    expect(speaker.instances[0].enqueued).toContainEqual(["CCCC", 22050]);
    expect(within(screen.getByRole("list", { name: "Call progress" })).getByText("Resolved")).toHaveAttribute("aria-current", "step");
    expect(screen.getByRole("status")).toHaveTextContent("Resolved");
    expect(screen.getByRole("button", { name: "New call" })).toBeInTheDocument();
  }, 15000);
});

describe("the employee workbench no longer hosts the call", () => {
  const fixture = { case_id: "C-1001", order_id: "O-1001", customer_id: "C-001", tracking_id: "T-1001", case_type: "DAMAGED_ON_ARRIVAL", market: "US", category: "GADGETS", complaint_text: "Cracked housing.", channel: "EMAIL", created_at: "2026-11-02T09:00:00Z", status: "OPEN" };

  it("shows cases and approval controls only: no call panel, no caller picker, and no voice requests", async () => {
    installFetch({ "GET /api/cases": () => json([fixture]) });
    render(<App />);
    expect(await screen.findByRole("button", { name: /C-1001/ })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Customer voice call" })).not.toBeInTheDocument();
    expect(screen.queryByText("Who is calling?")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start call" })).not.toBeInTheDocument();
    expect(calls.some((call) => call.key.includes("/api/voice"))).toBe(false);
  });

  it("the panel still tells its host when a confirmed call has created a case (the customer page uses this)", async () => {
    const user = userEvent.setup();
    const onCaseCreated = vi.fn();
    installFetch({
      "POST /api/voice/sessions/s1/turn": () =>
        stream([{ type: "case_created", case_id: "V-0001" }, agentLine("Thank you."), { type: "state", session: snapshot({ state: "SUBMITTED", case_id: "V-0001" }) }, { type: "done" }]),
    });
    render(<CallPanel onCaseCreated={onCaseCreated} />);
    await user.click(await screen.findByRole("button", { name: "Start call" }));
    await screen.findByText(GREETING, { selector: "li" });
    await waitFor(() => expect(avatar()).toHaveAttribute("data-state", "listening"));
    await user.type(screen.getByRole("textbox", { name: "Type a reply to the agent" }), "yes");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(onCaseCreated).toHaveBeenCalledWith("V-0001"));
  });
});
