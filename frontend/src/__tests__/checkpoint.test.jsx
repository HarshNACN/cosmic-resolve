import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App.jsx";
import {
  CASE_1001,
  CASE_1002,
  CHECKPOINT_ENABLED_RUN,
  CHECKPOINT_ENABLED_STORE_CREDIT_RUN,
  DECISION_APPROVED,
  DECISION_REJECTED,
  TRACE_1001,
  event,
  fail,
  installFetch,
  ok,
} from "../test/mockApi.js";

afterEach(() => {
  vi.unstubAllGlobals();
});

const FINGERPRINT_1002 = "b".repeat(64);

function routes(overrides = {}) {
  return {
    "GET /api/cases": () => ok([CASE_1001, CASE_1002]),
    "GET /api/cases/C-1001": () => ok(CASE_1001),
    "GET /api/cases/C-1002": () => ok(CASE_1002),
    "GET /api/cases/C-1001/trace": () => ok(TRACE_1001),
    "GET /api/cases/C-1002/trace": () => ok([]),
    "POST /api/cases/C-1002/propose": () => ok(CHECKPOINT_ENABLED_STORE_CREDIT_RUN),
    "POST /api/cases/C-1001/propose": () => ok(CHECKPOINT_ENABLED_RUN),
    ...overrides,
  };
}

async function openAndGenerate(user, id) {
  await user.click(await screen.findByRole("button", { name: new RegExp(id) }));
  await user.click(await screen.findByRole("button", { name: "Generate recommendation" }));
  await screen.findByRole("heading", { name: "Model-generated evidence" });
}

const approveButton = () => screen.queryByRole("button", { name: "Approve" });

describe("checkpoint capability", () => {
  it("shows the read-only message and no decision controls when the backend has checkpoints disabled", async () => {
    const user = userEvent.setup();
    installFetch(
      routes({
        "POST /api/cases/C-1002/propose": () =>
          ok({ ...CHECKPOINT_ENABLED_STORE_CREDIT_RUN, checkpoint_writes_enabled: false }),
      }),
    );
    render(<App />);
    await openAndGenerate(user, "C-1002");
    expect(screen.getByText("Decision controls are not enabled in this environment.")).toBeInTheDocument();
    expect(approveButton()).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit message" })).not.toBeInTheDocument();
  });

  it("shows Approve, Edit message and Reject when the backend enables checkpoints", async () => {
    const user = userEvent.setup();
    installFetch(routes());
    render(<App />);
    await openAndGenerate(user, "C-1002");
    expect(approveButton()).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit message" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
  });

  it("does not offer checkpoint controls when the proposal did not pass validation", async () => {
    const user = userEvent.setup();
    installFetch(
      routes({
        "POST /api/cases/C-1002/propose": () =>
          ok({ ...CHECKPOINT_ENABLED_STORE_CREDIT_RUN, status: "VALIDATION_FAILED", error: "Rule failed." }),
      }),
    );
    render(<App />);
    await openAndGenerate(user, "C-1002");
    expect(screen.getByText("This recommendation did not pass validation, so it cannot be approved.")).toBeInTheDocument();
    expect(approveButton()).not.toBeInTheDocument();
  });
});

