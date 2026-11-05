import { useEffect, useState } from "react";
import { fetchMyRequests } from "../api.js";
import { useLanguage } from "../i18n/LanguageProvider.jsx";

const FINAL = new Set(["RESOLVED", "FOLLOW_UP"]);

// The customer's own requests, form and voice together, each with its verified status. The list is quiet when there is
// nothing to show: no requests yet, or the service cannot be reached.
export default function YourRequests({ token, intervalMs = 5000 }) {
  const { t } = useLanguage();
  const [items, setItems] = useState([]);

  useEffect(() => {
    let stopped = false;
    let timer;
    const controller = new AbortController();
    async function poll() {
      try {
        const list = await fetchMyRequests(token, controller.signal);
        if (stopped) return;
        setItems(list);
        if (list.every((item) => FINAL.has(item.status))) return; // nothing is still moving
      } catch (error) {
        if (stopped || controller.signal.aborted || error.status === 401) return;
      }
      timer = setTimeout(poll, intervalMs);
    }
    poll();
    return () => {
      stopped = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, [token, intervalMs]);

  if (items.length === 0) return null;
  return (
    <section className="your-requests" aria-labelledby="your-requests-heading">
      <h3 id="your-requests-heading" className="tracker-title">
        {t("track.requests")}
      </h3>
      <ul className="request-list">
        {items.slice(0, 5).map((item) => (
          <li key={item.reference} className="request-row">
            <span className="request-main">
              <span className="request-title">{item.product_name || item.order_reference}</span>
              <span className="choice-meta">
                {t(`issue.${item.issue_type}.label`)} · {item.reference}
              </span>
            </span>
            <span className={`status-badge is-${item.status.toLowerCase().replace("_", "-")}`}>{t(`track.status.${item.status}`)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
