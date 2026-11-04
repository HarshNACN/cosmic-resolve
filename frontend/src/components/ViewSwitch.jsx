// Switches between the two Cosmic Resolve views: the internal case workbench (/) and the customer support
// portal (/support/). They are separate apps that share one origin: Vercel routes them when deployed, and
// the internal dev server proxies /support to the customer dev server locally (see frontend/vite.config.js).
// Open the app at http://localhost:5173 so both links resolve.
export const VIEW_URLS = {
  internal: "/",
  customer: "/support/",
};

const VIEWS = [
  { id: "internal", label: "Internal" },
  { id: "customer", label: "Customer" },
];

export default function ViewSwitch({ current = "internal" }) {
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
