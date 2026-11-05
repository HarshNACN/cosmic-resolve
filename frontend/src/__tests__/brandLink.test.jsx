import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App.jsx";

// The brand in the internal header is a real link to the Cosmic Resolve landing page ("/"), on the Cases and Eval views alike.
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the internal header brand", () => {
  it("links to / from the Cases view and from the Eval view", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, json: async () => [] })));
    render(<App />);
    const brand = () => screen.getByRole("link", { name: "Cosmic Resolve home" });
    expect(brand()).toHaveAttribute("href", "/"); // not /#top, /support/ or /internal/
    expect(brand()).toHaveTextContent("Cosmic Resolve");
    await user.click(screen.getByRole("button", { name: "Eval" }));
    expect(brand()).toHaveAttribute("href", "/");
    await user.click(screen.getByRole("button", { name: "Cases" }));
    expect(brand()).toHaveAttribute("href", "/");
    brand().focus();
    expect(brand()).toHaveFocus(); // reachable with the keyboard, a plain link so Enter follows it
  });
});
