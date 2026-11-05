import { useEffect, useRef, useState } from "react";
import Field from "./Field.jsx";

// Where each view lives. Deployed, these are paths on the same site; locally the landing dev server forwards them.
export const VIEWS = {
  internal: "/internal/",
  customer: "/support/",
};

// The real order of work for one case (see backend/cosmic_resolve/workflow.py), so it is numbered.
export const STEPS = [
  {
    title: "A customer reports a problem",
    text: "Through the support page, or by talking to Cosmo, the voice assistant. The complaint becomes a case.",
  },
  {
    title: "The agent investigates",
    text: "It decides which records to read: the order, the shipment, the customer's history, stock levels.",
  },
  {
    title: "It proposes a fix and cites the policy",
    text: "A refund, replacement, store credit, goodwill credit or an escalation, with the policy clause that allows it.",
  },
  {
    title: "Code checks the proposal",
    text: "The clause must apply to this case, anything over $200 is escalated, and goodwill credit stays within the customer's tier cap.",
  },
  {
    title: "A person decides",
    text: "Approve, edit the customer message, or reject. Only then do the actions run.",
  },
];

export const SAFEGUARDS = [
  {
    title: "Act without approval",
    text: "Every refund, replacement and message waits for a person. The agent can read records but cannot write anything.",
  },
  {
    title: "Take instructions from a complaint",
    text: "What a customer writes is treated as information. Attempts to change the policy or the amount are flagged and escalated.",
  },
  {
    title: "Make up policy",
    text: "A proposal can only cite clauses from the policy book for that market and product, and the citation is checked.",
  },
  {
    title: "Handle large amounts alone",
    text: "Anything over $200, a customer with repeated claims, or conflicting evidence goes to a person as an escalation.",
  },
];

// A soft light that follows the mouse across the whole page. Mouse and pen only; hidden until the first move.
function useCursorGlow(glowRef) {
  useEffect(() => {
    const glow = glowRef.current;
    if (!glow) return undefined;
    const onMove = (event) => {
      if (event.pointerType === "touch") return;
      glow.style.transform = `translate(${event.clientX}px, ${event.clientY}px)`;
      glow.classList.add("is-on");
    };
    const onLeave = () => glow.classList.remove("is-on");
    window.addEventListener("pointermove", onMove, { passive: true });
    document.documentElement.addEventListener("pointerleave", onLeave);
    return () => {
      window.removeEventListener("pointermove", onMove);
      document.documentElement.removeEventListener("pointerleave", onLeave);
    };
  }, [glowRef]);
}

// How far down the steps the reader has scrolled: each step lights up as it reaches the middle of the screen, the
// way a trace fills in. Without IntersectionObserver (old browsers, tests) every step is shown as reached.
function useReachedStep(listRef) {
  const [reached, setReached] = useState(-1);
  useEffect(() => {
    const list = listRef.current;
    if (!list) return undefined;
    if (typeof IntersectionObserver !== "function") {
      setReached(STEPS.length - 1);
      return undefined;
    }
    const items = Array.from(list.querySelectorAll("[data-step]"));
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const index = Number(entry.target.getAttribute("data-step"));
          setReached((current) => Math.max(current, index));
        }
      },
      { rootMargin: "-45% 0px -45% 0px" },
    );
    items.forEach((item) => observer.observe(item));
    return () => observer.disconnect();
  }, [listRef]);
  return reached;
}

export default function App() {
  const glowRef = useRef(null);
  const stepsRef = useRef(null);
  useCursorGlow(glowRef);
  const reached = useReachedStep(stepsRef);
  const progress = STEPS.length > 1 ? Math.max(0, reached) / (STEPS.length - 1) : 1;

  return (
    <div className="page">
      <div className="cursor-glow" ref={glowRef} aria-hidden="true" />

      <header className="nav">
        <a className="brand" href="#top">
          <span className="brand-mark" aria-hidden="true" />
          <span className="brand-name">Cosmic Resolve</span>
        </a>
        <nav className="nav-links" aria-label="Sections">
          <a href="#how">How it works</a>
          <a href="#safeguards">Safeguards</a>
          <a className="nav-cta" href={VIEWS.internal}>
            Open the workbench
          </a>
        </nav>
      </header>

      <main id="top">
        <section className="hero" aria-labelledby="hero-title">
          <Field />
          <div className="hero-content">
            <h1 id="hero-title">Order problems, resolved with a person in charge.</h1>
            <p className="hero-lead">
              Cosmic Resolve investigates each Cosmic Mart complaint, reads the records that matter and proposes a
              fix. Nothing is refunded, replaced or sent until someone approves it.
            </p>
            <div className="hero-actions">
              <a className="button button-primary" href={VIEWS.internal}>
                Open the case workbench
              </a>
              <a className="button button-quiet" href={VIEWS.customer}>
                Report a problem as a customer
              </a>
            </div>
          </div>
          <p className="hero-hint" aria-hidden="true">
            Each point is a record. Move your cursor to investigate.
          </p>
        </section>

        <section className="band" id="how" aria-labelledby="how-title">
          <div className="band-inner split">
            <div className="split-intro">
              <h2 id="how-title">How a case gets resolved</h2>
              <p>Five steps from complaint to outcome. The agent does the reading; a person makes the call.</p>
            </div>
            <ol className="steps" ref={stepsRef} style={{ "--progress": progress }}>
              {STEPS.map((step, index) => (
                <li key={step.title} data-step={index} className={index <= reached ? "step is-reached" : "step"}>
                  <span className="step-marker" aria-hidden="true">
                    {index + 1}
                  </span>
                  <h3>{step.title}</h3>
                  <p>{step.text}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="band band-sunk" id="safeguards" aria-labelledby="safeguards-title">
          <div className="band-inner">
            <h2 id="safeguards-title">What the agent will not do</h2>
            <ul className="safeguards">
              {SAFEGUARDS.map((item) => (
                <li key={item.title}>
                  <h3>{item.title}</h3>
                  <p>{item.text}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="band" id="start" aria-labelledby="start-title">
          <div className="band-inner">
            <h2 id="start-title">Pick a view</h2>
            <nav className="doors" aria-label="Choose a view">
              <a className="door" href={VIEWS.customer}>
                <span className="door-title">I&rsquo;m a customer</span>
                <span className="door-text">Report a damaged, late or missing order and get an answer.</span>
              </a>
              <a className="door" href={VIEWS.internal}>
                <span className="door-title">I review cases</span>
                <span className="door-text">See each recommendation, the evidence and policy behind it, and decide.</span>
              </a>
            </nav>
          </div>
        </section>
      </main>

      <footer className="foot">
        <span>Cosmic Resolve, a Cosmic Mart prototype.</span>
        <span>Demo environment. Refunds, replacements and messages are simulated.</span>
      </footer>
    </div>
  );
}
