import { useState } from "react";
import ErrorNotice from "./ErrorNotice.jsx";
import { formatUsd, humanize } from "../format.js";

// Limits mirror the backend DecisionRequest model. The browser checks them only to give quick feedback;
// the backend enforces them and its message is shown when it refuses a request.
const MAX_REVIEWER = 80;
const MAX_NOTE = 500;
const MAX_MESSAGE = 2000;

const READ_ONLY_TEXT = "Approval controls are not enabled in this environment.";

function Facts({ run }) {
  const proposal = run.proposal;
  const clauses = Array.isArray(proposal.policy_clause_ids) ? proposal.policy_clause_ids : [];
  return (
    <dl className="details checkpoint-facts">
      <div className="row">
        <dt>Decision</dt>
        <dd>{humanize(proposal.decision)}</dd>
      </div>
      <div className="row">
        <dt>Amount</dt>
        <dd>{formatUsd(proposal.amount)}</dd>
      </div>
      <div className="row">
        <dt>Policy clauses</dt>
        <dd>
          {clauses.length > 0 ? clauses.map((id) => <code key={id} className="clause-chip">{id}</code>) : "None cited"}
        </dd>
      </div>
    </dl>
  );
}

function reviewerField(value, onChange, id) {
  return (
    <div className="field">
      <label htmlFor={id}>Reviewer name (required)</label>
      <input
        id={id}
        type="text"
        value={value}
        maxLength={MAX_REVIEWER}
        onChange={(event) => onChange(event.target.value)}
        autoComplete="off"
      />
      <p className="muted">Recorded with the decision. It is not verified by this view.</p>
    </div>
  );
}

