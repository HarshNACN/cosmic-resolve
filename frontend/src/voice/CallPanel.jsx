import { useCallback, useEffect, useRef, useState } from "react";
import HeadsetAvatar, { PHASE_LABELS } from "./HeadsetAvatar.jsx";
import { useVoiceCall } from "./useVoiceCall.js";
import { fetchCallers } from "./voiceApi.js";
import { VoiceNotice, defaultFormat, defaultT } from "./voiceUi.jsx";
import "./voice.css";

// Step labels: [translation key, English text].
const STEPS = [
  ["voice.step.gather", "Gather details"],
  ["voice.step.confirm", "Confirm"],
  ["voice.step.review", "Specialist review"],
  ["voice.step.resolved", "Resolved"],
];
const TALKING_PHASES = new Set(["listening", "speaking", "waiting", "recording"]);
const LANGUAGE_PHASES = new Set(["listening", "speaking", "waiting"]); // the phases in which the call can take a language change
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

// The one phase shown to the customer. The call's phases are already mutually exclusive (ended, resolved, recording,
// speaking, thinking, waiting, ready, in that order of priority); this only stops "Ready" from showing when the
// session itself says the call is waiting on a specialist or is finished.
function displayPhase(phase, session) {
  if (phase !== "listening") return phase;
  if (session?.state === "SUBMITTED") return "waiting";
  if (session?.state === "CLOSED") return session.outcome ? "resolved" : "ended";
  return phase;
}

function MicIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2z" />
    </svg>
  );
}

// Says plainly what is missing when speech to text, the model, or the voice is not set up. The setup details are
// configuration messages for the person running the demo, so a customer-facing panel shows only the plain sentence.
function SetupNote({ capabilities, tr, showDetail }) {
  if (!capabilities || (capabilities.stt && capabilities.tts && capabilities.llm)) return null;
  return (
    <p className="muted">
      {tr("voice.setupPartial", "Voice is only partly set up")}
      {showDetail ? (capabilities.problems?.length ? `: ${capabilities.problems.join(" ")}` : ".") : null}
    </p>
  );
}

const LANGUAGE_LABELS = { en: "English", es: "Español", pt: "Português (Brasil)", hi: "Hindi — हिन्दी" };