describe("approve, edit and reject", () => {
  it("opens an approval confirmation that requires a reviewer name before it can be confirmed", async () => {
    const user = userEvent.setup();
    installFetch(routes());
    render(<App />);
    await openAndGenerate(user, "C-1002");
    await user.click(approveButton());
    expect(screen.getByText("Review approval")).toBeInTheDocument();
    const confirm = screen.getByRole("button", { name: "Confirm approval" });
    expect(confirm).toBeDisabled();
    await user.type(screen.getByLabelText("Reviewer name (required)"), "Jordan");
    expect(confirm).toBeEnabled();
  });

  it("sends only the allowed decision fields when approving", async () => {
    const user = userEvent.setup();
    const { bodies } = installFetch(
      routes({ "POST /api/cases/C-1002/decision": () => ok(DECISION_APPROVED) }),
    );
    render(<App />);
    await openAndGenerate(user, "C-1002");
    await user.click(approveButton());
    await user.type(screen.getByLabelText("Reviewer name (required)"), "  Jordan  ");
    await user.click(screen.getByRole("button", { name: "Confirm approval" }));
    await screen.findByText("Approved. Mock actions executed.");
    const sent = bodies.find((body) => body && body.action === "APPROVE");
    expect(Object.keys(sent).sort()).toEqual(["action", "proposal_fingerprint", "reviewer"]);
    expect(sent.reviewer).toBe("Jordan");
    expect(sent.proposal_fingerprint).toBe(FINGERPRINT_1002);
  });

  it("rejects with a confirmation, records no action, and says the case needs manual handling", async () => {
    const user = userEvent.setup();
    const { bodies } = installFetch(routes({ "POST /api/cases/C-1002/decision": () => ok(DECISION_REJECTED) }));
    render(<App />);
    await openAndGenerate(user, "C-1002");
    await user.click(screen.getByRole("button", { name: "Reject" }));
    await user.type(screen.getByLabelText("Reviewer name (required)"), "Jordan");
    await user.click(screen.getByRole("button", { name: "Confirm rejection" }));
    expect(await screen.findByText("Rejected. No resolution action was executed.")).toBeInTheDocument();
    expect(screen.getByText("The case requires manual handling.")).toBeInTheDocument();
    expect(screen.queryByText("Approved. Mock actions executed.")).not.toBeInTheDocument();
    expect(bodies.find((body) => body && body.action === "REJECT")).toEqual({
      action: "REJECT",
      proposal_fingerprint: FINGERPRINT_1002,
      reviewer: "Jordan",
    });
  });

  it("exposes only the customer message for editing", async () => {
    const user = userEvent.setup();
    installFetch(routes());
    render(<App />);
    await openAndGenerate(user, "C-1002");
    await user.click(screen.getByRole("button", { name: "Edit message" }));
    expect(screen.getByLabelText("Customer message (editable)")).toBeInTheDocument();
    expect(screen.queryByLabelText(/amount/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/decision/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/clause/i)).not.toBeInTheDocument();
  });

  it("refuses an empty edited message inline and does not enable review", async () => {
    const user = userEvent.setup();
    installFetch(routes());
    render(<App />);
    await openAndGenerate(user, "C-1002");
    await user.click(screen.getByRole("button", { name: "Edit message" }));
    await user.clear(screen.getByLabelText("Customer message (editable)"));
    expect(screen.getByText("The customer message cannot be empty.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review edit" })).toBeDisabled();
  });

  it("sends the trimmed edited message with the edit action", async () => {
    const user = userEvent.setup();
    const { bodies } = installFetch(
      routes({ "POST /api/cases/C-1002/decision": () => ok({ ...DECISION_APPROVED, action: "EDIT_AND_APPROVE" }) }),
    );
    render(<App />);
    await openAndGenerate(user, "C-1002");
    await user.click(screen.getByRole("button", { name: "Edit message" }));
    const editor = screen.getByLabelText("Customer message (editable)");
    await user.clear(editor);
    await user.type(editor, "  We are sorry for the delay.  ");
    await user.click(screen.getByRole("button", { name: "Review edit" }));
    await user.type(screen.getByLabelText("Reviewer name (required)"), "Jordan");
    await user.click(screen.getByRole("button", { name: "Confirm approval with edit" }));
    await screen.findByText("Approved. Mock actions executed.");
    const sent = bodies.find((body) => body && body.action === "EDIT_AND_APPROVE");
    expect(sent.edited_message).toBe("We are sorry for the delay.");
    expect(Object.keys(sent).sort()).toEqual(["action", "edited_message", "proposal_fingerprint", "reviewer"]);
  });

  it("shows a backend validation message inline when the decision is refused", async () => {
    const user = userEvent.setup();
    installFetch(
      routes({
        "POST /api/cases/C-1002/decision": () =>
          fail(409, { detail: "The proposal has changed since it was generated. Regenerate the recommendation before deciding." }),
      }),
    );
    render(<App />);
    await openAndGenerate(user, "C-1002");
    await user.click(approveButton());
    await user.type(screen.getByLabelText("Reviewer name (required)"), "Jordan");
    await user.click(screen.getByRole("button", { name: "Confirm approval" }));
    expect(await screen.findByText("The decision was not recorded.")).toBeInTheDocument();
    expect(screen.getByText(/The proposal has changed since it was generated/)).toBeInTheDocument();
    expect(screen.queryByText("Approved. Mock actions executed.")).not.toBeInTheDocument();
  });

  it("shows the executed actions after a successful approval and removes the controls", async () => {
    const user = userEvent.setup();
    installFetch(routes({ "POST /api/cases/C-1002/decision": () => ok(DECISION_APPROVED) }));
    render(<App />);
    await openAndGenerate(user, "C-1002");
    await user.click(approveButton());
    await user.type(screen.getByLabelText("Reviewer name (required)"), "Jordan");
    await user.click(screen.getByRole("button", { name: "Confirm approval" }));
    const result = await screen.findByText("Approved. Mock actions executed.");
    const list = result.parentElement.querySelector(".executed-list");
    expect(within(list).getByText(/Issue store credit/)).toBeInTheDocument();
    expect(within(list).getByText(/Send customer message/)).toBeInTheDocument();
    expect(approveButton()).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
  });

  it("shows the in-progress state and no repeat controls while the decision is recorded", async () => {
    const user = userEvent.setup();
    let release;
    const pending = new Promise((resolve) => {
      release = resolve;
    });
    installFetch(routes({ "POST /api/cases/C-1002/decision": () => pending }));
    render(<App />);
    await openAndGenerate(user, "C-1002");
    await user.click(approveButton());
    await user.type(screen.getByLabelText("Reviewer name (required)"), "Jordan");
    await user.click(screen.getByRole("button", { name: "Confirm approval" }));
    expect(await screen.findByText("Recording decision...")).toBeInTheDocument();
    expect(approveButton()).not.toBeInTheDocument();
    release(ok(DECISION_APPROVED));
    await screen.findByText("Approved. Mock actions executed.");
  });
});

