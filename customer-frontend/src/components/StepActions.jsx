// Back is always at the left and the primary action always at the right, so the action position never moves.
export default function StepActions({ onBack, onContinue, continueLabel = "Continue", disabled = false }) {
  return (
    <div className="step-actions">
      {onBack ? (
        <button type="button" className="button button-quiet" onClick={onBack}>
          Back
        </button>
      ) : (
        <span />
      )}
      <button type="button" className="button button-primary" onClick={onContinue} disabled={disabled}>
        {continueLabel}
      </button>
    </div>
  );
}
