import { useCallback, useEffect, useState } from "react";
import { errorMessage, fetchCases } from "../api.js";

// refreshMs > 0 turns on a quiet refresh: the list is re-read in the background and replaced only when a case was added or
// changed. It never shows "loading" again and never drops an error state, so the list does not flash. Off by default.
export function useCases({ refreshMs = 0 } = {}) {
  const [state, setState] = useState({ status: "loading", cases: [], error: null });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading", cases: [], error: null });
    fetchCases(controller.signal)
      .then((cases) => setState({ status: "ready", cases, error: null }))
      .catch((error) => {
        if (controller.signal.aborted) return;
        setState({ status: "error", cases: [], error: errorMessage(error, "Unable to load cases.") });
      });
    return () => controller.abort();
  }, [tick]);

  useEffect(() => {
    if (!refreshMs) return undefined;
    let active = true;
    const timer = setInterval(() => {
      fetchCases()
        .then((cases) => {
          if (!active) return;
          setState((current) => (current.status === "ready" && !sameCases(current.cases, cases) ? { ...current, cases } : current));
        })
        .catch(() => {}); // a missed refresh is not an error; the next one tries again
    }, refreshMs);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [refreshMs]);

  const reload = useCallback(() => setTick((value) => value + 1), []);
  return { ...state, reload };
}

const sameCases = (before, after) =>
  before.length === after.length && before.every((item, index) => item.case_id === after[index].case_id && item.status === after[index].status);
