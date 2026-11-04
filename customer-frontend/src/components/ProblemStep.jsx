import StepActions from "./StepActions.jsx";
import { ISSUES } from "../content.js";

export default function ProblemStep({ selected, onSelect, onBack, onContinue }) {
  return (
    <section className="step" aria-labelledby="problem-heading">
      <h2 id="problem-heading" className="step-title" tabIndex={-1}>
        What happened?
      </h2>

      <fieldset className="choice-list">
        <legend className="visually-hidden">What happened?</legend>
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
              <span className="choice-title">{issue.label}</span>
              <span className="choice-meta">{issue.description}</span>
            </span>
          </label>
        ))}
      </fieldset>

      <StepActions onBack={onBack} onContinue={onContinue} disabled={!selected} />
    </section>
  );
}
