import { useMemo, useState } from "react";
import ErrorNotice from "./ErrorNotice.jsx";
import { humanize } from "../format.js";

const PREVIEW_LENGTH = 90;

function preview(text) {
  if (typeof text !== "string") return "";
  return text.length > PREVIEW_LENGTH ? `${text.slice(0, PREVIEW_LENGTH).trimEnd()}...` : text;
}

export default function CaseQueue({ status, cases, error, onRetry, selectedId, onSelect }) {
  const [query, setQuery] = useState("");
  const [caseType, setCaseType] = useState("");

  // Filter options come only from values present in the returned cases.
  const caseTypes = useMemo(
    () => [...new Set(cases.map((item) => item.case_type).filter((value) => typeof value === "string"))].sort(),
    [cases],
  );

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return cases.filter((item) => {
      if (caseType && item.case_type !== caseType) return false;
      if (!needle) return true;
      const id = String(item.case_id).toLowerCase();
      const complaint = typeof item.complaint_text === "string" ? item.complaint_text.toLowerCase() : "";
      return id.includes(needle) || complaint.includes(needle);
    });
  }, [cases, query, caseType]);

  return (
    <section className="panel queue" aria-labelledby="queue-heading">
      <h2 id="queue-heading">Case queue</h2>

      {status === "loading" ? (
        <p role="status">Loading cases...</p>
      ) : status === "error" ? (
        <ErrorNotice title="Unable to load cases." detail={error} onRetry={onRetry} />
      ) : cases.length === 0 ? (
        <p>No cases in the queue.</p>
      ) : (
        <>
          <div className="field">
            <label htmlFor="case-search">Search by case ID or complaint</label>
            <input
              id="case-search"
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              autoComplete="off"
            />
          </div>
          {caseTypes.length > 1 ? (
            <div className="field">
              <label htmlFor="case-type-filter">Case type</label>
              <select id="case-type-filter" value={caseType} onChange={(event) => setCaseType(event.target.value)}>
                <option value="">All case types</option>
                {caseTypes.map((value) => (
                  <option key={value} value={value}>
                    {humanize(value)}
                  </option>
                ))}
              </select>
            </div>
          ) : null}

          <p className="muted" role="status" aria-live="polite">
            Showing {visible.length} of {cases.length} cases
          </p>

          {visible.length === 0 ? (
            <p>No cases match the current search.</p>
          ) : (
            <ul className="case-list">
              {visible.map((item) => {
                const selected = item.case_id === selectedId;
                return (
                  <li key={item.case_id}>
                    <button
                      type="button"
                      className={selected ? "case-item selected" : "case-item"}
                      aria-current={selected ? "true" : undefined}
                      onClick={() => onSelect(item.case_id)}
                    >
                      <span className="case-item-head">
                        <span className="case-id">{item.case_id}</span>
                        {typeof item.status === "string" ? <span className="tag">{humanize(item.status)}</span> : null}
                      </span>
                      <span className="case-type">{humanize(item.case_type)}</span>
                      <span className="case-preview">{preview(item.complaint_text)}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
