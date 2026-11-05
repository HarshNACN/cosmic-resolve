import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "../App.jsx";

// On the landing page the brand goes to the root page itself, not to an in-page "#top" anchor.
describe("the landing header brand", () => {
  it("links to / and not to #top", () => {
    render(<App />);
    const brand = screen.getByRole("link", { name: "Cosmic Resolve home" });
    expect(brand).toHaveAttribute("href", "/");
    expect(brand.getAttribute("href")).not.toContain("#");
    expect(brand).toHaveTextContent("Cosmic Resolve");
    expect(window.location.hash).toBe("");
  });
});
