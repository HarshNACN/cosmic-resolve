import { useLanguage } from "../i18n/LanguageProvider.jsx";

const STEPS = ["order", "problem", "details", "review"];

// Shows completed, current and upcoming steps. The state is also spoken as text, so it never depends on colour.
export default function Progress({ current }) {
  const { t } = useLanguage();
  const currentIndex = STEPS.indexOf(current);
  return (
    <nav aria-label={t("progress.label")}>
      <ol className="progress">
        {STEPS.map((step, index) => {
          const state = index < currentIndex ? "completed" : index === currentIndex ? "current" : "upcoming";
          const spoken = t(`progress.${state}`);
          return (
            <li key={step} className={`progress-item is-${state}`} aria-current={state === "current" ? "step" : undefined}>
              <span className="progress-marker" aria-hidden="true">
                {state === "completed" ? "✓" : index + 1}
              </span>
              <span className="progress-label">{t(`progress.${step}`)}</span>
              <span className="visually-hidden"> ({spoken})</span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
