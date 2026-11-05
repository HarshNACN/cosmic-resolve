import { issueFor, orderEnding } from "../content.js";
import { useLanguage } from "../i18n/LanguageProvider.jsx";

// Edit buttons return to the step that owns each answer. Nothing here shows internal fields or decisions.
// The customer's own statement and the order's name and reference are shown exactly as they were entered or issued.
export default function ReviewStep({ order, issueType, statement, submitting, submitError, onEdit, onBack, onSubmit }) {
  const { t, errorText, serverText, formatPrice, formatDate } = useLanguage();
  const issue = issueFor(issueType);
  const ending = order ? orderEnding(order.order_reference) : null;

  return (
    <section className="step" aria-labelledby="review-heading">
      <h2 id="review-heading" className="step-title" tabIndex={-1}>
        {t("review.heading")}
      </h2>

      <dl className="review-list">
        <div className="review-row">
          <dt>
            {t("review.order")}
            <button type="button" className="link-button" onClick={() => onEdit("order")}>
              {t("review.edit")}
              <span className="visually-hidden"> {t("review.editOrder")}</span>
            </button>
          </dt>
          <dd>
            {order ? (
              <>
                <span className="review-strong">{order.product_name}</span>
                <span className="review-sub">
                  {ending ? t("order.ending", { digits: ending }) : t("order.generic")} · {formatDate(order.order_date)} ·{" "}
                  {formatPrice(order.price)}
                </span>
              </>
            ) : (
              t("review.notSelected")
            )}
          </dd>
        </div>

        <div className="review-row">
          <dt>
            {t("review.issue")}
            <button type="button" className="link-button" onClick={() => onEdit("problem")}>
              {t("review.edit")}
              <span className="visually-hidden"> {t("review.editIssue")}</span>
            </button>
          </dt>
          <dd>{issue ? t(`issue.${issue.key}.label`) : t("review.notSelected")}</dd>
        </div>

        <div className="review-row">
          <dt>
            {t("review.details")}
            <button type="button" className="link-button" onClick={() => onEdit("details")}>
              {t("review.edit")}
              <span className="visually-hidden"> {t("review.editDetails")}</span>
            </button>
          </dt>
          <dd>
            <p className="quoted">{statement}</p>
          </dd>
        </div>
      </dl>

      {submitError ? (
        <div className="notice" role="alert">
          <p>{errorText(submitError)}</p>
        </div>
      ) : null}

      <div className="step-actions">
        <button type="button" className="button button-quiet" onClick={onBack} disabled={submitting}>
          {t("review.back")}
        </button>
        <button type="button" className="button button-primary" onClick={onSubmit} disabled={submitting}>
          {submitting ? t("review.sending") : t("review.submit")}
        </button>
      </div>
      <p role="status" aria-live="polite" className="visually-hidden">
        {submitting ? t("review.sendingStatus") : ""}
      </p>
    </section>
  );
}
