import { issueFor, formatOrderDate, formatPrice, orderEnding } from "../content.js";

// Edit buttons return to the step that owns each answer. Nothing here shows internal fields or decisions.
export default function ReviewStep({ order, issueType, statement, submitting, submitError, onEdit, onBack, onSubmit }) {
  const issue = issueFor(issueType);
  const ending = order ? orderEnding(order.order_reference) : null;

  return (
    <section className="step" aria-labelledby="review-heading">
      <h2 id="review-heading" className="step-title" tabIndex={-1}>
        Review your request
      </h2>

      <dl className="review-list">
        <div className="review-row">
          <dt>
            Order
            <button type="button" className="link-button" onClick={() => onEdit("order")}>
              Edit<span className="visually-hidden"> order</span>
            </button>
          </dt>
          <dd>
            {order ? (
              <>
                <span className="review-strong">{order.product_name}</span>
                <span className="review-sub">
                  {ending ? `Order ending in ${ending}` : "Order"} · {formatOrderDate(order.order_date)} ·{" "}
                  {formatPrice(order.price)}
                </span>
              </>
            ) : (
              "Not selected"
            )}
          </dd>
        </div>

        <div className="review-row">
          <dt>
            Issue
            <button type="button" className="link-button" onClick={() => onEdit("problem")}>
              Edit<span className="visually-hidden"> issue</span>
            </button>
          </dt>
          <dd>{issue ? issue.label : "Not selected"}</dd>
        </div>

        <div className="review-row">
          <dt>
            Details
            <button type="button" className="link-button" onClick={() => onEdit("details")}>
              Edit<span className="visually-hidden"> details</span>
            </button>
          </dt>
          <dd>
            <p className="quoted">{statement}</p>
          </dd>
        </div>
      </dl>

      {submitError ? (
        <div className="notice" role="alert">
          <p>{submitError}</p>
        </div>
      ) : null}

      <div className="step-actions">
        <button type="button" className="button button-quiet" onClick={onBack} disabled={submitting}>
          Back
        </button>
        <button type="button" className="button button-primary" onClick={onSubmit} disabled={submitting}>
          {submitting ? "Sending..." : "Submit request"}
        </button>
      </div>
      <p role="status" aria-live="polite" className="visually-hidden">
        {submitting ? "Sending your request" : ""}
      </p>
    </section>
  );
}
