// The few presentation helpers the call panel needs. They live in the voice folder so the panel imports nothing from
// the internal app, and the customer page can mount the same panel. With no host props the output is exactly what the
// internal app's own helpers produce.

// {name} placeholders in the English fallback text, filled from params.
function fill(template, params) {
  return String(template).replace(/\{(\w+)\}/g, (placeholder, name) => (params && name in params ? String(params[name]) : placeholder));
}

// The default text lookup: the English fallback. A host (the customer page) passes its own `t(key, fallback, params)`.
export const defaultT = (key, fallback, params) => fill(fallback, params);

// How an order card writes its reference, price and delivery state. A host can replace any of these.
export const defaultFormat = {
  orderRef: (orderId) => orderId,
  price: (amount) =>
    typeof amount !== "number" || Number.isNaN(amount) ? "Not available" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(amount),
  status: (value) => {
    if (typeof value !== "string" || value === "") return "Not available";
    const text = value.replace(/_/g, " ").toLowerCase();
    return text.charAt(0).toUpperCase() + text.slice(1);
  },
};

// Concise error notice. Same markup and classes as the internal app's ErrorNotice, without its retry button.
export function VoiceNotice({ title, detail }) {
  return (
    <div className="notice notice-error" role="alert">
      <p className="notice-title">{title}</p>
      {detail ? <p className="notice-detail">{detail}</p> : null}
    </div>
  );
}
