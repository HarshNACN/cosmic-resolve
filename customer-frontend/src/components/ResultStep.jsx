import { useEffect, useRef } from "react";

// The receipt describes this interaction only. It makes no promise of review, notification, lookup or timing.
// The demo note comes from the backend receipt, so every client shows the same disclosure.
export default function ResultStep({ receipt, onStartAnother }) {
  const headingRef = useRef(null);

  // Move focus to the result heading so screen readers announce the outcome when the step appears.
  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  return (
    <section className="step result" aria-labelledby="result-heading">
      <h2 id="result-heading" className="step-title" tabIndex={-1} ref={headingRef}>
        Request received
      </h2>

      <p className="result-message">Your request passed intake validation.</p>

      <dl className="review-list">
        <div className="review-row">
          <dt>Reference</dt>
          <dd className="reference">{receipt.reference}</dd>
        </div>
        <div className="review-row">
          <dt>Issue</dt>
          <dd>{receipt.issue_label}</dd>
        </div>
      </dl>

      <div className="step-actions">
        <span />
        <button type="button" className="button button-primary" onClick={onStartAnother}>
          Start another request
        </button>
      </div>

      <aside className="demo-note" aria-label="Demo note">
        <p>{receipt.next_step}</p>
      </aside>
    </section>
  );
}
