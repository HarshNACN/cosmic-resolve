import StepActions from "./StepActions.jsx";
import { ISSUES } from "../content.js";
import { useLanguage } from "../i18n/LanguageProvider.jsx";

export default function ProblemStep({ selected, onSelect, onBack, onContinue }) {
  const { t } = useLanguage();
  return (
    <section className="step" aria-labelledby="problem-heading">
      <h2 id="problem-heading" className="step-title" tabIndex={-1}>
        {t("problem.heading")}
      </h2>

      <fieldset className="choice-list">
        <legend className="visually-hidden">{t("problem.heading")}</legend>
        {ISSUES.map((issue) => (
          <label key={issue.key} className="choice">
            <input
              type="radio"
              name="issue"
              value={issue.key}
              checked={selected === issue.key}
              onChange={() => onSelect(issue.key)}
            />
            <span className="choice-body">
              <span className="choice-title">{t(`issue.${issue.key}.label`)}</span>
              <span className="choice-meta">{t(`issue.${issue.key}.description`)}</span>
            </span>
          </label>
        ))}
      </fieldset>

      <StepActions onBack={onBack} onContinue={onContinue} disabled={!selected} />
    </section>
  );
}
