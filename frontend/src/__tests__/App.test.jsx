import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App.jsx";
import {
  CASE_1001,
  CASE_1002,
  ESCALATE_RUN,
  STORE_CREDIT_RUN,
  TRACE_1001,
  deferred,
  event,
  fail,
  installFetch,
  ok,
} from "../test/mockApi.js";

afterEach(() => {
  vi.unstubAllGlobals();
});

const baseRoutes = (overrides = {}) => ({
  "GET /api/cases": () => ok([CASE_1001, CASE_1002]),
  "GET /api/cases/C-1001": () => ok(CASE_1001),
  "GET /api/cases/C-1001/trace": () => ok(TRACE_1001),
  "GET /api/cases/C-1002": () => ok(CASE_1002),
  "GET /api/cases/C-1002/trace": () => ok([]),
  ...overrides,
});

async function openCase(user, id) {
  await user.click(await screen.findByRole("button", { name: new RegExp(id) }));
}

describe("case queue", () => {
  it("renders the case list from the API", async () => {
    installFetch(baseRoutes());
    render(<App />);
    expect(screen.getByText("Loading cases...")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /C-1001/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /C-1002/ })).toBeInTheDocument();
    expect(screen.getByText("Showing 2 of 2 cases")).toBeInTheDocument();
  });

  it("shows an empty state when there are no cases", async () => {
    installFetch(baseRoutes({ "GET /api/cases": () => ok([]) }));
    render(<App />);
    expect(await screen.findByText("No cases in the queue.")).toBeInTheDocument();
  });

  it("shows an error with a retry that re-requests the list", async () => {
    const user = userEvent.setup();
    let attempt = 0;
    installFetch(baseRoutes({ "GET /api/cases": () => (++attempt === 1 ? fail(500) : ok([CASE_1001])) }));
    render(<App />);
    expect(await screen.findByText("Unable to load cases.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("button", { name: /C-1001/ })).toBeInTheDocument();
    expect(attempt).toBe(2);
  });

  it("treats a malformed list as an error", async () => {
    installFetch(baseRoutes({ "GET /api/cases": () => ok({ not: "a list" }) }));
    render(<App />);
    expect(await screen.findByText("Unable to load cases.")).toBeInTheDocument();
  });

  it("filters by case ID or complaint text and by case type", async () => {
    const user = userEvent.setup();
    installFetch(baseRoutes());
    render(<App />);
    await screen.findByRole("button", { name: /C-1001/ });

    await user.type(screen.getByLabelText("Search by case ID or complaint"), "lost in transit");
    expect(screen.queryByRole("button", { name: /C-1001/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /C-1002/ })).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Search by case ID or complaint"));
    await user.selectOptions(screen.getByLabelText("Case type"), "DAMAGED_ON_ARRIVAL");
    expect(screen.getByRole("button", { name: /C-1001/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /C-1002/ })).not.toBeInTheDocument();
  });
});

