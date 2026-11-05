import { useEffect, useState } from "react";
import StepActions from "./StepActions.jsx";
import { fetchDemoOrders } from "../api.js";
import { orderEnding } from "../content.js";
import { useLanguage } from "../i18n/LanguageProvider.jsx";

export default function OrderStep({ selected, onSelect, onContinue }) {
  const { t, errorText, serverText, formatPrice, formatDate } = useLanguage();
  const [state, setState] = useState({ status: "loading", orders: [], error: null });
  const [attempt, setAttempt] = useState(0);

  // The orders are fetched once per attempt, never per language: the order data does not change with the language,
  // only the words around it do, so switching language keeps the list and the selected order exactly as they are.
  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading", orders: [], error: null });
    fetchDemoOrders(controller.signal)
      .then((orders) => setState({ status: "ready", orders, error: null }))
      .catch((error) => {
        if (controller.signal.aborted) return;
        setState({ status: "error", orders: [], error });
      });
    return () => controller.abort();
  }, [attempt]);

  return (
    <section className="step" aria-labelledby="order-heading">
      <h2 id="order-heading" className="step-title" tabIndex={-1}>
        {t("order.heading")}
      </h2>

      {state.status === "loading" ? <p role="status">{t("order.loading")}</p> : null}

      {state.status === "error" ? (
        <div className="notice" role="alert">
          <p>{errorText(state.error)}</p>
          <button type="button" className="button" onClick={() => setAttempt((value) => value + 1)}>
            {t("order.retry")}
          </button>
        </div>
      ) : null}

      {state.status === "ready" && state.orders.length === 0 ? <p>{t("order.empty")}</p> : null}

      {state.status === "ready" && state.orders.length > 0 ? (
        <fieldset className="choice-list">
          <legend className="visually-hidden">{t("order.legend")}</legend>
          {state.orders.map((order) => {
            const ending = orderEnding(order.order_reference);
            return (
              <label key={order.order_reference} className="choice">
                <input
                  type="radio"
                  name="order"
                  value={order.order_reference}
                  checked={selected === order.order_reference}
                  onChange={() => onSelect(order)}
                />
                <span className="choice-body">
                  <span className="choice-title">{order.product_name}</span>
                  <span className="choice-meta">
                    {ending ? t("order.ending", { digits: ending }) : t("order.generic")} · {formatDate(order.order_date)} ·{" "}
                    {formatPrice(order.price)}
                  </span>
                  <span className="choice-meta">{serverText(order.delivery_summary)}</span>
                </span>
              </label>
            );
          })}
        </fieldset>
      ) : null}

      <StepActions onContinue={onContinue} disabled={!selected} />
    </section>
  );
}
