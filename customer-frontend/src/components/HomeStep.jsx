import { useLanguage } from "../i18n/LanguageProvider.jsx";
import YourRequests from "./YourRequests.jsx";

// Two equally prominent ways to get help. Both cards are the same size and style; the voice card is only disabled
// (with a plain reason) while voice is not available, so the form is always there.
export default function HomeStep({ firstName, token, voiceAvailable, onVoice, onForm }) {
  const { t } = useLanguage();
  return (
    <section className="step" aria-labelledby="home-heading">
      <h2 id="home-heading" className="step-title" tabIndex={-1}>
        {t("home.heading", { name: firstName })}
      </h2>

      <div className="home-grid">
        <button type="button" className="home-card" onClick={onVoice} disabled={!voiceAvailable}>
          <span className="home-card-title">{t("home.voice.title")}</span>
          <span className="home-card-text">{voiceAvailable ? t("home.voice.text") : t("home.voice.soon")}</span>
        </button>
        <button type="button" className="home-card" onClick={onForm}>
          <span className="home-card-title">{t("home.form.title")}</span>
          <span className="home-card-text">{t("home.form.text")}</span>
        </button>
      </div>

      {token ? <YourRequests token={token} /> : null}
    </section>
  );
}
