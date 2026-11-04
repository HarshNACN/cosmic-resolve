import { useCallback, useEffect, useRef, useState } from "react";
import ErrorNotice from "../components/ErrorNotice.jsx";
import { formatUsd, humanize } from "../format.js";
import HeadsetAvatar, { PHASE_LABELS } from "./HeadsetAvatar.jsx";
import { useVoiceCall } from "./useVoiceCall.js";
import { fetchCallers } from "./voiceApi.js";
import "./voice.css";

const STEPS = ["Gather details", "Confirm", "Specialist review", "Resolved"];
const TALKING_PHASES = new Set(["listening", "speaking", "waiting", "recording"]);
const LIVE_PHASES = new Set(["connecting", "listening", "recording", "thinking", "speaking", "waiting"]);

function currentStep(session) {
  switch (session?.state) {
    case "PICK_ORDER":
    case "DESCRIBE":
      return 0;
    case "CONFIRM":
      return 1;
    case "SUBMITTED":
      return 2;
    case "CLOSED":
      return session.outcome ? 3 : -1;
    default:
      return -1;
  }
}

function MicIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2z" />
    </svg>
  );
}

// Says plainly what is missing when speech to text, the model, or the voice is not set up.
function SetupNote({ capabilities }) {
  if (!capabilities || (capabilities.stt && capabilities.tts && capabilities.llm)) return null;
  return (
    <p className="muted">
      Voice is only partly set up
      {capabilities.problems?.length ? `: ${capabilities.problems.join(" ")}` : "."}
    </p>
  );
}

const LANGUAGE_LABELS = { en: "English", es: "Español", pt: "Português (Brasil)" };

// Shows which language the call is in, with a compact manual selector. Rendered only when multilingual calls are on,
// so with the feature off the panel looks exactly as before.
function LanguageControl({ capabilities, session, selected, onChange, disabled }) {
  if (!capabilities?.multilingual) return null;
  const labels = { ...LANGUAGE_LABELS, ...(capabilities.language_labels || {}) };
  const current = session?.language || selected;
  return (
    <div className="language-control">
      <span className="tag" data-testid="language-indicator" aria-live="polite">
        {labels[current] || labels.en}
      </span>
      <label className="visually-hidden" htmlFor="language-select">
        Call language
      </label>
      <select id="language-select" value={current} disabled={disabled} onChange={(event) => onChange(event.target.value)}>
        {Object.keys(LANGUAGE_LABELS).map((code) => (
          <option key={code} value={code}>
            {labels[code]}
            {capabilities.languages && capabilities.languages[code] === false ? " (text only)" : ""}
          </option>
        ))}
      </select>
    </div>
  );
}

function micLabel(phase) {
  if (phase === "recording") return "Stop recording and send";
  if (phase === "speaking") return "Interrupt and speak";
  if (TALKING_PHASES.has(phase)) return "Start speaking";
  return "Microphone unavailable right now";
}

