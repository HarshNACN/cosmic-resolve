import { useCallback, useMemo, useState } from "react";
import CallPanel from "@cosmo-voice/CallPanel.jsx";
import { orderEnding } from "../content.js";
import CaseStatus, { OriginalMessage, resolutionSummary } from "./CaseStatus.jsx";
import { useLanguage } from "../i18n/LanguageProvider.jsx";
import en from "../i18n/locales/en.js";

// How a delivery state code from the call's order cards is written for a customer. These are the same customer-facing
// wordings the form shows (see customer.py _DELIVERY_SUMMARY): the internal shipment codes are never shown.
const DELIVERY_TEXT = {
  DELIVERED: "server.delivered",
  DELAYED: "server.onTheWay",
  IN_TRANSIT: "server.onTheWay",
  LOST_IN_TRANSIT: "server.notDelivered",
  RETURNED_TO_SENDER: "server.notDelivered",
};

const fill = (template, params) => String(template).replace(/\{(\w+)\}/g, (hole, name) => (params && name in params ? String(params[name]) : hole));

// The existing Cosmo voice experience, mounted for a signed-in customer. It is the same CallPanel the internal app used
// (imported from frontend/src/voice, not copied). This page supplies only what is specific to a customer:
//   - the session token, handed over as a function that returns the Authorization header for the one request that opens
//     the call; the page sends no customer id and never calls the callers list
//   - its translations and its order-card wording
//   - the page's language, so the call starts in it, follows it, and reports every spoken switch back to it
export default function VoiceStep({ session, onBack }) {
  const { t, language, onVoiceEvent, formatPrice } = useLanguage();
  const [caseId, setCaseId] = useState(null); // the case this call created, once the customer confirms it
  const [verified, setVerified] = useState(null); // that case's server-verified status, shared with the transcript

  // A new call (or New call after one ended) starts clean: the last call's case must not look like this one's.
  const resetCall = useCallback(() => {
    setCaseId(null);
    setVerified(null);
  }, []);

  // The approved-message line, shown as a localized summary of the verified outcome (it follows the page language)
  // with the associate's original wording kept, untranslated, in a collapsed control.
  const renderNote = useCallback(
    (line) => {
      const summary = resolutionSummary(t, formatPrice, verified);
      return (
        <>
          <span className="who who-agent">{t("voice.who.summary")}</span>
          {summary}
          <OriginalMessage message={line.text} />
        </>
      );
    },
    [t, formatPrice, verified],
  );

  const getAuthHeaders = useCallback(() => ({ Authorization: `Bearer ${session.token}` }), [session.token]);
  const customer = useMemo(() => ({ firstName: session.firstName, getAuthHeaders }), [session.firstName, getAuthHeaders]);

  // The panel asks for a key and an English fallback; a key this page has text for is translated, anything else keeps the fallback.
  const voiceT = useCallback((key, fallback, params) => (key in en ? t(key, params) : fill(fallback, params)), [t]);
  const format = useMemo(
    () => ({
      orderRef: (id) => {
        const ending = orderEnding(id);
        return ending ? t("order.ending", { digits: ending }) : t("order.generic");
      },
      price: formatPrice,
      status: (code) => t(DELIVERY_TEXT[code] ?? "server.statusUnavailable"),
    }),
    [t, formatPrice],
  );

  return (
    <>
      <button type="button" className="link-button back-to-options" onClick={onBack}>
        {t("home.back")}
      </button>
      <CallPanel
        customer={customer}
        t={voiceT}
        format={format}
        language={language}
        onLanguageChange={(code) => onVoiceEvent({ type: "language", language: code })}
        onCaseCreated={setCaseId}
        onCallReset={resetCall}
        renderNote={renderNote}
        hideLanguageSelector
      />
      {caseId ? <CaseStatus token={session.token} reference={caseId} onStatus={setVerified} /> : null}
    </>
  );
}
