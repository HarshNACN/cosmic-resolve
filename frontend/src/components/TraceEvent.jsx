import Disclosure from "./Disclosure.jsx";
import { asText, classifyEvent, formatTimestamp } from "../format.js";

// Fields that hold full prompts and model replies (backend "model_exchange" events). Each gets its own
// collapsed section so nothing large is shown until requested.
const LARGE_FIELDS = [
  ["system_prompt", "System prompt"],
  ["user_message", "User message"],
  ["response", "Model response"],
];

export default function TraceEvent({ event }) {
  const { category, label, status } = classifyEvent(event.event_type);
  const details = event.details || {};
  const provider = typeof details.model_id === "string" ? details.model_id : null;

  const large = LARGE_FIELDS.filter(([key]) => key in details);
  const rest = Object.fromEntries(Object.entries(details).filter(([key]) => !LARGE_FIELDS.some(([name]) => name === key)));
  const hasRest = Object.keys(rest).length > 0;

  return (
    <li className={`trace-event trace-${category}`}>
      <div className="trace-head">
        <span className="trace-label">{label}</span>
        {status ? <span className="trace-status">{status}</span> : null}
        <time className="trace-time">{formatTimestamp(event.timestamp)}</time>
      </div>
      <p className="trace-message">{typeof event.message === "string" && event.message ? event.message : event.event_type}</p>
      <p className="muted trace-meta">
        <code>{event.event_type}</code>
        {provider ? <> &middot; model: {provider}</> : null}
      </p>
      {hasRest ? (
        <Disclosure title="Details">
          <pre className="code-block">{asText(rest)}</pre>
        </Disclosure>
      ) : null}
      {large.map(([key, title]) => (
        <Disclosure key={key} title={title}>
          <pre className="code-block">{asText(details[key])}</pre>
        </Disclosure>
      ))}
    </li>
  );
}