// Keyed by case and proposal fingerprint by the parent, so local form state resets whenever either changes.
export default function HumanCheckpoint({ run, decision, onDecide }) {
  const [mode, setMode] = useState(null); // null | "approve" | "edit" | "reject"
  const [reviewer, setReviewer] = useState("");
  const [note, setNote] = useState("");
  const [message, setMessage] = useState(run.proposal?.customer_message_draft || "");
  const [reviewing, setReviewing] = useState(false); // the edit has been written and is awaiting confirmation

  const fingerprint = run.proposal_fingerprint;
  const escalation = run.proposal?.decision === "ESCALATE";

  if (!run.checkpoint_writes_enabled) {
    return (
      <section className="checkpoint" aria-labelledby="checkpoint-heading">
        <h3 id="checkpoint-heading">Human checkpoint</h3>
        <p>{READ_ONLY_TEXT}</p>
      </section>
    );
  }

  if (run.status !== "AWAITING_APPROVAL" || !fingerprint) {
    return (
      <section className="checkpoint" aria-labelledby="checkpoint-heading">
        <h3 id="checkpoint-heading">Human checkpoint</h3>
        <p>This recommendation did not pass validation, so it cannot be approved.</p>
      </section>
    );
  }

  if (decision.status === "submitting") {
    return (
      <section className="checkpoint" aria-labelledby="checkpoint-heading" aria-busy="true">
        <h3 id="checkpoint-heading">Human checkpoint</h3>
        <p role="status">Recording decision...</p>
      </section>
    );
  }

  if (decision.status === "ready") {
    const result = decision.data;
    const executed = result.status === "EXECUTED";
    return (
      <section className="checkpoint checkpoint-result" aria-labelledby="checkpoint-heading">
        <h3 id="checkpoint-heading">Human checkpoint</h3>
        {executed ? (
          <>
            <p className="result-title">Approved. Mock actions executed.</p>
            <ul className="executed-list">
              {result.executed_actions.map((item, index) => (
                <li key={`${item.action}-${index}`}>
                  {humanize(item.action)}
                  {typeof item.amount === "number" ? ` (${formatUsd(item.amount)})` : ""}
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="result-title">Rejected. No resolution action was executed.</p>
        )}
        <p className="muted">{result.outcome}</p>
        {!executed ? <p className="muted">The case requires manual handling.</p> : null}
      </section>
    );
  }

  const busy = decision.status === "submitting";

  const submit = (fields) => {
    onDecide({ proposal_fingerprint: fingerprint, reviewer: reviewer.trim(), ...fields });
  };

  const startMode = (next) => {
    setMode(next);
    setReviewing(false);
  };

  const reviewerReady = reviewer.trim().length > 0 && reviewer.trim().length <= MAX_REVIEWER;

  let body;
  if (mode === null) {
    body = (
      <div className="checkpoint-actions">
        <button type="button" className="button button-primary" onClick={() => startMode("approve")} disabled={busy}>
          Approve
        </button>
        <button
          type="button"
          className="button"
          onClick={() => startMode("edit")}
          disabled={busy || escalation}
          aria-describedby={escalation ? "edit-unavailable" : undefined}
        >
          Edit message
        </button>
        <button type="button" className="button button-negative" onClick={() => startMode("reject")} disabled={busy}>
          Reject
        </button>
        {escalation ? (
          <p id="edit-unavailable" className="muted">
            Escalations do not send a customer message, so only Approve or Reject are available.
          </p>
        ) : null}
      </div>
    );
  } else if (mode === "approve") {
    body = (
      <div className="checkpoint-confirm">
        <p className="confirm-title">Review approval</p>
        <Facts run={run} />
        <p className="muted">
          {escalation
            ? "No customer message is sent for an escalation. Approval records the escalation and runs the mock escalate action."
            : "Approval records the decision and runs the mock actions for it. Customer message:"}
        </p>
        {escalation ? null : <p className="quoted">{run.proposal.customer_message_draft}</p>}
        {reviewerField(reviewer, setReviewer, "reviewer-approve")}
        <div className="checkpoint-actions">
          <button type="button" className="button button-primary" disabled={!reviewerReady || busy} onClick={() => submit({ action: "APPROVE" })}>
            Confirm approval
          </button>
          <button type="button" className="button" onClick={() => startMode(null)}>
            Cancel
          </button>
        </div>
      </div>
    );
  } else if (mode === "edit") {
    const trimmed = message.trim();
    const messageOk = trimmed.length > 0 && trimmed.length <= MAX_MESSAGE;
    body = reviewing ? (
      <div className="checkpoint-confirm">
        <p className="confirm-title">Confirm approval with edited message</p>
        <Facts run={run} />
        <p className="muted">Only the customer message changes. Customer message as it will be sent:</p>
        <p className="quoted">{trimmed}</p>
        {reviewerField(reviewer, setReviewer, "reviewer-edit")}
        <div className="checkpoint-actions">
          <button type="button" className="button button-primary" disabled={!reviewerReady || busy} onClick={() => submit({ action: "EDIT_AND_APPROVE", edited_message: trimmed })}>
            Confirm approval with edit
          </button>
          <button type="button" className="button" onClick={() => setReviewing(false)}>
            Back to edit
          </button>
        </div>
      </div>
    ) : (
      <div className="checkpoint-confirm">
        <p className="confirm-title">Edit customer message</p>
        <Facts run={run} />
        <div className="field">
          <label htmlFor="edit-message">Customer message (editable)</label>
          <textarea
            id="edit-message"
            className="message-editor"
            value={message}
            maxLength={MAX_MESSAGE + 200}
            onChange={(event) => setMessage(event.target.value)}
            rows={5}
            aria-invalid={!messageOk}
            aria-describedby="edit-message-help"
          />
          <p id="edit-message-help" className="muted">
            Plain text, up to {MAX_MESSAGE} characters. Decision, amount, clauses and evidence cannot be edited here.
          </p>
          {!messageOk ? (
            <p className="field-error" role="alert">
              {trimmed.length === 0 ? "The customer message cannot be empty." : `The customer message is longer than ${MAX_MESSAGE} characters.`}
            </p>
          ) : null}
        </div>
        <div className="checkpoint-actions">
          <button type="button" className="button button-primary" disabled={!messageOk || busy} onClick={() => setReviewing(true)}>
            Review edit
          </button>
          <button type="button" className="button" onClick={() => startMode(null)}>
            Cancel
          </button>
        </div>
      </div>
    );
  } else {
    body = (
      <div className="checkpoint-confirm">
        <p className="confirm-title">Review rejection</p>
        <p className="muted">
          Rejection records your decision. No resolution action will run, and the case stays open for manual handling.
        </p>
        <div className="field">
          <label htmlFor="reject-note">Reason (optional)</label>
          <textarea id="reject-note" value={note} maxLength={MAX_NOTE} onChange={(event) => setNote(event.target.value)} rows={3} />
        </div>
        {reviewerField(reviewer, setReviewer, "reviewer-reject")}
        <div className="checkpoint-actions">
          <button
            type="button"
            className="button button-negative"
            disabled={!reviewerReady || busy}
            onClick={() => submit({ action: "REJECT", note: note.trim() || undefined })}
          >
            Confirm rejection
          </button>
          <button type="button" className="button" onClick={() => startMode(null)}>
            Cancel
          </button>
        </div>
      </div>
    );
  }

  return (
    <section className="checkpoint" aria-labelledby="checkpoint-heading">
      <h3 id="checkpoint-heading">Human checkpoint</h3>
      <p className="muted">Nothing is executed until you confirm.</p>
      {decision.status === "error" ? (
        <ErrorNotice title="The decision was not recorded." detail={decision.error} />
      ) : null}
      {body}
    </section>
  );
}
