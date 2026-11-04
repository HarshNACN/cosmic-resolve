import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App.jsx";
import { generateProposal } from "../api.js";
import {
  CASE_1001,
  CASE_1002,
  CHECKPOINT_ENABLED_RUN,
  CHECKPOINT_ENABLED_STORE_CREDIT_RUN,
  installFetch,
  ok,
} from "../test/mockApi.js";

afterEach(() => {
  vi.unstubAllGlobals();
});

function routes(propose) {
  return {
    "GET /api/cases": () => ok([CASE_1001, CASE_1002]),
    "GET /api/cases/C-1001": () => ok(CASE_1001),
    "GET /api/cases/C-1002": () => ok(CASE_1002),
    "GET /api/cases/C-1001/trace": () => ok([]),
    "GET /api/cases/C-1002/trace": () => ok([]),
    "POST /api/cases/C-1002/propose": () => ok(propose),
  };
}

describe("propose normalizer", () => {
  it("passes the provenance fields through from the backend", async () => {
    installFetch(routes(CHECKPOINT_ENABLED_STORE_CREDIT_RUN));
    const result = await generateProposal("C-1002");
    expect(result.provider).toBe("agent");
    expect(result.tool_calls).toBe(3);
  });

  it("returns null provenance when the backend sends none, and rejects a non-integer tool count", async () => {
    installFetch(routes({ ...CHECKPOINT_ENABLED_RUN, provider: undefined, tool_calls: "3" }));
    const result = await generateProposal("C-1002");
    expect(result.provider).toBeNull();
    expect(result.tool_calls).toBeNull();
  });
});

async function generateFor(propose) {
  const user = userEvent.setup();
  installFetch(routes(propose));
  render(<App />);
  await user.click(await screen.findByRole("button", { name: /C-1002/ }));
  await user.click(await screen.findByRole("button", { name: "Generate recommendation" }));
  await screen.findByRole("heading", { name: "Model-generated evidence" });
}

describe("provenance line in the proposal panel", () => {
  it("says the Claude agent made the recommendation and how many tool calls it used", async () => {
    await generateFor(CHECKPOINT_ENABLED_STORE_CREDIT_RUN);
    expect(screen.getByText("Recommended by the Claude agent, 3 tool calls")).toBeInTheDocument();
  });

  it("says the offline rule-based provider made the recommendation", async () => {
    await generateFor({ ...CHECKPOINT_ENABLED_STORE_CREDIT_RUN, provider: "rules", tool_calls: null });
    expect(screen.getByText("Offline rule-based")).toBeInTheDocument();
    expect(screen.queryByText(/Claude agent/)).not.toBeInTheDocument();
  });
});
