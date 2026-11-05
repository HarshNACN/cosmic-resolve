import { useState } from "react";
import StepActions from "./StepActions.jsx";
import { STATEMENT_COUNT_FROM, STATEMENT_MAX, STATEMENT_MIN, issueFor } from "../content.js";
import { useLanguage } from "../i18n/LanguageProvider.jsx";

// Only the question for the chosen issue is shown. Validation runs when the customer tries to continue, so the
// field is never marked wrong before they have had a chance to write. The error is kept as a key, so a message that
// is already showing changes language with the rest of the page; the customer's own text is never touched.
export default function DetailsStep({ issueType, statement, onChange, onBack, onContinue }) {
  const { t } = useLanguage();
  const issue = issueFor(issueType);
  const [attempted, setAttempted] = useState(false);

  if (!issue) {
    return (
      <section className="step" aria-labelledby="details-heading">
        <h2 id="details-heading" className="step-title">
          {t("details.chooseFirst")}
        </h2>
        <StepActions onBack={onBack} onContinue={() => {}} disabled />
      </section>
    );
  }

  const trimmed = statement.trim();
  let error = null;
  if (trimmed.length < STATEMENT_MIN) error = "details.tooShort";
  else if (statement.length > STATEMENT_MAX) error = "details.tooLong";

  const showError = attempted && error !== null;

  return (
    <section className="step" aria-labelledby="details-heading">
      <h2 id="details-heading" className="step-title" tabIndex={-1}>
        {t(`issue.${issue.key}.detailHeading`)}
      </h2>

      <div className="field">
        <label htmlFor="statement" className="field-label">
          {t(`issue.${issue.key}.detailQuestion`)}
        </label>
        <p id="statement-help" className="field-help">
          {t(`issue.${issue.key}.detailHelp`)}
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
              {t(error, { max: STATEMENT_MAX })}
            </p>
          ) : (
            <span />
          )}
          {statement.length >= STATEMENT_COUNT_FROM ? (
            <span className="field-count">{t("details.count", { count: statement.length, max: STATEMENT_MAX })}</span>
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
