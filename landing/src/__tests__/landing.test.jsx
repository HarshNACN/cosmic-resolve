import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import App, { SAFEGUARDS, STEPS, VIEWS } from "../App.jsx";
import { RADIUS, buildPoints, nearest, targetFor } from "../field.js";

describe("hero field geometry", () => {
  it("lays out the same jittered grid every time", () => {
    const first = buildPoints(300, 200);
    const second = buildPoints(300, 200);
    expect(first).toEqual(second);
    expect(first.length).toBeGreaterThan(50);
    const off = first.filter((p) => p.hx % 30 !== 0 || p.hy % 30 !== 0);
    expect(off.length).toBeGreaterThan(first.length / 2); // jittered, not a plain grid
  });

  it("leaves points at home when there is no pointer or it is far away", () => {
    const point = { hx: 100, hy: 100 };
    expect(targetFor(point, null)).toEqual({ x: 100, y: 100, pull: 0 });
    expect(targetFor(point, { x: 100 + RADIUS + 1, y: 100 })).toEqual({ x: 100, y: 100, pull: 0 });
  });

  it("draws nearby points inward and around the pointer", () => {
    const pointer = { x: 0, y: 0 };
    const target = targetFor({ hx: 60, hy: 0 }, pointer);
    expect(target.pull).toBeGreaterThan(0);
    expect(Math.hypot(target.x, target.y)).toBeLessThan(60); // pulled in
    expect(target.y).toBeGreaterThan(0); // turned, not just pushed straight
  });

  it("pulls harder the closer a point is", () => {
    const pointer = { x: 0, y: 0 };
    expect(targetFor({ hx: 20, hy: 0 }, pointer).pull).toBeGreaterThan(targetFor({ hx: 120, hy: 0 }, pointer).pull);
  });

  it("finds the closest points within reach, nearest first", () => {
    const points = [
      { x: 50, y: 0 },
      { x: 10, y: 0 },
      { x: 500, y: 0 },
      { x: 30, y: 0 },
    ];
    const found = nearest(points, { x: 0, y: 0 }, 100, 2).map((entry) => entry.point.x);
    expect(found).toEqual([10, 30]);
    expect(nearest(points, null, 100, 2)).toEqual([]);
  });
});

describe("landing page", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("says what the product does and offers both views", () => {
    render(<App />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("resolved with a person in charge");
    expect(screen.getByRole("link", { name: "Open the case workbench" })).toHaveAttribute("href", VIEWS.internal);
    expect(screen.getByRole("link", { name: "Report a problem as a customer" })).toHaveAttribute("href", VIEWS.customer);
  });

  it("routes to the paths Vercel and the dev proxy serve", () => {
    expect(VIEWS).toEqual({ internal: "/internal/", customer: "/support/" });
  });

  it("lists the five steps in order as a numbered list", () => {
    render(<App />);
    const list = screen.getByRole("heading", { name: "How a case gets resolved" }).closest("section").querySelector("ol");
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(STEPS.length);
    expect(items[0]).toHaveTextContent("A customer reports a problem");
    expect(items[items.length - 1]).toHaveTextContent("A person decides");
  });

  it("lists every safeguard", () => {
    render(<App />);
    for (const item of SAFEGUARDS) {
      expect(screen.getByRole("heading", { name: item.title })).toBeInTheDocument();
    }
  });

  it("offers both views again at the end of the page", () => {
    render(<App />);
    const doors = screen.getByRole("navigation", { name: "Choose a view" });
    expect(within(doors).getByRole("link", { name: /customer/i })).toHaveAttribute("href", VIEWS.customer);
    expect(within(doors).getByRole("link", { name: /review cases/i })).toHaveAttribute("href", VIEWS.internal);
  });

  it("keeps decoration away from assistive technology", () => {
    const { container } = render(<App />);
    expect(container.querySelector("canvas")).toHaveAttribute("aria-hidden", "true");
    expect(container.querySelector(".cursor-glow")).toHaveAttribute("aria-hidden", "true");
  });

  it("shows every step as reached when the browser cannot track scrolling", () => {
    vi.stubGlobal("IntersectionObserver", undefined);
    render(<App />);
    expect(document.querySelectorAll(".step.is-reached")).toHaveLength(STEPS.length);
  });

  it("lights each step as it scrolls to the middle of the screen, and never un-lights it", () => {
    let callback;
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(cb) {
          callback = cb;
        }
        observe() {}
        disconnect() {}
      },
    );
    render(<App />);
    const steps = document.querySelectorAll("[data-step]");
    expect(document.querySelectorAll(".step.is-reached")).toHaveLength(0);
    act(() => callback([{ isIntersecting: true, target: steps[2] }]));
    expect(document.querySelectorAll(".step.is-reached")).toHaveLength(3);
    act(() => callback([{ isIntersecting: true, target: steps[0] }]));
    expect(document.querySelectorAll(".step.is-reached")).toHaveLength(3);
  });

  it("follows the mouse with the glow but ignores touch", () => {
    const { container } = render(<App />);
    const glow = container.querySelector(".cursor-glow");
    fireEvent.pointerMove(window, { clientX: 10, clientY: 10, pointerType: "touch" });
    expect(glow).not.toHaveClass("is-on");
    fireEvent.pointerMove(window, { clientX: 120, clientY: 80, pointerType: "mouse" });
    expect(glow).toHaveClass("is-on");
    expect(glow.style.transform).toBe("translate(120px, 80px)");
  });
});
