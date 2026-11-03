import Disclosure from "./Disclosure.jsx";
import ErrorNotice from "./ErrorNotice.jsx";
import { asText, formatShortDateTime, humanize } from "../format.js";

const NOT_AVAILABLE = "Not available";

const show = (value) => (typeof value === "string" && value !== "" ? value : NOT_AVAILABLE);

// One component, two sections. The summary (identity, metadata, customer statement) renders above the
// recommendation. The evidence (linked records) renders below it. Splitting them keeps the page order
// equal to the DOM order, so screen readers and sighted users follow the same sequence.
//
// The backend exposes only the case record. Customer, order, shipment and inventory details are not
// served by any endpoint, so only IDs are shown and the rest is marked unavailable.
export default function CaseDetails({ section, caseId, state, onRetry }) {
  if (section === "evidence") {
    if (!caseId || state.status !== "ready") return null;
    const record = state.data;
    return (
      <section className="panel case-evidence" aria-labelledby="evidence-heading">
        <div className="section-head">
          <h2 id="evidence-heading">Evidence</h2>
          <p className="muted">IDs only from this service</p>
        </div>
        <dl className="evidence-list">
          <div className="evidence-row">
            <dt>Customer</dt>
            <dd className="evidence-id">{show(record.customer_id)}</dd>
            <dd className="muted">History unavailable</dd>
          </div>
          <div className="evidence-row">
            <dt>Order</dt>
            <dd className="evidence-id">{show(record.order_id)}</dd>
            <dd className="muted">Details unavailable</dd>
          </div>
          <div className="evidence-row">
            <dt>Shipment</dt>
            <dd className="evidence-id">{show(record.tracking_id)}</dd>
            <dd className="muted">Delivery details unavailable</dd>
          </div>
          <div className="evidence-row">
            <dt>Inventory</dt>
            <dd className="evidence-id">{NOT_AVAILABLE}</dd>
            <dd className="muted">Availability unavailable</dd>
          </div>
        </dl>
      </section>
    );
  }

  if (!caseId) {
    return (
      <section className="panel case-summary" aria-labelledby="summary-heading">
        <div className="section-head">
          <h2 id="summary-heading">Case</h2>
        </div>
        <p className="muted">Select a case from the queue.</p>
      </section>
    );
  }

  if (state.status === "loading" || state.status === "idle") {
    return (
      <section className="panel case-summary" aria-labelledby="summary-heading" aria-busy="true">
        <div className="section-head">
          <h2 id="summary-heading">Case</h2>
        </div>
        <p role="status">Loading case...</p>
      </section>
    );
  }

  if (state.status === "error") {
    return (
      <section className="panel case-summary" aria-labelledby="summary-heading">
        <div className="section-head">
          <h2 id="summary-heading">Case</h2>
        </div>
        <ErrorNotice title="Unable to load this case." detail={state.error} onRetry={onRetry} />
      </section>
    );
  }

  const record = state.data;
  const meta = [
    show(record.market),
    humanize(record.category),
    humanize(record.channel),
    `Opened ${formatShortDateTime(record.created_at)}`,
  ];
  return (
    <section className="panel case-summary" aria-labelledby="summary-heading">
      <div className="section-head">
        <h2 id="summary-heading">Case</h2>
      </div>
      <div className="case-topline">
        <h3 className="case-title">{show(record.case_id)}</h3>
        <span className="case-status">{humanize(record.status)}</span>
      </div>
      <p className="case-subtitle">{humanize(record.case_type)}</p>
      <ul className="case-meta" aria-label="Case details">
        {meta.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>

      <h3>Customer statement</h3>
      <p className="quoted">{show(record.complaint_text)}</p>

      <Disclosure title="Raw case data">
        <pre className="code-block">{asText(record)}</pre>
      </Disclosure>
    </section>
  );
}
