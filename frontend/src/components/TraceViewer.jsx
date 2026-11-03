import ErrorNotice from "./ErrorNotice.jsx";
import TraceEvent from "./TraceEvent.jsx";

export default function TraceViewer({ caseId, state, onRetry }) {
  const events = Array.isArray(state.data) ? state.data : null;
  const refreshing = state.status === "loading" && events !== null;

  return (
    <section className="panel" aria-labelledby="trace-heading" aria-busy={state.status === "loading"}>
      <h2 id="trace-heading">Activity trace</h2>
      <p className="muted">
        Trace details may contain customer or model-generated content. Events from every run of this case are listed
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
      {events && events.length > 0 ? (
        <ol className="trace-list">
          {events.map((event, index) => (
            <TraceEvent key={`${event.timestamp}-${index}`} event={event} />
          ))}
        </ol>
      ) : null}
    </section>
  );
}