describe("trace and case switching", () => {
  it("refreshes the trace after a decision so the new actions appear in the timeline", async () => {
    const user = userEvent.setup();
    let traceReturnsActions = false;
    const actionsEvent = event("actions_executed", "Gated write actions executed", {
      decision: "STORE_CREDIT",
      actions: [{ action: "issue_store_credit", amount: 45 }],
    });
    const { calls } = installFetch(
      routes({
        "GET /api/cases/C-1002/trace": () =>
          ok(
            traceReturnsActions
              ? [
                  event("case_loaded", "Case loaded", { case_id: "C-1002" }),
                  event("human_decision", "Approved", { case_id: "C-1002", action: "APPROVE" }),
                  actionsEvent,
                ]
              : [],
          ),
        "POST /api/cases/C-1002/decision": () => {
          traceReturnsActions = true;
          return ok(DECISION_APPROVED);
        },
      }),
    );
    render(<App />);
    await openAndGenerate(user, "C-1002");
    const before = calls.filter((c) => c === "GET /api/cases/C-1002/trace").length;
    await user.click(approveButton());
    await user.type(screen.getByLabelText("Reviewer name (required)"), "Jordan");
    await user.click(screen.getByRole("button", { name: "Confirm approval" }));
    await screen.findByText("Approved. Mock actions executed.");
    await waitFor(() => {
      expect(calls.filter((c) => c === "GET /api/cases/C-1002/trace").length).toBeGreaterThan(before);
    });
    const trace = await screen.findByRole("region", { name: "Run 1" });
    expect(within(trace).getByText("Actions executed")).toBeInTheDocument();
  });

  it("clears the checkpoint result when another case is selected", async () => {
    const user = userEvent.setup();
    installFetch(routes({ "POST /api/cases/C-1002/decision": () => ok(DECISION_APPROVED) }));
    render(<App />);
    await openAndGenerate(user, "C-1002");
    await user.click(approveButton());
    await user.type(screen.getByLabelText("Reviewer name (required)"), "Jordan");
    await user.click(screen.getByRole("button", { name: "Confirm approval" }));
    await screen.findByText("Approved. Mock actions executed.");

    await user.click(screen.getByRole("button", { name: /C-1001/ }));
    await screen.findByRole("button", { name: "Generate recommendation" });
    expect(screen.queryByText("Approved. Mock actions executed.")).not.toBeInTheDocument();
  });
});

describe("safe rendering and escalation presentation", () => {
  it("renders hostile edited-message text as text, never as markup", async () => {
    const user = userEvent.setup();
    const hostile = '<img src=x onerror="window.__owned=1"><b>bold</b>';
    installFetch(routes());
    const { container } = render(<App />);
    await openAndGenerate(user, "C-1002");
    await user.click(screen.getByRole("button", { name: "Edit message" }));
    const editor = screen.getByLabelText("Customer message (editable)");
    await user.clear(editor);
    await user.type(editor, hostile);
    await user.click(screen.getByRole("button", { name: "Review edit" }));
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(window.__owned).toBeUndefined();
  });

  it("shows the recommended action only when the backend returned one", async () => {
    const user = userEvent.setup();
    installFetch(routes());
    render(<App />);
    await openAndGenerate(user, "C-1001");
    expect(screen.getByText("Manual review required: Value > $200 threshold")).toBeInTheDocument();
    expect(screen.getByText("Recommended action")).toBeInTheDocument();
  });

  it("does not invent a recommended action for a non-escalation", async () => {
    const user = userEvent.setup();
    installFetch(routes());
    render(<App />);
    await openAndGenerate(user, "C-1002");
    expect(screen.queryByText("Recommended action")).not.toBeInTheDocument();
  });

  it("offers no edit control for an escalation, since no message is sent for it", async () => {
    const user = userEvent.setup();
    installFetch(routes());
    render(<App />);
    await openAndGenerate(user, "C-1001");
    expect(screen.getByRole("button", { name: "Edit message" })).toBeDisabled();
    expect(screen.getByText(/Escalations do not send a customer message/)).toBeInTheDocument();
  });
});
