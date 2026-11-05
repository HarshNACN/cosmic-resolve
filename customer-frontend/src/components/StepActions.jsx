import { useLanguage } from "../i18n/LanguageProvider.jsx";

// Back is always at the left and the primary action always at the right, so the action position never moves.
export default function StepActions({ onBack, onContinue, continueLabel, disabled = false }) {
  const { t } = useLanguage();
  return (
    <div className="step-actions">
      {onBack ? (
        <button type="button" className="button button-quiet" onClick={onBack}>
          {t("actions.back")}
        </button>
      ) : (
        <span />
      )}
      <button type="button" className="button button-primary" onClick={onContinue} disabled={disabled}>
        {continueLabel ?? t("actions.continue")}
      </button>
    </div>
  );
}
