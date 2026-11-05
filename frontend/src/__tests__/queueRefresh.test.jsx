import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useCases } from "../hooks/useCases.js";

// Customers raise cases from the customer page, so the employee's queue refreshes quietly in the background: a new case
// appears without a reload, the list never flashes "loading", and an unchanged list is left exactly as it is.
const CASE = (id, status = "OPEN") => ({ case_id: id, order_id: "O-1", customer_id: "C-1", tracking_id: "T-1", case_type: "LATE_DELIVERY", market: "US", category: "GADGETS", complaint_text: "x", channel: "WEB", created_at: "2026-11-02T09:00:00Z", status });

function installCases(lists) {
  let calls = 0;
  vi.stubGlobal("fetch", vi.fn(async () => {
    const answer = lists[Math.min(calls, lists.length - 1)];
    calls += 1;
    if (answer === "fail") throw new Error("down");
    return { ok: true, status: 200, json: async () => answer };
  }));
  return () => calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the case queue refresh", () => {
  it("shows a case that arrives later, never goes back to loading, and keeps the list when nothing changed", async () => {
    const calls = installCases([[CASE("C-1001")], [CASE("C-1001")], [CASE("W-0001"), CASE("C-1001")]]);
    const seen = [];
    const { result } = renderHook(() => {
      const value = useCases({ refreshMs: 20 });
      seen.push(value.status);
      return value;
    });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    await waitFor(() => expect(result.current.cases.map((c) => c.case_id)).toEqual(["W-0001", "C-1001"]));
    expect(calls()).toBeGreaterThanOrEqual(3);
    expect(seen.slice(seen.indexOf("ready"))).not.toContain("loading"); // once loaded, the list never flashes "loading" again
  });

  it("leaves the very same list in place when a refresh finds nothing new", async () => {
    installCases([[CASE("C-1001")], [CASE("C-1001")], [CASE("C-1001")]]);
    const { result } = renderHook(() => useCases({ refreshMs: 20 }));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    const first = result.current.cases;
    await act(async () => new Promise((resolve) => setTimeout(resolve, 90)));
    expect(result.current.cases).toBe(first);
  });

  it("notices a case whose status changed, and ignores a refresh that fails", async () => {
    installCases([[CASE("C-1001")], "fail", [CASE("C-1001", "CLOSED")]]);
    const { result } = renderHook(() => useCases({ refreshMs: 20 }));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    await waitFor(() => expect(result.current.cases[0].status).toBe("CLOSED"));
    expect(result.current.status).toBe("ready");
    expect(result.current.error).toBeNull();
  });

  it("does not refresh at all unless asked to (the default)", async () => {
    const calls = installCases([[CASE("C-1001")]]);
    const { result } = renderHook(() => useCases());
    await waitFor(() => expect(result.current.status).toBe("ready"));
    await act(async () => new Promise((resolve) => setTimeout(resolve, 80)));
    expect(calls()).toBe(1);
  });
});
