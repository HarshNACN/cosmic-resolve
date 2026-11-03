import ErrorNotice from "./ErrorNotice.jsx";
import TraceEvent from "./TraceEvent.jsx";
import { formatTimestamp, groupTraceRuns } from "../format.js";

export default function TraceViewer({ caseId, state, onRetry }) {
  const events = Array.isArray(state.data) ? state.data : null;
  const refreshing = state.status === "loading" && events !== null;
  const runs = events ? groupTraceRuns(events) : [];
  // Number only real runs; the earlier-activity group (if any) is never numbered.
  let runNumber = 0;

  return (
    <section className="panel" aria-labelledby="trace-heading" aria-busy={state.status === "loading"}>
      <h2 id="trace-heading">Activity trace</h2>
      <p className="muted">
        Trace details may contain customer or model-generated content. Each run starts at Case loaded and is listed
        oldest first.
      </p>

      {!caseId ? <p>Select a case to see its activity.</p> : null}
      {caseId && state.status === "loading" && !events ? <p role="status">Loading activity trace...</p> : null}
      {refreshing ? (
        <p role="status" className="muted">
          Refreshing...
        </p>
      ) : null}
      {state.status === "error" ? (
        <ErrorNotice title="Unable to load the activity trace." detail={state.error} onRetry={onRetry} />
      ) : null}
      {events && events.length === 0 ? <p>No activity recorded for this case yet.</p> : null}
      {runs.map((run, index) => {
        if (run.isRun) runNumber += 1;
        const title = run.isRun ? `Run ${runNumber}` : "Earlier activity";
        return (
          <section className="trace-run" key={`${run.isRun ? "run" : "earlier"}-${index}`} aria-label={title}>
            <h3 className="run-title">
              {title}
              {run.isRun && run.startedAt ? <time className="run-time">{formatTimestamp(run.startedAt)}</time> : null}
            </h3>
            <ol className="trace-list">
              {run.events.map((event, eventIndex) => (
                <TraceEvent key={`${event.timestamp}-${eventIndex}`} event={event} />
              ))}
            </ol>
          </section>
        );
      })}
    </section>
  );
}
