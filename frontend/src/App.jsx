import { useCallback, useState } from "react";
import CaseDetails from "./components/CaseDetails.jsx";
import CaseQueue from "./components/CaseQueue.jsx";
import PolicyBasis from "./components/PolicyBasis.jsx";
import ProposalPanel from "./components/ProposalPanel.jsx";
import TraceViewer from "./components/TraceViewer.jsx";
import { useCaseWorkbench } from "./hooks/useCaseWorkbench.js";
import { useCases } from "./hooks/useCases.js";
import CallPanel from "./voice/CallPanel.jsx";

// Read-only case workbench. It reads cases and traces and can request a recommendation, but it has no
// approval or write controls. Approval is enforced by the backend and is not part of this view.
export default function App() {
  const queue = useCases();
  const [selectedId, setSelectedId] = useState(null);
  const workbench = useCaseWorkbench(selectedId);
  const { reload: reloadQueue } = queue;
  // A confirmed voice call becomes a case: refresh the queue and open it, so the checkpoint is right below the call.
  const openVoiceCase = useCallback(
    (caseId) => {
      reloadQueue();
      setSelectedId(caseId);
    },
    [reloadQueue],
  );

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <div>
            <h1>Cosmic Resolve</h1>
            <p className="brand-sub">Cosmic Mart · Post-purchase resolution</p>
          </div>
        </div>
      </header>
      <div className="workbench">
        <CaseQueue
          status={queue.status}
          cases={queue.cases}
          error={queue.error}
          onRetry={queue.reload}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
        <main className="case-column" aria-label="Selected case">
          <CallPanel onCaseCreated={openVoiceCase} />
          {/* Page order: case identity, recommendation, evidence, policy, trace. */}
          <CaseDetails section="summary" caseId={selectedId} state={workbench.detail} onRetry={workbench.retryDetail} />
          {selectedId ? (
            <>
              <ProposalPanel
                caseId={selectedId}
                state={workbench.proposal}
                onGenerate={workbench.generate}
                decision={workbench.decision}
                onDecide={workbench.decide}
              />
              <CaseDetails section="evidence" caseId={selectedId} state={workbench.detail} />
              <PolicyBasis state={workbench.proposal} />
              <TraceViewer caseId={selectedId} state={workbench.trace} onRetry={workbench.retryTrace} />
            </>
          ) : null}
        </main>
      </div>
    </div>
  );
}
