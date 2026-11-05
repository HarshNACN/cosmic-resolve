import { useEffect, useState } from "react";
import { errorMessage, fetchScorecard } from "../api.js";

const pct = (value) => (typeof value === "number" ? `${Math.round(value * 1000) / 10}%` : "n/a");

// [label, metric key, format, "good" test]. Targets follow the PRD: citations 100%, no unsafe remedies.
const TILES = [
  ["Decision accuracy", "decision_accuracy", pct, (v) => v >= 0.9],
  ["Policy-citation validity", "policy_citation_validity", pct, (v) => v === 1],
  ["Correct escalation", "correct_escalation_rate", pct, (v) => v === 1],
  ["Unnecessary escalation", "unnecessary_escalation_rate", pct, (v) => v === 0],
  ["False-refund rate", "false_refund_rate", pct, (v) => v === 0],
  ["Unsafe remedies", "unsafe_remedy_count", (v) => String(v ?? "n/a"), (v) => v === 0],
  ["Avg tool calls / case", "avg_tool_calls_per_case", (v) => (typeof v === "number" ? v.toFixed(1) : "n/a"), () => true],
];

const when = (run) => (run.meta?.generated_at ? `${run.meta.generated_at.slice(0, 16).replace("T", " ")} UTC` : "unknown time");
const label = (run) => `${run.meta?.provider ?? "unknown"}${run.meta?.model_id ? ` · ${run.meta.model_id}` : ""}`;

export default function EvalScorecard() {
  const [state, setState] = useState({ status: "loading", runs: [], error: null });

  useEffect(() => {
    const controller = new AbortController();
    fetchScorecard(controller.signal)
      .then((runs) => setState({ status: "ready", runs, error: null }))
      .catch((error) => {
        if (controller.signal.aborted) return;
        setState({ status: "error", runs: [], error: errorMessage(error, "Unable to load the scorecard.") });
      });
    return () => controller.abort();
  }, []);

  if (state.status === "loading") return <p className="eval-note">Loading scorecard…</p>;
  if (state.status === "error") return <p role="alert" className="eval-note">{state.error}</p>;
  if (state.runs.length === 0) return <p className="eval-note">No eval runs recorded yet.</p>;

  const latest = state.runs[state.runs.length - 1];
  const caseCount = latest.denominators?.cases ?? latest.meta?.case_count;
  const mismatches = Array.isArray(latest.mismatches) ? latest.mismatches : [];

  return (
    <section className="eval-scorecard" aria-label="Eval scorecard">
      <h2>Eval scorecard</h2>
      <p className="eval-note">
        Latest run: {label(latest)} · {caseCount} synthetic cases · {when(latest)}
      </p>
      <ul className="eval-tiles">
        {TILES.map(([name, key, format, isGood]) => {
          const value = latest.metrics[key];
          return (
            <li key={key} className={`eval-tile ${typeof value === "number" && isGood(value) ? "is-good" : "is-watch"}`}>
              <span className="eval-tile-value">{format(value)}</span>
              <span className="eval-tile-label">{name}</span>
            </li>
          );
        })}
      </ul>

      <h3>Missed cases in the latest run</h3>
      {mismatches.length === 0 ? (
        <p className="eval-note">None. Every decision matched the expected outcome.</p>
      ) : (
        <ul className="eval-mismatches">
          {mismatches.map((m) => (
            <li key={m.case_id}>
              <strong>{m.case_id}</strong>: expected {m.expected}, got {m.actual}. {m.notes}
            </li>
          ))}
        </ul>
      )}

      <h3>Run history</h3>
      <table className="eval-history">
        <thead>
          <tr>
            <th>When</th>
            <th>Provider</th>
            <th>Accuracy</th>
            <th>Citations</th>
            <th>False refunds</th>
          </tr>
        </thead>
        <tbody>
          {[...state.runs].reverse().map((run, index) => (
            <tr key={`${run.meta?.generated_at}-${index}`}>
              <td>{when(run)}</td>
              <td>{label(run)}</td>
              <td>{pct(run.metrics.decision_accuracy)}</td>
              <td>{pct(run.metrics.policy_citation_validity)}</td>
              <td>{pct(run.metrics.false_refund_rate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
