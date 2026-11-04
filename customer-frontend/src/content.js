// Customer-facing copy and issue definitions. Plain language only: no internal case types, no system terms.
// Issue keys match the backend IssueType values, which are the only values the API accepts.

export const ISSUES = [
  {
    key: "DAMAGED_ITEM",
    label: "Item arrived damaged",
    description: "Something is broken, cracked or unusable.",
    detailHeading: "Tell us about the damage",
    detailQuestion: "What happened?",
    detailHelp: "Describe what you saw.",
  },
  {
    key: "LATE_OR_MISSING",
    label: "Order is late or missing",
    description: "The delivery date has passed, or the package didn't arrive.",
    detailHeading: "Tell us about the delivery",
    detailQuestion: "Anything we should know about the delivery?",
    detailHelp: "Add anything that would help us understand the delay.",
  },
  {
    key: "RETURN_ITEM",
    label: "Return an item",
    description: "Send an eligible item back.",
    detailHeading: "Tell us about the return",
    detailQuestion: "Why are you returning it?",
    detailHelp: "A short reason is enough.",
  },
  {
    key: "OTHER",
    label: "Something else",
    description: "Get help with another issue.",
    detailHeading: "How can we help?",
    detailQuestion: "Tell us what you need.",
    detailHelp: "Describe what you need in a sentence or two.",
  },
];

export const issueFor = (key) => ISSUES.find((issue) => issue.key === key) ?? null;

export const STATEMENT_MIN = 10;
export const STATEMENT_MAX = 1000;
export const STATEMENT_COUNT_FROM = 800;

// Shows the last four characters of the order reference, for example "Order ending in 1001".
export function orderEnding(reference) {
  const digits = String(reference ?? "").replace(/\D/g, "");
  return digits.length >= 4 ? digits.slice(-4) : null;
}

export function formatPrice(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);
}

export function formatOrderDate(value) {
  if (typeof value !== "string") return "";
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" }).format(date);
}