// Shows which language the call is in, with a compact manual selector. Rendered only when multilingual calls are on,
// so with the feature off the panel looks exactly as before.
function LanguageControl({ capabilities, session, selected, onChange, disabled, tr }) {
  if (!capabilities?.multilingual) return null;
  const labels = { ...LANGUAGE_LABELS, ...(capabilities.language_labels || {}) };
  const current = session?.language || selected;
  return (
    <div className="language-control">
      <span className="tag" data-testid="language-indicator" aria-live="polite">
        {labels[current] || labels.en}
      </span>
      <label className="visually-hidden" htmlFor="language-select">
        {tr("voice.languageLabel", "Call language")}
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

function micLabel(phase, tr) {
  if (phase === "recording") return tr("voice.mic.stop", "Stop recording and send");
  if (phase === "speaking") return tr("voice.mic.interrupt", "Interrupt and speak");
  if (TALKING_PHASES.has(phase)) return tr("voice.mic.start", "Start speaking");
  return tr("voice.mic.unavailable", "Microphone unavailable right now");
}

// The call panel: tap the microphone (or type) and talk with the intake agent. When the customer confirms, the call
// becomes an ordinary case in the queue. Everything below the first block of props is optional; without it the panel is
// the internal one, with a "Who is calling?" picker and English text.
//
// A host page can mount it for a signed-in customer:
//   customer           { firstName, getAuthHeaders }  no caller picker and no callers list; the call starts from the
//                      customer's own session token, sent in a header on the one request that opens the call (the
//                      token is only ever passed in here, never stored globally, and no customer id is sent)
//   t(key, fallback, params)  translates the panel's text; format { orderRef, price, status } writes order cards
//   language           asks the call to switch to that language; onLanguageChange(language, source) reports every
//                      language the call changes to, so the host's own language stays in step
//   hideLanguageSelector  the host has its own single selector
//   onCallReset()      a call ended or a new one is starting, so anything the host keeps about the last call is stale
//   renderNote(line)   how the host shows the approved-message line; return null to use the default
export default function CallPanel({ onCaseCreated, onCallReset, renderNote, language, onLanguageChange, customer, t, format, hideLanguageSelector = false }) {
  const tr = t ?? defaultT;
  const fmt = { ...defaultFormat, ...(format || {}) };
  const customerMode = Boolean(customer);
  const call = useVoiceCall({ onCaseCreated, onLanguageChange, t: tr, getAuthHeaders: customer?.getAuthHeaders });
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
  // A signed-in customer never loads the list of callers: there is nobody to pick.
  useEffect(() => {
    if (!customerMode) loadCallers();
  }, [customerMode, loadCallers]);

  // The host's language, pushed to the call once. It is not pushed again while the call is catching up, so the call's
  // own `language` event (which the host also hears) cannot start a second request. Before a call exists it only sets
  // the language the call will start in.
  const requestedLanguage = useRef(null);
  const sessionLanguage = session?.language;
  const changeLanguage = call.changeLanguage;
  useEffect(() => {
    if (language && !session) changeLanguage(language);
  }, [language, session, changeLanguage]);
  useEffect(() => {
    if (!language || !sessionLanguage) return;
    if (sessionLanguage === language) {
      requestedLanguage.current = null;
      return;
    }
    if (requestedLanguage.current === language || !LANGUAGE_PHASES.has(phase)) return;
    requestedLanguage.current = language;
    changeLanguage(language);
  }, [language, sessionLanguage, phase, changeLanguage]);

  const lineCount = session?.transcript?.length ?? 0;
  useEffect(() => {
    transcriptEnd.current?.scrollIntoView?.({ block: "nearest" });
  }, [lineCount]);

  const live = LIVE_PHASES.has(phase);
  const finished = phase === "resolved" || phase === "ended";
  const canTalk = TALKING_PHASES.has(phase);
  const step = currentStep(session);
  const shown = displayPhase(phase, session);
  const startCall = (id) => {
    onCallReset?.();
    call.startCall(id);
  };
  const resetCall = () => {
    onCallReset?.();
    call.resetCall();
  };

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
        <h2 id="call-heading">{tr("voice.title", "Customer voice call")}</h2>
        {session && !customerMode ? <span className="tag">{tr("voice.caller", "Caller: {name}", { name: session.customer.first_name })}</span> : null}
        {hideLanguageSelector ? null : (
          <LanguageControl
            capabilities={call.capabilities}
            session={session}
            selected={preferred}
            tr={tr}
            disabled={phase === "connecting" || phase === "recording" || phase === "thinking" || finished}
            onChange={(next) => {
              setPreferred(next);
              call.changeLanguage(next);
            }}
          />
        )}
      </div>

      {phase === "idle" ? (
        <>
          {customerMode ? (
            <div className="caller-picker">
              <button type="button" className="button button-primary" onClick={() => startCall(null)}>
                {tr("voice.start", "Start call")}
              </button>
            </div>
          ) : callers.status === "error" ? (
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
                      {caller.name} ({defaultFormat.status(caller.tier)}, {caller.orders} orders)
                    </option>
                  ))}
                </select>
              </div>
              <button type="button" className="button button-primary" disabled={!callerId} onClick={() => startCall(callerId)}>
                {tr("voice.start", "Start call")}
              </button>
            </div>
          )}
          <p className="muted">{tr("voice.startHint", "Press Start call, then tap the microphone and speak, or type if you prefer.")}</p>
          <SetupNote capabilities={call.capabilities} tr={tr} showDetail={!customerMode} />
          {call.notice ? <VoiceNotice title={tr("voice.startFailed", "The call could not start.")} detail={call.notice} /> : null}
        </>
      ) : (
        <div className="call-body">
          <div className="call-agent">
            <HeadsetAvatar phase={shown} level={call.level} t={tr} />
            <p className="call-status" role="status" aria-live="polite">
              {tr(`voice.phase.${shown}`, PHASE_LABELS[shown])}
            </p>
          </div>

          <div className="call-main">
            <ol className="call-stepper" aria-label={tr("voice.progress", "Call progress")}>
              {STEPS.map(([key, label], index) => (
                <li key={key} aria-current={index === step ? "step" : undefined} data-done={index < step ? "true" : undefined}>
                  {tr(key, label)}
                </li>
              ))}
            </ol>

            {session?.state === "PICK_ORDER" && session.orders?.length ? (
              <ul className="order-cards" aria-label={tr("voice.orders", "Recent orders. Tap one to choose it.")}>
                {session.orders.map((order) => (
                  <li key={order.order_id}>
                    <button type="button" className="order-card" disabled={!canTalk || phase === "recording"} onClick={() => call.chooseOrder(order.order_id)}>
                      <span>{order.title}</span>
                      <span className="meta">
                        {fmt.orderRef(order.order_id)} · {fmt.price(order.price)} · {fmt.status(order.delivery_status)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}

            <ol className="call-transcript" aria-label={tr("voice.transcript", "Call transcript")}>
              {(session?.transcript || []).map((line, index) => {
                const custom = line.note && renderNote ? renderNote(line) : null;
                if (custom) return <li key={`${index}-${line.role}`}>{custom}</li>;
                return (
                <li key={`${index}-${line.role}`}>
                  <span className={line.role === "agent" ? "who who-agent" : "who"}>
                    {line.role === "agent"
                      ? line.note
                        ? tr("voice.who.note", "Cosmo (approved message)")
                        : tr("voice.who.agent", "Cosmo")
                      : tr("voice.who.customer", "Customer")}
                  </span>
                  {line.text}
                </li>
                );
              })}
              <li ref={transcriptEnd} aria-hidden="true" />
            </ol>

            <SetupNote capabilities={call.capabilities} tr={tr} showDetail={!customerMode} />
            {call.missingVoice ? (
              <p className="muted" role="status">
                {customerMode
                  ? tr("voice.missingVoice", "Cosmo is replying in text because no {language} voice is available.", { language: call.missingVoice })
                  : `No ${call.missingVoice} voice is installed, so Cosmo is replying in text only. See docs/VOICE.md to add it.`}
              </p>
            ) : null}
            {call.notice ? <VoiceNotice title={tr("voice.problem", "Call problem")} detail={call.notice} /> : null}

            <div className="call-controls">
              <button
                type="button"
                className="mic-button"
                aria-label={micLabel(phase, tr)}
                aria-pressed={phase === "recording"}
                disabled={!canTalk}
                onClick={call.toggleMic}
              >
                <MicIcon />
              </button>
              <form className="call-text-form" onSubmit={submitTyped}>
                <input
                  type="text"
                  aria-label={tr("voice.type.label", "Type a reply to the agent")}
                  placeholder={tr("voice.type.placeholder", "Or type your reply")}
                  value={typed}
                  maxLength={500}
                  onChange={(event) => setTyped(event.target.value)}
                  disabled={!canTalk || phase === "recording"}
                />
                <button type="submit" className="button" disabled={!typed.trim() || !canTalk || phase === "recording"}>
                  {tr("voice.send", "Send")}
                </button>
              </form>
              {finished ? (
                <button type="button" className="button button-primary" onClick={resetCall}>
                  {tr("voice.newCall", "New call")}
                </button>
              ) : (
                <button type="button" className="button button-negative" disabled={!live} onClick={call.endCall}>
                  {tr("voice.endCall", "End call")}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
