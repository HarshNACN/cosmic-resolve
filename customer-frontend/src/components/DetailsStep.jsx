import { useState } from "react";
import StepActions from "./StepActions.jsx";
import { STATEMENT_COUNT_FROM, STATEMENT_MAX, STATEMENT_MIN, issueFor } from "../content.js";

// Only the question for the chosen issue is shown. Validation runs when the customer tries to continue, so the
// field is never marked wrong before they have had a chance to write.
export default function DetailsStep({ issueType, statement, onChange, onBack, onContinue }) {
  const issue = issueFor(issueType);
  const [attempted, setAttempted] = useState(false);

  if (!issue) {
    return (
      <section className="step" aria-labelledby="details-heading">
        <h2 id="details-heading" className="step-title">
          Choose an issue first
        </h2>
        <StepActions onBack={onBack} onContinue={() => {}} disabled />
      </section>
    );
  }

  const trimmed = statement.trim();
  let error = null;
  if (trimmed.length < STATEMENT_MIN) error = "Add a few more details so we can help.";
  else if (statement.length > STATEMENT_MAX) error = `Keep your details to ${STATEMENT_MAX} characters or fewer.`;

  const showError = attempted && error !== null;

  return (
    <section className="step" aria-labelledby="details-heading">
      <h2 id="details-heading" className="step-title" tabIndex={-1}>
        {issue.detailHeading}
      </h2>

      <div className="field">
        <label htmlFor="statement" className="field-label">
          {issue.detailQuestion}
        </label>
        <p id="statement-help" className="field-help">
          {issue.detailHelp}
        </p>
        <textarea
          id="statement"
          className="textarea"
          rows={6}
          value={statement}
          onChange={(event) => onChange(event.target.value)}
          aria-invalid={showError}
          aria-describedby={showError ? "statement-help statement-error" : "statement-help"}
        />
        <div className="field-footer">
          {showError ? (
            <p id="statement-error" className="field-error" role="alert">
              {error}
            </p>
          ) : (
            <span />
          )}
          {statement.length >= STATEMENT_COUNT_FROM ? (
            <span className="field-count">
              {statement.length} of {STATEMENT_MAX}
            </span>
          ) : null}
        </div>
      </div>

      <StepActions
        onBack={onBack}
        onContinue={() => {
          setAttempted(true);
          if (error === null) onContinue();
        }}
      />
    </section>
  );
}
