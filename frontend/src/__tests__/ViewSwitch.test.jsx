import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import ViewSwitch, { VIEW_URLS } from "../components/ViewSwitch.jsx";

describe("ViewSwitch", () => {
  it("links to both views and marks the current one", () => {
    render(<ViewSwitch current="internal" />);
    const internal = screen.getByRole("link", { name: "Internal" });
    const customer = screen.getByRole("link", { name: "Customer" });
    expect(internal).toHaveAttribute("href", VIEW_URLS.internal);
    expect(customer).toHaveAttribute("href", VIEW_URLS.customer);
    expect(screen.getByRole("link", { name: "Internal" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Customer" })).not.toHaveAttribute("aria-current");
  });
});
