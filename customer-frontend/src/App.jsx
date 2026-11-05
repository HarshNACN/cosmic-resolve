import { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import ViewSwitch from "./components/ViewSwitch.jsx";
import Progress from "./components/Progress.jsx";
import IdentifyStep from "./components/IdentifyStep.jsx";
import HomeStep from "./components/HomeStep.jsx";
import OrderStep from "./components/OrderStep.jsx";
import ProblemStep from "./components/ProblemStep.jsx";
import DetailsStep from "./components/DetailsStep.jsx";
import ReviewStep from "./components/ReviewStep.jsx";
import ResultStep from "./components/ResultStep.jsx";
import VoiceStep from "./components/VoiceStep.jsx";
import { voiceWarmup } from "@cosmo-voice/voiceApi.js";
import { submitSupportRequest } from "./api.js";
import { LanguageProvider, useLanguage } from "./i18n/LanguageProvider.jsx";
import LanguageSelector from "./i18n/LanguageSelector.jsx";

// The customer flow: a demo sign-in, a home page with two ways to get help, and the four-step form. The address stays
// /support/ throughout, so the app needs no router. The form keeps one task per screen in one application state, and
// answers are kept while the customer moves backwards, so Back never discards work. Every answer lives here, above the
// language: changing the language only changes the words on the page, so the order, the issue, the typed details and
// the step are all kept.
//
// initialSession and initialView let a host (or a test) start signed in, for example at the form.
export function SupportApp({ initialSession = null, initialView = null }) {
  const { t } = useLanguage();
  // After the demo sign-in: { token, firstName }. The token is the only credential, it is held in memory only (a page
  // refresh signs out) and it is sent in a header, never in a URL. The page never holds a customer id.
  const [session, setSession] = useState(initialSession);
  const [view, setView] = useState(initialView ?? (initialSession ? "home" : "identify"));
  // Whether the voice service answered: "idle" before sign-in, "checking" while the warm-up runs, then "ready" or "unavailable".
  // The voice card is only disabled once the service has failed to answer; while it is still starting it stays usable.
  const [voice, setVoice] = useState(initialSession ? "ready" : "idle");
  const [step, setStep] = useState("order");
  const [orderReference, setOrderReference] = useState(null);
  const [orderSummary, setOrderSummary] = useState(null);
  const [issueType, setIssueType] = useState(null);
  const [statement, setStatement] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const [receipt, setReceipt] = useState(null);

  const submittingRef = useRef(false);
  const controllerRef = useRef(null);
  const firstRender = useRef(true);

  useEffect(() => () => controllerRef.current?.abort(), []);

  // Moving between steps or screens (including Back) puts focus on the new heading, so keyboard and screen reader users
  // land on the task instead of the top of the page. The first render is left alone.
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    document.querySelector(".support-main .step-title")?.focus();
  }, [step, view]);

  function resetForm() {
    setStep("order");
    setOrderReference(null);
    setOrderSummary(null);
    setIssueType(null);
    setStatement("");
    setSubmitError(null);
    setReceipt(null);
  }

  function startAnother() {
    resetForm();
  }

  // The brand is a real link to the Cosmic Resolve landing page ("/"), a separate app, so this is a full page load and the
  // in-memory demo sign-in does not survive it (cases and backend data do). Before leaving: an unfinished form asks first,
  // and an open call is closed (the view is unmounted, which stops the microphone, the audio and the stream) so nothing
  // keeps recording. Modified clicks (new tab) are left to the browser.
  function goToLanding(event) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    const unfinished = view === "form" && step !== "result" && Boolean(orderReference || issueType || statement.trim());
    if (unfinished && !window.confirm(t("brand.leave"))) return;
    controllerRef.current?.abort();
    flushSync(() => setView("home"));
    window.location.assign("/");
  }

  function signOut() {
    controllerRef.current?.abort();
    resetForm();
    setSession(null);
    setVoice("idle");
    setView("identify");
  }

  // Right after sign-in, start loading the voice (the first load takes several seconds) so it is ready when the customer
  // chooses "Talk to Cosmo". A failure only disables that one card; the form keeps working.
  function warmUpVoice() {
    setVoice("checking");
    voiceWarmup().then(
      () => setVoice("ready"),
      () => setVoice("unavailable"),
    );
  }

  function submit() {
    // Ignore repeat activations while a request is in flight, so a double click cannot send two requests.
    if (submittingRef.current) return;
    submittingRef.current = true;
    setSubmitting(true);
    setSubmitError(null);
    const controller = new AbortController();
    controllerRef.current = controller;
    submitSupportRequest(
      { order_reference: orderReference, issue_type: issueType, customer_statement: statement.trim(), channel: "WEB" },
      controller.signal,
      session?.token,
    )
      .then((result) => {
        setReceipt(result);
        setStep("result");
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setSubmitError(error); // the error itself, so its text can be shown in whichever language is active
      })
      .finally(() => {
        submittingRef.current = false;
        setSubmitting(false);
      });
  }

  return (
    <div className="support-app">
      <header className="site-header">
        <a className="brand brand-link" href="/" aria-label={t("brand.home")} onClick={goToLanding}>
          <span className="brand-mark" aria-hidden="true" />
          <span className="brand-name">Cosmic Mart</span>
        </a>
        <div className="header-end">
          <span className="brand-section">{t("brand.section")}</span>
          {session ? (
            <div className="account">
              <span className="account-name">{t("account.signedInAs", { name: session.firstName })}</span>
              <button type="button" className="link-button account-signout" onClick={signOut}>
                {t("account.signOut")}
              </button>
            </div>
          ) : null}
          <LanguageSelector />
          <ViewSwitch current="customer" />
        </div>
      </header>

      <main className="support-main" aria-labelledby="page-title">
        <h1 id="page-title" className="visually-hidden">
          {t("page.title")}
        </h1>

        {view === "identify" ? (
          <IdentifyStep
            onIdentified={(next) => {
              setSession(next);
              setView("home");
              warmUpVoice();
            }}
          />
        ) : null}

        {view === "home" ? (
          <HomeStep
            firstName={session?.firstName ?? ""}
            token={session?.token}
            voiceAvailable={voice !== "unavailable"}
            onVoice={() => setView("voice")}
            onForm={() => {
              setView("form");
            }}
          />
        ) : null}

        {view === "voice" && session ? <VoiceStep session={session} onBack={() => setView("home")} /> : null}

        {view === "form" ? (
          <>
            {step !== "result" ? (
              <button type="button" className="link-button back-to-options" onClick={() => setView("home")}>
                {t("home.back")}
              </button>
            ) : null}

            {step !== "result" ? <Progress current={step} /> : null}

            {step === "order" ? (
              <OrderStep
                token={session?.token}
                selected={orderReference}
                onSelect={(order) => {
                  setOrderReference(order.order_reference);
                  setOrderSummary(order);
                }}
                onContinue={() => setStep("problem")}
              />
            ) : null}

            {step === "problem" ? (
              <ProblemStep
                selected={issueType}
                onSelect={setIssueType}
                onBack={() => setStep("order")}
                onContinue={() => setStep("details")}
              />
            ) : null}

            {step === "details" ? (
              <DetailsStep
                issueType={issueType}
                statement={statement}
                onChange={setStatement}
                onBack={() => setStep("problem")}
                onContinue={() => setStep("review")}
              />
            ) : null}

            {step === "review" ? (
              <ReviewStep
                order={orderSummary}
                issueType={issueType}
                statement={statement.trim()}
                submitting={submitting}
                submitError={submitError}
                onEdit={setStep}
                onBack={() => setStep("details")}
                onSubmit={submit}
              />
            ) : null}

            {step === "result" && receipt ? (
              <ResultStep receipt={receipt} issueType={issueType} token={session?.token} onStartAnother={startAnother} />
            ) : null}
          </>
        ) : null}
      </main>
    </div>
  );
}

// The customer app. supportedLanguages is the list the running voice system reports (null offers every language the
// page has text for). onLanguageChange is told about a language the customer picks, so a voice call mounted inside
// this page can follow it; a language reported by the voice backend goes the other way through useLanguage().onVoiceEvent.
export default function App({ supportedLanguages = null, onLanguageChange, initialLanguage, ...appProps }) {
  return (
    <LanguageProvider supported={supportedLanguages} onManualChange={onLanguageChange} initial={initialLanguage}>
      <SupportApp {...appProps} />
    </LanguageProvider>
  );
}
