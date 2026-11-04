import { useEffect, useRef, useState } from "react";
import ViewSwitch from "./components/ViewSwitch.jsx";
import Progress from "./components/Progress.jsx";
import OrderStep from "./components/OrderStep.jsx";
import ProblemStep from "./components/ProblemStep.jsx";
import DetailsStep from "./components/DetailsStep.jsx";
import ReviewStep from "./components/ReviewStep.jsx";
import ResultStep from "./components/ResultStep.jsx";
import { submitSupportRequest } from "./api.js";

// One task per screen, in one application state. The address stays /support/ for every step, so the
// app does not need a router or any deep-link handling. Answers are kept while the customer moves
// backwards, so Back never discards work.
export default function App() {
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

  // Moving between steps (including Back) puts focus on the new step's heading, so keyboard and screen reader
  // users land on the task instead of the top of the page. The first render is left alone.
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    document.querySelector(".support-main .step-title")?.focus();
  }, [step]);

  function startAnother() {
    setStep("order");
    setOrderReference(null);
    setOrderSummary(null);
    setIssueType(null);
    setStatement("");
    setSubmitError(null);
    setReceipt(null);
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
    )
      .then((result) => {
        setReceipt(result);
        setStep("result");
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setSubmitError(error.message);
      })
      .finally(() => {
        submittingRef.current = false;
        setSubmitting(false);
      });
  }

  return (
    <div className="support-app">
      <header className="site-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <span className="brand-name">Cosmic Mart</span>
        </div>
        <div className="header-end">
          <span className="brand-section">Support</span>
          <ViewSwitch current="customer" />
        </div>
      </header>

      <main className="support-main" aria-labelledby="page-title">
        <h1 id="page-title" className="visually-hidden">
          Cosmic Mart support
        </h1>

        {step !== "result" ? <Progress current={step} /> : null}

        {step === "order" ? (
          <OrderStep
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

        {step === "result" && receipt ? <ResultStep receipt={receipt} onStartAnother={startAnother} /> : null}
      </main>
    </div>
  );
}
