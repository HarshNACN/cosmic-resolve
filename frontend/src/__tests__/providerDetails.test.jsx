import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ProposalPanel from "../components/ProposalPanel.jsx";

const PROPOSAL = {
  case_id: "C-1001",
  decision: "REFUND",
  amount: 42,
  policy_clause_ids: ["US-GAD-DOA-01"],
  evidence: ["Shipment T-1001 status: DELIVERED"],
  confidence: 0.9,
  escalation_reasons: [],
  customer_message_draft: "We are sorry the item arrived damaged.",
  root_cause: { category: "CARRIER_DAMAGE", detail: "Packaging" },
};

function run(overrides = {}) {
  return {
    case_id: "C-1001",
    status: "AWAITING_APPROVAL",
    error: null,
    provider: "bedrock",
    execution_mode: "agentic",
    pipeline: "agent",
    proposal: PROPOSAL,
    proposal_fingerprint: "a".repeat(64),
    recommended_action: null,
    checkpoint_writes_enabled: false,
    ...overrides,
  };
}

function renderPanel(data) {
  return render(
    <ProposalPanel
      caseId="C-1001"
      state={{ status: "ready", data }}
      onGenerate={vi.fn()}
      decision={{ status: "idle" }}
      onDecide={vi.fn()}
    />,
  );
}

describe("provider metadata on the recommendation", () => {
  it("shows Amazon Bedrock and Agentic for the live agent path", () => {
    const { container } = renderPanel(run());
    const details = container.querySelector(".provider-details");
    expect(within(details).getByText("Provider")).toBeInTheDocument();
    expect(within(details).getByText("Amazon Bedrock")).toBeInTheDocument();
    expect(within(details).getByText("Mode")).toBeInTheDocument();
    expect(within(details).getByText("Agentic")).toBeInTheDocument();
  });

  it("shows Offline rules and no mode row for the deterministic path", () => {
    const { container } = renderPanel(run({ provider: "offline", execution_mode: "rule_based" }));
    const details = container.querySelector(".provider-details");
    expect(within(details).getByText("Offline rules")).toBeInTheDocument();
    expect(within(details).queryByText("Mode")).not.toBeInTheDocument();
  });

  it("shows Single-shot for the older one-call Bedrock path", () => {
    const { container } = renderPanel(run({ execution_mode: "single_shot" }));
    expect(within(container.querySelector(".provider-details")).getByText("Single-shot")).toBeInTheDocument();
  });

  it("shows no provider line for an unexpected value, and never prints the raw value", () => {
    const { container } = renderPanel(run({ provider: "<img src=x onerror=alert(1)>", execution_mode: "??" }));
    expect(container.querySelector(".provider-details")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).not.toContain("onerror");
  });

  it("shows the existing safe provider error when Bedrock fails, with no proposal and no offline substitute", () => {
    const { container } = renderPanel(
      run({
        status: "PROVIDER_ERROR",
        error: "Bedrock credentials have expired or are invalid.",
        proposal: null,
        proposal_fingerprint: null,
      }),
    );
    expect(within(container.querySelector(".provider-details")).getByText("Amazon Bedrock")).toBeInTheDocument();
    expect(screen.getByText(/Bedrock credentials have expired or are invalid\./)).toBeInTheDocument();
    expect(screen.queryByText("Decision")).not.toBeInTheDocument();
    expect(screen.queryByText("Offline rules")).not.toBeInTheDocument();
  });

  it("does not use marketing language about AI", () => {
    const { container } = renderPanel(run());
    expect(container.textContent).not.toMatch(/\bAI\b|intelligent|autonomous|powered|sparkle/i);
  });
});
