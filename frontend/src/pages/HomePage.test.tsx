import { cleanup, render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, expect, test } from "vitest";
import { HomePage } from "./HomePage";

afterEach(cleanup);

function renderHome() {
  const router = createMemoryRouter([{ path: "/", element: <HomePage /> }], { initialEntries: ["/"] });
  render(<RouterProvider router={router} />);
}

test("the start page leads with the tagline and the compare form", () => {
  renderHome();
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("See what you’re merging.");
  const form = screen.getByRole("form", { name: "Compare releases" });
  expect(within(form).getByRole("button", { name: "Compare" })).toBeTruthy();
});

test("the example release diff is marked as invented", () => {
  renderHome();
  const example = screen.getByRole("figure", { name: /package, its releases and its code are invented/ });
  expect(within(example).getByText("Invented example")).toBeTruthy();
  expect(within(example).getAllByText("High")).toHaveLength(4);
  expect(within(example).getByText("+_telemetry.start()").className).toBe("add");
  expect(within(example).getByText("1 file not in tag").className).toBe("changed");
});

test("every section is a labeled region, and the nav links to the main ones", () => {
  renderHome();
  const ids = screen.getAllByRole("region").map((r) => r.getAttribute("aria-labelledby"));
  expect(ids).toEqual(["why", "pillars", "how", "who", "results", "status", "final"]);
  const nav = screen.getByRole("navigation", { name: "Sections" });
  for (const id of ["why", "how", "results"]) {
    expect(nav.querySelector(`a[href="#${id}"]`)).not.toBeNull();
  }
});

test("audiences mark what isn't available yet, and the numbers link to their research", () => {
  renderHome();
  const who = screen.getByRole("region", { name: "One view, four jobs." });
  expect(within(who).getByText("Coming")).toBeTruthy();
  expect(within(who).getByText("Later")).toBeTruthy();
  const results = screen.getByRole("region", { name: "Tuned against real releases." });
  const hrefs = within(results)
    .getAllByRole("link")
    .map((a) => a.getAttribute("href"));
  expect(hrefs).toEqual([
    "https://github.com/aesir-oss/sightglass/blob/main/docs/research/routine-sample.md",
    "https://github.com/aesir-oss/sightglass/blob/main/docs/research/tag-discovery.md",
    "https://github.com/aesir-oss/sightglass/blob/main/docs/research/pypi-publisher-data.md",
  ]);
});
