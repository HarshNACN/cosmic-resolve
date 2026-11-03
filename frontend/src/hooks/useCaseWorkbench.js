import { useCallback, useEffect, useRef, useState } from "react";
import { errorMessage, fetchCase, fetchTrace, generateProposal } from "../api.js";

const IDLE = { caseId: null, status: "idle", data: null, error: null };

// Each piece of state remembers which case it belongs to. A response for a previously selected case
// can therefore never be shown for the current one, even for a render before effects have run.
function forCase(state, caseId) {
  return state.caseId === caseId ? state : IDLE;
}

export function useCaseWorkbench(caseId) {
  const [detail, setDetail] = useState(IDLE);
  const [trace, setTrace] = useState(IDLE);
  const [proposal, setProposal] = useState(IDLE);
  const [detailTick, setDetailTick] = useState(0);
  const [traceTick, setTraceTick] = useState(0);
  const proposalController = useRef(null);

  // Case details: fetched when the selection changes or on retry.
  useEffect(() => {
    if (!caseId) return undefined;
    const controller = new AbortController();
    setDetail({ caseId, status: "loading", data: null, error: null });
    fetchCase(caseId, controller.signal)
      .then((data) => setDetail({ caseId, status: "ready", data, error: null }))
      .catch((error) => {
        if (controller.signal.aborted) return;
        setDetail({ caseId, status: "error", data: null, error: errorMessage(error, "Unable to load this case.") });
      });
    return () => controller.abort();
  }, [caseId, detailTick]);

  // Activity trace: independent of the case detail, so a failure here never hides the case.
  useEffect(() => {
    if (!caseId) return undefined;
    const controller = new AbortController();
    // Keep the events already on screen for the same case while refreshing; never for another case.
    setTrace((previous) => ({
      caseId,
      status: "loading",
      data: previous.caseId === caseId ? previous.data : null,
      error: null,
    }));
    fetchTrace(caseId, controller.signal)
      .then((data) => setTrace({ caseId, status: "ready", data, error: null }))
      .catch((error) => {
        if (controller.signal.aborted) return;
        setTrace({ caseId, status: "error", data: null, error: errorMessage(error, "Unable to load the activity trace.") });
      });
    return () => controller.abort();
  }, [caseId, traceTick]);

  // Changing the selected case discards any proposal and cancels one that is still in flight.
  useEffect(() => {
    setProposal(IDLE);
    return () => proposalController.current?.abort();
  }, [caseId]);

  const generate = useCallback(() => {
    if (!caseId) return;
    proposalController.current?.abort();
    const controller = new AbortController();
    proposalController.current = controller;
    setProposal({ caseId, status: "loading", data: null, error: null });
    generateProposal(caseId, controller.signal)
      .then((data) => {
        setProposal({ caseId, status: "ready", data, error: null });
        setTraceTick((value) => value + 1); // the run just added events to this case's trace
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setProposal({ caseId, status: "error", data: null, error: errorMessage(error, "Unable to generate a recommendation.") });
      });
  }, [caseId]);

  return {
    detail: forCase(detail, caseId),
    trace: forCase(trace, caseId),
    proposal: forCase(proposal, caseId),
    retryDetail: useCallback(() => setDetailTick((value) => value + 1), []),
    retryTrace: useCallback(() => setTraceTick((value) => value + 1), []),
    generate,
  };
}
