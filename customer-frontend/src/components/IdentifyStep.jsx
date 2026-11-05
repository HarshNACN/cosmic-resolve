import { useState } from "react";
import { identifyCustomer } from "../api.js";
import { DEMO_ACCESS_CODE, DEMO_NAMES } from "../content.js";
import { useLanguage } from "../i18n/LanguageProvider.jsx";

// DEMO SIGN-IN ONLY. A full name and a shared demo code choose which synthetic customer's orders the demo shows. This is
// not account verification and the page says so; a real service would ask for an email address and a password. The
// server answers every failure with the same message, and the page never receives a customer id, only an opaque token.
export default function IdentifyStep({ onIdentified }) {
  const { t, errorText } = useLanguage();
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [state, setState] = useState({ busy: false, error: null });

  async function submit(event) {
    event.preventDefault();
    if (state.busy) return;
    setState({ busy: true, error: null });
    try {
      const session = await identifyCustomer(name, code);
      onIdentified({ token: session.token, firstName: session.first_name });
    } catch (error) {
      setState({ busy: false, error });
    }
  }

  return (
    <section className="step" aria-labelledby="identify-heading">
      <h2 id="identify-heading" className="step-title" tabIndex={-1}>
        {t("identify.heading")}
      </h2>
      <p className="field-help">{t("identify.intro")}</p>

      <form onSubmit={submit} noValidate>
        <div className="field">
          <label htmlFor="identify-name" className="field-label">
            {t("identify.name")}
          </label>
          <input
            id="identify-name"
            className="input"
            type="text"
            autoComplete="off"
            value={name}
            maxLength={80}
            onChange={(event) => setName(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="identify-code" className="field-label">
            {t("identify.code")}
          </label>
          <input
            id="identify-code"
            className="input"
            type="text"
            autoComplete="off"
            value={code}
            maxLength={40}
            onChange={(event) => setCode(event.target.value)}
          />
        </div>

        {state.error ? (
          <div className="notice" role="alert">
            <p>{errorText(state.error)}</p>
          </div>
        ) : null}

        <div className="step-actions">
          <span />
          <button type="submit" className="button button-primary" disabled={state.busy || !name.trim() || !code.trim()}>
            {state.busy ? t("identify.busy") : t("identify.submit")}
          </button>
        </div>
      </form>

      <aside className="demo-note" aria-label={t("result.demoLabel")}>
        <p>{t("identify.demoNote")}</p>
        <p>{t("identify.hint", { names: DEMO_NAMES.join(", "), code: DEMO_ACCESS_CODE })}</p>
      </aside>
    </section>
  );
}
