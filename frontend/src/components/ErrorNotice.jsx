// Concise error with an optional retry that re-runs the request that failed. No stack traces.
export default function ErrorNotice({ title, detail, onRetry }) {
  return (
    <div className="notice notice-error" role="alert">
      <p className="notice-title">{title}</p>
      {detail ? <p className="notice-detail">{detail}</p> : null}
      {onRetry ? (
        <button type="button" className="button" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}
