import { describe, expect, it } from "vitest";
import { groupTraceRuns } from "../format.js";

const ev = (event_type, timestamp = "2026-11-02T10:00:00+00:00") => ({ event_type, timestamp, message: event_type, details: {} });

describe("groupTraceRuns", () => {
  it("returns no runs for an empty trace", () => {
    expect(groupTraceRuns([])).toEqual([]);
  });

  it("starts a new run at each case_loaded event and keeps events in order", () => {
    const runs = groupTraceRuns([
      ev("case_loaded", "t1"),
      ev("context_gathered"),
      ev("validation_passed"),
      ev("case_loaded", "t2"),
      ev("provider_request"),
    ]);
    expect(runs).toHaveLength(2);
    expect(runs[0].startedAt).toBe("t1");
    expect(runs[0].events.map((e) => e.event_type)).toEqual(["case_loaded", "context_gathered", "validation_passed"]);
    expect(runs[1].startedAt).toBe("t2");
    expect(runs[1].events.map((e) => e.event_type)).toEqual(["case_loaded", "provider_request"]);
  });

  it("puts events that precede the first case_loaded into an untitled earlier group", () => {
    const runs = groupTraceRuns([ev("provider_error"), ev("case_loaded", "t2"), ev("validation_failed")]);
    expect(runs).toHaveLength(2);
    expect(runs[0].startedAt).toBeNull();
    expect(runs[0].events.map((e) => e.event_type)).toEqual(["provider_error"]);
    expect(runs[1].startedAt).toBe("t2");
  });

  it("does not reorder or drop events", () => {
    const input = [ev("case_loaded"), ev("a"), ev("case_loaded"), ev("b"), ev("c")];
    const flattened = groupTraceRuns(input).flatMap((run) => run.events);
    expect(flattened).toEqual(input);
  });

  it("marks only case_loaded groups as runs, so earlier activity is never numbered", () => {
    const runs = groupTraceRuns([ev("provider_error"), ev("case_loaded", "t2")]);
    expect(runs.map((run) => run.isRun)).toEqual([false, true]);
  });

  it("still starts a run for a case_loaded event that has no timestamp", () => {
    const runs = groupTraceRuns([{ event_type: "case_loaded", message: "Case loaded", details: {} }]);
    expect(runs).toHaveLength(1);
    expect(runs[0].isRun).toBe(true);
    expect(runs[0].startedAt).toBeUndefined();
  });

  it("does not mutate its input", () => {
    const input = [ev("case_loaded", "t1"), ev("a"), ev("case_loaded", "t2"), ev("b")];
    const before = structuredClone(input);
    groupTraceRuns(input);
    expect(input).toEqual(before);
  });
});
