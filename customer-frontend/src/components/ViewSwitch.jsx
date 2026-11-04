// Switches between the two Cosmic Resolve views: the internal case workbench and the customer support portal.
// They are separate apps. Deployed, they share one origin (/ and /support/). In local development they run on
// different ports, so the dev links point at the other dev server.
const DEV = import.meta.env.DEV;

export const VIEW_URLS = {
  internal: DEV ? "http://localhost:5173/" : "/",
  customer: DEV ? "http://localhost:5174/support/" : "/support/",
};

const VIEWS = [
  { id: "internal", label: "Internal" },
  { id: "customer", label: "Customer" },
];

export default function ViewSwitch({ current = "customer" }) {
  return (
    <nav className="view-switch" aria-label="Switch view">
      {VIEWS.map((view) => (
        <a
          key={view.id}
          href={VIEW_URLS[view.id]}
          className={view.id === current ? "view-switch-link is-current" : "view-switch-link"}
          aria-current={view.id === current ? "page" : undefined}
        >
          {view.label}
        </a>
      ))}
    </nav>
  );
}
