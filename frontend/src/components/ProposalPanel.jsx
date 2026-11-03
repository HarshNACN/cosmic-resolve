import ErrorNotice from "./ErrorNotice.jsx";
import HumanCheckpoint from "./HumanCheckpoint.jsx";
import { formatConfidence, formatUsd, humanize } from "../format.js";

function Row({ label, children }) {
  return (
    <div className="row">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

// Validation status is not a separate field in the API. It is derived from the run status the backend
// returns with the proposal, and labeled that way.
function describeValidation(run) {
  switch (run.status) {
    case "AWAITING_APPROVAL":
      return { text: "Passed. Waiting for a human decision.", passed: true };
    case "VALIDATION_FAILED":
      return { text: `Failed. ${run.error || "The backend rejected this proposal."}`, passed: false };
    case "NO_POLICY":
      return { text: `Not run. ${run.error || "No applicable policy clause was found."}`, passed: false };
    case "PROVIDER_ERROR":
      return { text: `Not run. ${run.error || "The recommendation provider failed."}`, passed: false };
    default:
      return { text: `Unrecognized run status: ${run.status}`, passed: false };
  }
}

function ProposalBody({ run }) {
  const proposal = run.proposal;
  const validation = describeValidation(run);
  const escalated = proposal?.decision === "ESCALATE";
  const needsReview = escalated || !validation.passed;

  const reasons = Array.isArray(proposal?.escalation_reasons) ? proposal.escalation_reasons : [];
  const evidence = Array.isArray(proposal?.evidence) ? proposal.evidence : [];

  return (
    <>
      {needsReview ? (
        <div className="notice notice-review">
          <h3>Needs human review</h3>
          {reasons.length > 0 ? (
            <ul>
              {reasons.map((reason, index) => (
                <li key={index}>{reason}</li>
              ))}
            </ul>
          ) : (
            <p>{escalated ? "No escalation reasons were returned." : "No usable recommendation was produced for this case."}</p>
          )}
          {run.recommended_action ? (
            <p className="recommended-action">
              <span className="recommended-label">Recommended action</span> {run.recommended_action}
            </p>
          ) : null}
        </div>
      ) : null}

      <h3>Validation</h3>
      <p className={validation.passed ? "status status-ok" : "status status-fail"}>
        <strong>Validation:</strong> {validation.text}
      </p>

      {proposal ? (
        <>
          <div className="decision">
            <div className="decision-main">
              <p className="decision-label">Decision</p>
              <p className="decision-value">{humanize(proposal.decision)}</p>
            </div>
            <div className="decision-figures">
              <div>
                <p className="decision-label">Amount</p>
                <p className="decision-amount">{formatUsd(proposal.amount)}</p>
              </div>
              <div>
                <p className="decision-label">Confidence</p>
                <p className="confidence">
                  <span className="confidence-value">{formatConfidence(proposal.confidence)}</span>
                  {typeof proposal.confidence === "number" ? (
                    <span className="meter" aria-hidden="true">
                      <span className="meter-fill" style={{ width: formatConfidence(proposal.confidence) }} />
                    </span>
                  ) : null}
                </p>
              </div>
            </div>
          </div>
          <dl className="details">
            <Row label="Root cause">
              {proposal.root_cause
                ? `${humanize(proposal.root_cause.category)}${proposal.root_cause.detail ? `: ${proposal.root_cause.detail}` : ""}`
                : "Not available"}
            </Row>
          </dl>

          <h3>Model-generated evidence</h3>
          <p className="muted">Written by the recommendation model. Not checked against the source records.</p>
          {evidence.length > 0 ? (
            <ul>
              {evidence.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          ) : (
            <p>No evidence was returned.</p>
          )}

          <h3>Customer message (draft)</h3>
          <p className="muted">Draft only. Nothing has been sent.</p>
          <p className="quoted">{proposal.customer_message_draft || "Not available"}</p>
        </>
      ) : null}
    </>
  );
}

export default function ProposalPanel({ caseId, state, onGenerate, decision, onDecide }) {
  const loading = state.status === "loading";
  return (
    <section className="panel" aria-labelledby="proposal-heading" aria-busy={loading}>
      <h2 id="proposal-heading">Recommended resolution</h2>

      <div className="actions">
        <button type="button" className="button button-primary" onClick={onGenerate} disabled={!caseId || loading}>
          Generate recommendation
        </button>
        <span role="status" aria-live="polite">
          {loading ? "Generating recommendation..." : ""}
        </span>
      </div>

      {state.status === "idle" ? <p>No recommendation has been generated for this case yet.</p> : null}
      {state.status === "error" ? (
        <ErrorNotice title="Unable to generate a recommendation." detail={state.error} onRetry={onGenerate} />
      ) : null}
      {state.status === "ready" ? <ProposalBody run={state.data} /> : null}

      {state.status === "ready" ? (
        <HumanCheckpoint
          key={`${caseId}:${state.data.proposal_fingerprint ?? "none"}`}
          run={state.data}
          decision={decision}
          onDecide={onDecide}
        />
      ) : null}
    </section>
  );
}