// The customer side of the demo, shown above the case being worked: pick who is calling, tap the microphone, and
// talk with the intake agent. When the customer confirms, the call becomes an ordinary case in the queue.
export default function CallPanel({ onCaseCreated }) {
  const call = useVoiceCall({ onCaseCreated });
  const { phase, session } = call;
  const [callers, setCallers] = useState({ status: "loading", items: [], error: null });
  const [callerId, setCallerId] = useState("");
  const [typed, setTyped] = useState("");
  const [preferred, setPreferred] = useState("en");
  const transcriptEnd = useRef(null);

  const loadCallers = useCallback(() => {
    setCallers({ status: "loading", items: [], error: null });
    fetchCallers()
      .then(({ callers: items }) => {
        setCallers({ status: "ready", items: Array.isArray(items) ? items : [], error: null });
        setCallerId((current) => current || (items?.[0]?.customer_id ?? ""));
      })
      .catch((error) => setCallers({ status: "error", items: [], error: error.message }));
  }, []);
  useEffect(loadCallers, [loadCallers]);

  const lineCount = session?.transcript?.length ?? 0;
  useEffect(() => {
    transcriptEnd.current?.scrollIntoView?.({ block: "nearest" });
  }, [lineCount]);

  const live = LIVE_PHASES.has(phase);
  const finished = phase === "resolved" || phase === "ended";
  const canTalk = TALKING_PHASES.has(phase);
  const step = currentStep(session);

  const submitTyped = (event) => {
    event.preventDefault();
    const text = typed.trim();
    if (!text || !canTalk || phase === "recording") return;
    setTyped("");
    call.sendText(text);
  };

  return (
    <section className="panel call-panel" aria-labelledby="call-heading">
      <div className="call-head">
        <h2 id="call-heading">Customer voice call</h2>
        {session ? <span className="tag">Caller: {session.customer.first_name}</span> : null}
        <LanguageControl
          capabilities={call.capabilities}
          session={session}
          selected={preferred}
          disabled={phase === "connecting" || phase === "recording" || phase === "thinking" || finished}
          onChange={(language) => {
            setPreferred(language);
            call.changeLanguage(language);
          }}
        />
      </div>

      {phase === "idle" ? (
        <>
          {callers.status === "error" ? (
            <div className="caller-picker">
              <p className="muted" role="status">
                Voice callers could not be loaded. {callers.error}
              </p>
              <button type="button" className="button" onClick={loadCallers}>
                Reload callers
              </button>
            </div>
          ) : (
            <div className="caller-picker">
              <div className="field">
                <label htmlFor="caller-select">Who is calling?</label>
                <select
                  id="caller-select"
                  value={callerId}
                  onChange={(event) => setCallerId(event.target.value)}
                  disabled={callers.status !== "ready" || callers.items.length === 0}
                >
                  {callers.items.map((caller) => (
                    <option key={caller.customer_id} value={caller.customer_id}>
                      {caller.name} ({humanize(caller.tier)}, {caller.orders} orders)
                    </option>
                  ))}
                </select>
              </div>
              <button type="button" className="button button-primary" disabled={!callerId} onClick={() => call.startCall(callerId)}>
                Start call
              </button>
            </div>
          )}
          <p className="muted">Press Start call, then tap the microphone and speak, or type if you prefer.</p>
          <SetupNote capabilities={call.capabilities} />
          {call.notice ? <ErrorNotice title="The call could not start." detail={call.notice} /> : null}
        </>
      ) : (
        <div className="call-body">
          <div className="call-agent">
            <HeadsetAvatar phase={phase} level={call.level} />
            <p className="call-status" role="status" aria-live="polite">
              {PHASE_LABELS[phase]}
            </p>
          </div>

          <div className="call-main">
            <ol className="call-stepper" aria-label="Call progress">
              {STEPS.map((label, index) => (
                <li key={label} aria-current={index === step ? "step" : undefined} data-done={index < step ? "true" : undefined}>
                  {label}
                </li>
              ))}
            </ol>

            {session?.state === "PICK_ORDER" && session.orders?.length ? (
              <ul className="order-cards" aria-label="Recent orders. Tap one to choose it.">
                {session.orders.map((order) => (
                  <li key={order.order_id}>
                    <button type="button" className="order-card" disabled={!canTalk || phase === "recording"} onClick={() => call.chooseOrder(order.order_id)}>
                      <span>{order.title}</span>
                      <span className="meta">
                        {order.order_id} · {formatUsd(order.price)} · {humanize(order.delivery_status)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}

            <ol className="call-transcript" aria-label="Call transcript">
              {(session?.transcript || []).map((line, index) => (
                <li key={`${index}-${line.role}`}>
                  <span className={line.role === "agent" ? "who who-agent" : "who"}>
                    {line.role === "agent" ? (line.note ? "Cosmo (approved message)" : "Cosmo") : "Customer"}
                  </span>
                  {line.text}
                </li>
              ))}
              <li ref={transcriptEnd} aria-hidden="true" />
            </ol>

            <SetupNote capabilities={call.capabilities} />
            {call.missingVoice ? (
              <p className="muted" role="status">
                No {call.missingVoice} voice is installed, so Cosmo is replying in text only. See docs/VOICE.md to add it.
              </p>
            ) : null}
            {call.notice ? <ErrorNotice title="Call problem" detail={call.notice} /> : null}

            <div className="call-controls">
              <button
                type="button"
                className="mic-button"
                aria-label={micLabel(phase)}
                aria-pressed={phase === "recording"}
                disabled={!canTalk}
                onClick={call.toggleMic}
              >
                <MicIcon />
              </button>
              <form className="call-text-form" onSubmit={submitTyped}>
                <input
                  type="text"
                  aria-label="Type a reply to the agent"
                  placeholder="Or type your reply"
                  value={typed}
                  maxLength={500}
                  onChange={(event) => setTyped(event.target.value)}
                  disabled={!canTalk || phase === "recording"}
                />
                <button type="submit" className="button" disabled={!typed.trim() || !canTalk || phase === "recording"}>
                  Send
                </button>
              </form>
              {finished ? (
                <button type="button" className="button button-primary" onClick={call.resetCall}>
                  New call
                </button>
              ) : (
                <button type="button" className="button button-negative" disabled={!live} onClick={call.endCall}>
                  End call
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
