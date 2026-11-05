import { useEffect, useRef, useState } from "react";
import { fetchRequestStatus } from "../api.js";
import { useLanguage } from "../i18n/LanguageProvider.jsx";

// Statuses that will not change by themselves, so polling stops: Resolved (confirmed done) and Follow-up required (a
// person has to act). "Resolution approved" keeps polling, because the actions are not confirmed done yet.
const FINAL = new Set(["RESOLVED", "FOLLOW_UP"]);

// Real case ids look like W-0001 or V-0001; the old validation-only receipt reference (CR-...) has nothing to track.
export const isTrackable = (reference) => /^[VW]-\d+$/.test(String(reference ?? ""));

// Where one of the customer's requests really is. Everything shown comes from the server's verified status: the page
// never decides an outcome. The decision, amount and approved message only arrive once the resolution is confirmed done.
export const resolutionSummary = (t, formatPrice, data) => {
  if (data?.status !== "RESOLVED" || !data.decision) return "";
  const params = { amount: formatPrice(data.amount), product: data.product_name };
  // Written from the verified decision, amount and product, in the active language. Without a product name the
  // plainer decision sentence is used instead.
  return data.product_name ? t(`track.summary.${data.decision}`, params) : t(`track.decision.${data.decision}`, params);
};

// The associate's approved message, exactly as written and never translated, kept out of the way: it was drafted before
// the decision, so it can describe the outcome in the future tense. The summary above it is what the customer reads.
export function OriginalMessage({ message }) {
  const { t } = useLanguage();
  if (!message) return null;
  return (
    <details className="original-message">
      <summary>{t("track.original")}</summary>
      <p className="quoted">{message}</p>
    </details>
  );
}

export default function CaseStatus({ token, reference, intervalMs = 3000, onStatus }) {
  const { t, formatPrice } = useLanguage();
  const [state, setState] = useState({ data: null, failed: false });
  const report = useRef(onStatus);
  report.current = onStatus;

  useEffect(() => {
    let stopped = false;
    let timer;
    const controller = new AbortController();
    async function poll() {
      try {
        const data = await fetchRequestStatus(token, reference, controller.signal);
        if (stopped) return;
        setState({ data, failed: false });
        report.current?.(data);
        if (FINAL.has(data.status)) return;
      } catch (error) {
        if (stopped || controller.signal.aborted) return;
        setState((current) => ({ ...current, failed: true }));
        if (error.status === 401 || error.status === 404) return; // nothing to retry: the session ended or it is not theirs
      }
      timer = setTimeout(poll, intervalMs);
    }
    poll();
    return () => {
      stopped = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, [token, reference, intervalMs]);

  const { data, failed } = state;
  const resolved = data?.status === "RESOLVED";

  return (
    <section className="tracker" aria-labelledby={`tracker-${reference}`}>
      <h3 id={`tracker-${reference}`} className="tracker-title">
        {t("track.heading")}
      </h3>

      {!data ? (
        <p role="status">{failed ? t("track.error") : t("track.loading")}</p>
      ) : (
        <>
          <p className="tracker-status" role="status">
            <span className={`status-badge is-${data.status.toLowerCase().replace("_", "-")}`}>{t(`track.status.${data.status}`)}</span>
          </p>
          <p>{t(`track.note.${data.status}`)}</p>

          {resolved && data.decision ? <p className="tracker-decision">{resolutionSummary(t, formatPrice, data)}</p> : null}
          {resolved ? <OriginalMessage message={data.message} /> : null}
          {resolved ? <p className="field-help">{t("server.caseNote")}</p> : null}
          {failed ? <p className="field-help">{t("track.error")}</p> : null}
        </>
      )}
    </section>
  );
}
