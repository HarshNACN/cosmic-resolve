import { useEffect, useRef } from "react";
import { issueFor } from "../content.js";
import CaseStatus, { isTrackable } from "./CaseStatus.jsx";
import { useLanguage } from "../i18n/LanguageProvider.jsx";

// The receipt describes this interaction only. It makes no promise of review, notification, lookup or timing.
// The demo note comes from the backend receipt, so every client shows the same disclosure: it is translated only when
// it is exactly the known sentence, and any other note is shown as the server sent it. The reference never changes.
export default function ResultStep({ receipt, issueType, token, onStartAnother }) {
  const { t, serverText } = useLanguage();
  const headingRef = useRef(null);
  const issue = issueFor(issueType);

  // Move focus to the result heading so screen readers announce the outcome when the step appears.
  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  return (
    <section className="step result" aria-labelledby="result-heading">
      <h2 id="result-heading" className="step-title" tabIndex={-1} ref={headingRef}>
        {t("result.heading")}
      </h2>

      <p className="result-message">{serverText(receipt.customer_message)}</p>

      <dl className="review-list">
        <div className="review-row">
          <dt>{t("result.reference")}</dt>
          <dd className="reference">{receipt.reference}</dd>
        </div>
        <div className="review-row">
          <dt>{t("result.issue")}</dt>
          <dd>{issue ? t(`issue.${issue.key}.label`) : receipt.issue_label}</dd>
        </div>
      </dl>

      {token && isTrackable(receipt.reference) ? <CaseStatus token={token} reference={receipt.reference} /> : null}

      <div className="step-actions">
        <span />
        <button type="button" className="button button-primary" onClick={onStartAnother}>
          {t("result.startAnother")}
        </button>
      </div>

      <aside className="demo-note" aria-label={t("result.demoLabel")}>
        <p>{serverText(receipt.next_step)}</p>
      </aside>
    </section>
  );
}
