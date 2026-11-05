// Customer-facing issue definitions and formatting helpers. The words themselves live in i18n/locales/*.js, looked up by
// stable keys such as "issue.DAMAGED_ITEM.label". Plain language only: no internal case types, no system terms.
// Issue keys match the backend IssueType values, which are the only values the API accepts.
import en from "./i18n/locales/en.js";

export const ISSUES = [{ key: "DAMAGED_ITEM" }, { key: "LATE_OR_MISSING" }, { key: "RETURN_ITEM" }, { key: "OTHER" }];

export const issueFor = (key) => ISSUES.find((issue) => issue.key === key) ?? null;

// The shared demo code and the designated demo profiles, shown on the sign-in page as presenter help. They must match
// DEMO_ACCESS_CODE and the demo profiles in backend/cosmic_resolve/customer.py. This is a demo convenience, not a secret.
export const DEMO_ACCESS_CODE = "COSMO-DEMO";
export const DEMO_NAMES = ["Jon Park", "Maya Rowe", "Anita Lee", "Penelope Coleman"];

export const STATEMENT_MIN = 10;
export const STATEMENT_MAX = 1000;
export const STATEMENT_COUNT_FROM = 800;

// Shows the last four digits of the order reference, for example "Order ending in 1001". The reference itself is
// never changed or translated.
export function orderEnding(reference) {
  const digits = String(reference ?? "").replace(/\D/g, "");
  return digits.length >= 4 ? digits.slice(-4) : null;
}

// The amount and currency never change with the language; only the way they are written does.
export function formatPrice(value, locale = "en-US") {
  if (typeof value !== "number" || Number.isNaN(value)) return "";
  return new Intl.NumberFormat(locale, { style: "currency", currency: "USD" }).format(value);
}

export function formatOrderDate(value, locale = "en-US") {
  if (typeof value !== "string") return "";
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(locale, { month: "short", day: "numeric", year: "numeric" }).format(date);
}

// The fixed English sentences the server sends (delivery states and the demo note), mapped to their translation key.
// Text that is not one of these exact sentences has no key, so it is shown as received instead of guessed at.
const SERVER_TEXT = Object.fromEntries(Object.entries(en).filter(([key]) => key.startsWith("server.")).map(([key, text]) => [text, key]));

export const serverTextKey = (text) => SERVER_TEXT[text] ?? null;
