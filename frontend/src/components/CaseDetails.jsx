import Disclosure from "./Disclosure.jsx";
import ErrorNotice from "./ErrorNotice.jsx";
import { asText, formatTimestamp, humanize } from "../format.js";

const NOT_AVAILABLE = "Not available";

function Row({ label, children }) {
  return (
    <div className="row">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

const show = (value) => (typeof value === "string" && value !== "" ? value : NOT_AVAILABLE);

// Renders two sections: the case summary and the evidence the current API can supply.
// The backend exposes only the case record. Customer, order, shipment and inventory data are not
// served by any endpoint, so only the IDs on the case are shown and the gap is stated plainly.
export default function CaseDetails({ caseId, state, onRetry }) {
  if (!caseId) {
    return (
      <section className="panel" aria-labelledby="summary-heading">
        <h2 id="summary-heading">Case summary</h2>
        <p>Select a case from the queue to see its details.</p>
      </section>
    );
  }

  if (state.status === "loading" || state.status === "idle") {
    return (
      <section className="panel" aria-labelledby="summary-heading" aria-busy="true">
        <h2 id="summary-heading">Case summary</h2>
        <p role="status">Loading case...</p>
      </section>
    );
  }

  if (state.status === "error") {
    return (
      <section className="panel" aria-labelledby="summary-heading">
        <h2 id="summary-heading">Case summary</h2>
        <ErrorNotice title="Unable to load this case." detail={state.error} onRetry={onRetry} />
      </section>
    );
  }

  const record = state.data;
  return (
    <>
      <section className="panel" aria-labelledby="summary-heading">
        <h2 id="summary-heading">Case summary</h2>
        <div className="case-header">
          <h3 className="case-title">{show(record.case_id)}</h3>
          <p className="case-subtitle">{humanize(record.case_type)}</p>
        </div>
        <dl className="details">
          <Row label="Market">{show(record.market)}</Row>
          <Row label="Category">{humanize(record.category)}</Row>
          <Row label="Channel">{humanize(record.channel)}</Row>
          <Row label="Opened">{formatTimestamp(record.created_at)}</Row>
          <Row label="Status">{humanize(record.status)}</Row>
        </dl>
        <h3>Customer statement</h3>
        <p className="quoted">{show(record.complaint_text)}</p>
        <Disclosure title="Raw case data">
          <pre className="code-block">{asText(record)}</pre>
        </Disclosure>
      </section>

      <section className="panel" aria-labelledby="evidence-heading">
        <h2 id="evidence-heading">Evidence</h2>
        <p className="muted">Linked records. This service provides their IDs only.</p>
        <dl className="details">
          <Row label="Customer">
            {show(record.customer_id)}
            <span className="muted block">Customer history and prior claims: {NOT_AVAILABLE.toLowerCase()}</span>
          </Row>
          <Row label="Order">
            {show(record.order_id)}
            <span className="muted block">Product, amount and order status: {NOT_AVAILABLE.toLowerCase()}</span>
          </Row>
          <Row label="Shipment">
            {show(record.tracking_id)}
            <span className="muted block">Carrier status and delivery evidence: {NOT_AVAILABLE.toLowerCase()}</span>
          </Row>
          <Row label="Inventory">
            <span className="muted">Replacement availability: {NOT_AVAILABLE.toLowerCase()}</span>
          </Row>
        </dl>
      </section>
    </>
  );
}