describe("selected case", () => {
  it("loads case details and marks the selection", async () => {
    const user = userEvent.setup();
    installFetch(baseRoutes());
    render(<App />);
    await openCase(user, "C-1001");

    expect(await screen.findByText(CASE_1001.complaint_text, { selector: "p" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /C-1001/ })).toHaveAttribute("aria-current", "true");
    const evidence = screen.getByRole("region", { name: "Evidence" });
    expect(within(evidence).getByText("O-1001")).toBeInTheDocument();
    expect(within(evidence).getAllByText(/not available/i).length).toBeGreaterThan(0);
  });

  it("keeps the case visible when only the trace fails, and retries just the trace", async () => {
    const user = userEvent.setup();
    let attempt = 0;
    installFetch(
      baseRoutes({ "GET /api/cases/C-1001/trace": () => (++attempt === 1 ? fail(500) : ok(TRACE_1001)) }),
    );
    render(<App />);
    await openCase(user, "C-1001");

    expect(await screen.findByText("Unable to load the activity trace.")).toBeInTheDocument();
    expect(screen.getByText(CASE_1001.complaint_text, { selector: "p" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Case loaded")).toBeInTheDocument();
  });

  it("shows a case error with retry when details fail", async () => {
    const user = userEvent.setup();
    let attempt = 0;
    installFetch(baseRoutes({ "GET /api/cases/C-1001": () => (++attempt === 1 ? fail(404) : ok(CASE_1001)) }));
    render(<App />);
    await openCase(user, "C-1001");
    expect(await screen.findByText("Unable to load this case.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText(CASE_1001.complaint_text, { selector: "p" })).toBeInTheDocument();
  });
});

describe("recommendation", () => {
  it("does not request a recommendation until asked, then shows it with policy IDs", async () => {
    const user = userEvent.setup();
    const { calls } = installFetch(
      baseRoutes({
        "GET /api/cases/C-1002": () => ok(CASE_1002),
        "POST /api/cases/C-1002/propose": () => ok(STORE_CREDIT_RUN),
      }),
    );
    render(<App />);
    await openCase(user, "C-1002");
    await screen.findByRole("button", { name: "Generate recommendation" });
    expect(calls).not.toContain("POST /api/cases/C-1002/propose");

    await user.click(screen.getByRole("button", { name: "Generate recommendation" }));
    const panel = await screen.findByText("Store credit");
    expect(panel).toBeInTheDocument();
    expect(screen.getByText("$45.00")).toBeInTheDocument();
    expect(screen.getByText("86%")).toBeInTheDocument();
    expect(screen.getByText(/Passed\. Waiting for a human decision/)).toBeInTheDocument();
    expect(screen.queryByText("Needs human review")).not.toBeInTheDocument();

    const policy = screen.getByRole("region", { name: "Policy basis" });
    expect(within(policy).getByText("US-GAD-LD-01")).toBeInTheDocument();
    expect(within(policy).getByText("Policy clause details are not included in the current API response.")).toBeInTheDocument();
  });

  it("marks escalations as needing human review and offers no approval controls", async () => {
    const user = userEvent.setup();
    installFetch(baseRoutes({ "POST /api/cases/C-1001/propose": () => ok(ESCALATE_RUN) }));
    render(<App />);
    await openCase(user, "C-1001");
    await user.click(await screen.findByRole("button", { name: "Generate recommendation" }));

    expect(await screen.findByRole("heading", { name: "Needs human review" })).toBeInTheDocument();
    expect(screen.getByText("Value > $200 threshold")).toBeInTheDocument();
    expect(screen.getByText("$649.00")).toBeInTheDocument();
    expect(screen.getByText("Human approval controls are not enabled in this view.")).toBeInTheDocument();
    for (const name of [/approve/i, /reject/i, /refund/i, /execute/i, /send/i]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
  });

  it("shows a validation failure without presenting it as valid", async () => {
    const user = userEvent.setup();
    installFetch(
      baseRoutes({
        "POST /api/cases/C-1001/propose": () =>
          ok({ ...ESCALATE_RUN, status: "VALIDATION_FAILED", error: "ESCALATE decisions require at least one escalation reason." }),
      }),
    );
    render(<App />);
    await openCase(user, "C-1001");
    await user.click(await screen.findByRole("button", { name: "Generate recommendation" }));
    expect(await screen.findByText(/Failed\. ESCALATE decisions require/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Needs human review" })).toBeInTheDocument();
  });

  it("handles a run with no proposal", async () => {
    const user = userEvent.setup();
    installFetch(
      baseRoutes({
        "POST /api/cases/C-1001/propose": () =>
          ok({ case_id: "C-1001", status: "NO_POLICY", error: "No policy clauses for market=US", proposal: null }),
      }),
    );
    render(<App />);
    await openCase(user, "C-1001");
    await user.click(await screen.findByRole("button", { name: "Generate recommendation" }));
    expect(await screen.findByText(/Not run\. No policy clauses/)).toBeInTheDocument();
    expect(screen.getByText("This run did not produce a proposal, so no policy clauses are cited.")).toBeInTheDocument();
  });

  it("shows a recommendation error with a retry that calls the endpoint again", async () => {
    const user = userEvent.setup();
    let attempt = 0;
    installFetch(
      baseRoutes({ "POST /api/cases/C-1001/propose": () => (++attempt === 1 ? fail(500) : ok(ESCALATE_RUN)) }),
    );
    render(<App />);
    await openCase(user, "C-1001");
    await user.click(await screen.findByRole("button", { name: "Generate recommendation" }));
    expect(await screen.findByText("Unable to generate a recommendation.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("$649.00")).toBeInTheDocument();
  });

  it("refreshes the trace after a recommendation is generated", async () => {
    const user = userEvent.setup();
    let traceCalls = 0;
    installFetch(
      baseRoutes({
        "GET /api/cases/C-1001/trace": () => (++traceCalls === 1 ? ok([]) : ok(TRACE_1001)),
        "POST /api/cases/C-1001/propose": () => ok(ESCALATE_RUN),
      }),
    );
    render(<App />);
    await openCase(user, "C-1001");
    expect(await screen.findByText("No activity recorded for this case yet.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Generate recommendation" }));
    expect(await screen.findByText("Case loaded")).toBeInTheDocument();
  });
});

describe("trace", () => {
  it("keeps prompts and model responses collapsed until expanded", async () => {
    const user = userEvent.setup();
    const exchange = event("model_exchange", "Full prompt and model response", {
      model_id: "test-profile",
      system_prompt: "SYSTEM-PROMPT-TEXT",
      user_message: "USER-MESSAGE-TEXT",
      response: { decision: "ESCALATE" },
    });
    installFetch(baseRoutes({ "GET /api/cases/C-1001/trace": () => ok([...TRACE_1001, exchange]) }));
    render(<App />);
    await openCase(user, "C-1001");

    expect(await screen.findByText("Full prompt and model response")).toBeInTheDocument();
    expect(screen.getByText(/model: test-profile/)).toBeInTheDocument();
    expect(screen.queryByText(/SYSTEM-PROMPT-TEXT/)).not.toBeInTheDocument();
    expect(screen.queryByText(/USER-MESSAGE-TEXT/)).not.toBeInTheDocument();

    const toggle = screen.getByRole("button", { name: /System prompt/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/SYSTEM-PROMPT-TEXT/)).toBeInTheDocument();
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/SYSTEM-PROMPT-TEXT/)).not.toBeInTheDocument();
  });

  it("labels validation and error events and shows the content notice", async () => {
    const user = userEvent.setup();
    installFetch(
      baseRoutes({
        "GET /api/cases/C-1001/trace": () =>
          ok([...TRACE_1001, event("provider_error", "Provider failed", { error: "boom" }), event("brand_new_type", "Unknown")]),
      }),
    );
    render(<App />);
    await openCase(user, "C-1001");
    expect(await screen.findByText("Passed")).toBeInTheDocument();
    expect(screen.getByText("Error", { selector: ".trace-status" })).toBeInTheDocument();
    expect(screen.getByText("Other")).toBeInTheDocument();
    expect(screen.getByText(/may contain customer or model-generated content/)).toBeInTheDocument();
  });
});

describe("untrusted content", () => {
  it("renders complaint, trace and model text as literal text, never as markup", async () => {
    const user = userEvent.setup();
    const hostile = '<img src=x onerror="window.__pwned=1"><script>window.__pwned=1</script><b>bold</b>';
    installFetch(
      baseRoutes({
        "GET /api/cases/C-1001": () => ok({ ...CASE_1001, complaint_text: hostile }),
        "GET /api/cases/C-1001/trace": () =>
          ok([event("model_exchange", hostile, { user_message: hostile, response: hostile })]),
        "POST /api/cases/C-1001/propose": () =>
          ok({
            ...ESCALATE_RUN,
            proposal: { ...ESCALATE_RUN.proposal, evidence: [hostile], customer_message_draft: hostile },
          }),
      }),
    );
    const { container } = render(<App />);
    await openCase(user, "C-1001");
    await user.click(await screen.findByRole("button", { name: "Generate recommendation" }));
    await screen.findByText("$649.00");
    for (const toggle of screen.getAllByRole("button", { name: /User message|Model response/ })) {
      await user.click(toggle);
    }

    expect(screen.getAllByText(hostile, { exact: false }).length).toBeGreaterThan(0);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(window.__pwned).toBeUndefined();
  });
});

describe("switching cases", () => {
  it("clears the previous proposal and trace when another case is selected", async () => {
    const user = userEvent.setup();
    installFetch(
      baseRoutes({
        "POST /api/cases/C-1001/propose": () => ok(ESCALATE_RUN),
      }),
    );
    render(<App />);
    await openCase(user, "C-1001");
    await user.click(await screen.findByRole("button", { name: "Generate recommendation" }));
    await screen.findByText("$649.00");
    expect(screen.getByText("Case loaded")).toBeInTheDocument();

    await openCase(user, "C-1002");
    await screen.findByText(CASE_1002.complaint_text, { selector: "p" });
    expect(screen.queryByText("$649.00")).not.toBeInTheDocument();
    expect(screen.queryByText("US-GAD-DOA-01")).not.toBeInTheDocument();
    expect(screen.queryByText("Case loaded")).not.toBeInTheDocument();
    expect(screen.getByText("No recommendation has been generated for this case yet.")).toBeInTheDocument();
  });

  it("ignores a late response for a case that is no longer selected", async () => {
    const user = userEvent.setup();
    const slowDetail = deferred();
    const slowTrace = deferred();
    installFetch(
      baseRoutes({
        "GET /api/cases/C-1001": () => slowDetail.promise,
        "GET /api/cases/C-1001/trace": () => slowTrace.promise,
      }),
    );
    render(<App />);
    await openCase(user, "C-1001");
    await openCase(user, "C-1002");
    await screen.findByText(CASE_1002.complaint_text, { selector: "p" });

    slowDetail.resolve(ok(CASE_1001));
    slowTrace.resolve(ok(TRACE_1001));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /C-1002/ })).toHaveAttribute("aria-current", "true");
    });
    expect(screen.queryByText(CASE_1001.complaint_text, { selector: "p" })).not.toBeInTheDocument();
    expect(screen.queryByText("Case loaded")).not.toBeInTheDocument();
  });

  it("cancels an in-flight recommendation when the selection changes", async () => {
    const user = userEvent.setup();
    const slowPropose = deferred();
    installFetch(baseRoutes({ "POST /api/cases/C-1001/propose": () => slowPropose.promise }));
    render(<App />);
    await openCase(user, "C-1001");
    await user.click(await screen.findByRole("button", { name: "Generate recommendation" }));
    expect(screen.getByText("Generating recommendation...")).toBeInTheDocument();

    await openCase(user, "C-1002");
    slowPropose.resolve(ok(ESCALATE_RUN));
    await screen.findByText(CASE_1002.complaint_text, { selector: "p" });
    expect(screen.queryByText("$649.00")).not.toBeInTheDocument();
    expect(screen.queryByText("Generating recommendation...")).not.toBeInTheDocument();
  });
});

describe("trace runs", () => {
  it("groups a repeated recommendation into a second run without merging the first", async () => {
    const user = userEvent.setup();
    const firstRun = [
      event("case_loaded", "Case loaded", {}, "2026-11-02T10:00:00+00:00"),
      event("validation_passed", "Proposal passed validation; awaiting human approval"),
    ];
    const secondRun = [
      ...firstRun,
      event("case_loaded", "Case loaded", {}, "2026-11-02T10:05:00+00:00"),
      event("validation_passed", "Proposal passed validation; awaiting human approval"),
    ];
    // The backend returns the full history on every request, so the second response contains both runs.
    let trace = [];
    installFetch(
      baseRoutes({
        "GET /api/cases/C-1001/trace": () => ok(trace),
        "POST /api/cases/C-1001/propose": () => ok(ESCALATE_RUN),
      }),
    );
    render(<App />);
    await openCase(user, "C-1001");
    await screen.findByRole("button", { name: "Generate recommendation" });

    trace = firstRun;
    await user.click(screen.getByRole("button", { name: "Generate recommendation" }));
    expect(await screen.findByRole("region", { name: "Run 1" })).toBeInTheDocument();

    trace = secondRun;
    await user.click(screen.getByRole("button", { name: "Generate recommendation" }));

    const run1 = await screen.findByRole("region", { name: "Run 1" });
    const run2 = await screen.findByRole("region", { name: "Run 2" });
    expect(within(run1).getAllByText("Case loaded")).toHaveLength(1);
    expect(within(run2).getAllByText("Case loaded")).toHaveLength(1);
    expect(within(run2).getByRole("heading", { name: /Run 2/ })).toBeInTheDocument();
  });

  it("shows events before any case_loaded under Earlier activity, unnumbered and in order", async () => {
    const user = userEvent.setup();
    installFetch(
      baseRoutes({
        "GET /api/cases/C-1001/trace": () =>
          ok([event("provider_error", "Provider failed", { error: "boom" }), event("case_loaded", "Case loaded")]),
      }),
    );
    render(<App />);
    await openCase(user, "C-1001");

    const earlier = await screen.findByRole("region", { name: "Earlier activity" });
    expect(within(earlier).getByText("Provider failed")).toBeInTheDocument();
    expect(within(earlier).queryByText("Case loaded")).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Run 1" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Run 0" })).not.toBeInTheDocument();
  });
});
