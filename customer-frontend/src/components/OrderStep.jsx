import { useEffect, useState } from "react";
import StepActions from "./StepActions.jsx";
import { fetchDemoOrders } from "../api.js";
import { formatOrderDate, formatPrice, orderEnding } from "../content.js";

export default function OrderStep({ selected, onSelect, onContinue }) {
  const [state, setState] = useState({ status: "loading", orders: [], error: null });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading", orders: [], error: null });
    fetchDemoOrders(controller.signal)
      .then((orders) => setState({ status: "ready", orders, error: null }))
      .catch((error) => {
        if (controller.signal.aborted) return;
        setState({ status: "error", orders: [], error: error.message });
      });
    return () => controller.abort();
  }, [attempt]);

  return (
    <section className="step" aria-labelledby="order-heading">
      <h2 id="order-heading" className="step-title" tabIndex={-1}>
        Which order do you need help with?
      </h2>

      {state.status === "loading" ? <p role="status">Loading your orders...</p> : null}

      {state.status === "error" ? (
        <div className="notice" role="alert">
          <p>{state.error}</p>
          <button type="button" className="button" onClick={() => setAttempt((value) => value + 1)}>
            Try again
          </button>
        </div>
      ) : null}

      {state.status === "ready" && state.orders.length === 0 ? <p>No orders are available right now.</p> : null}

      {state.status === "ready" && state.orders.length > 0 ? (
        <fieldset className="choice-list">
          <legend className="visually-hidden">Orders</legend>
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
                    {ending ? `Order ending in ${ending}` : "Order"} · {formatOrderDate(order.order_date)} ·{" "}
                    {formatPrice(order.price)}
                  </span>
                  <span className="choice-meta">{order.delivery_summary}</span>
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
