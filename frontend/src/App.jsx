import { useState } from "react";
import CaseDetails from "./components/CaseDetails.jsx";
import CaseQueue from "./components/CaseQueue.jsx";
import PolicyBasis from "./components/PolicyBasis.jsx";
import ProposalPanel from "./components/ProposalPanel.jsx";
import TraceViewer from "./components/TraceViewer.jsx";
import { useCaseWorkbench } from "./hooks/useCaseWorkbench.js";
import { useCases } from "./hooks/useCases.js";

// Read-only case workbench. It reads cases and traces and can request a recommendation, but it has no
// approval or write controls. Approval is enforced by the backend and is not part of this view.
export default function App() {
  const queue = useCases();
  const [selectedId, setSelectedId] = useState(null);
  const workbench = useCaseWorkbench(selectedId);

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
          <CaseDetails caseId={selectedId} state={workbench.detail} onRetry={workbench.retryDetail} />
          {selectedId ? (
            <>
              <ProposalPanel
                caseId={selectedId}
                state={workbench.proposal}
                onGenerate={workbench.generate}
                decision={workbench.decision}
                onDecide={workbench.decide}
              />
              <PolicyBasis state={workbench.proposal} />
              <TraceViewer caseId={selectedId} state={workbench.trace} onRetry={workbench.retryTrace} />
            </>
          ) : null}
        </main>
      </div>
    </div>
  );
}
