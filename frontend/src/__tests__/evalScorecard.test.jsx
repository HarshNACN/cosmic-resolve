import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import EvalScorecard from "../components/EvalScorecard.jsx";

const RUN = {
  meta: { generated_at: "2026-11-04T15:48:15Z", provider: "bedrock", model_id: "m", case_count: 30 },
  metrics: {
    decision_accuracy: 0.9667,
    policy_citation_validity: 1,
    correct_escalation_rate: 1,
    unnecessary_escalation_rate: 0,
    false_refund_rate: 0,
    unsafe_remedy_count: 0,
    avg_tool_calls_per_case: 4.87,
  },
  denominators: { cases: 30 },
  mismatches: [{ case_id: "C-1011", expected: "GOODWILL_CREDIT", actual: "REPLACE", notes: "n" }],
};

afterEach(() => vi.unstubAllGlobals());

describe("EvalScorecard", () => {
  it("shows the latest run metrics and misses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ runs: [RUN] }) }));
    render(<EvalScorecard />);
    expect((await screen.findAllByText("96.7%")).length).toBeGreaterThan(0);
    expect(screen.getByText("Policy-citation validity")).toBeInTheDocument();
    expect(screen.getByText("C-1011")).toBeInTheDocument();
  });

  it("shows an error when the scorecard is unavailable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({ detail: "No eval scorecard is available." }) }),
    );
    render(<EvalScorecard />);
    expect(await screen.findByRole("alert")).toHaveTextContent("No eval scorecard");
  });
});
