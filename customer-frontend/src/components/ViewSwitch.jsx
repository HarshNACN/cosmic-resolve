// Switches between the two Cosmic Resolve views: the internal case workbench (/internal/) and the customer
// support portal (/support/). They are separate apps that share one origin with the landing page at "/":
// Vercel routes the paths when deployed, and the landing dev server forwards them locally (landing/vite.config.js).
// Open http://localhost:5173 so both links resolve.
export const VIEW_URLS = {
  internal: "/internal/",
  customer: "/support/",
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
