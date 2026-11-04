const STEPS = [
  { key: "order", label: "Order" },
  { key: "problem", label: "Problem" },
  { key: "details", label: "Details" },
  { key: "review", label: "Review" },
];

// Shows completed, current and upcoming steps. The state is also spoken as text, so it never depends on colour.
export default function Progress({ current }) {
  const currentIndex = STEPS.findIndex((step) => step.key === current);
  return (
    <nav aria-label="Progress">
      <ol className="progress">
        {STEPS.map((step, index) => {
          const state = index < currentIndex ? "completed" : index === currentIndex ? "current" : "upcoming";
          const spoken = state === "completed" ? "completed" : state === "current" ? "current step" : "not started";
          return (
            <li
              key={step.key}
              className={`progress-item is-${state}`}
              aria-current={state === "current" ? "step" : undefined}
            >
              <span className="progress-marker" aria-hidden="true">
                {state === "completed" ? "✓" : index + 1}
              </span>
              <span className="progress-label">{step.label}</span>
              <span className="visually-hidden"> ({spoken})</span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
