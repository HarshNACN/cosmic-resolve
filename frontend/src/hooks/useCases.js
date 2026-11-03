import { useCallback, useEffect, useState } from "react";
import { errorMessage, fetchCases } from "../api.js";

export function useCases() {
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

  const reload = useCallback(() => setTick((value) => value + 1), []);
  return { ...state, reload };
}
