import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { ReleaseSummary } from "../api/types";
import { Timeline } from "./Timeline";

afterEach(cleanup);

const publisher = {
  kind: "GitHub",
  repository: "kestrel-weather/orbit-client",
  workflow: "release.yml",
  environment: null,
};
const releases: ReleaseSummary[] = [
  { version: "2.4.0", published_at: "2025-11-01T00:00:00Z", yanked: false, attestation: "all", publisher },
  { version: "2.4.1", published_at: "2026-02-01T00:00:00Z", yanked: false, attestation: "all", publisher },
  { version: "2.5.0", published_at: "2026-09-30T00:00:00Z", yanked: true, attestation: "none", publisher: null },
  { version: "2.6.0", published_at: null, yanked: false, attestation: "unknown", publisher: null },
];

function renderTimeline(onCompare = vi.fn()) {
  render(<Timeline pkg="orbit-client" releases={releases} from="2.4.1" to="2.5.0" onCompare={onCompare} />);
  return onCompare;
}

test("each dated release is a labelled mark showing its publisher and attestation", () => {
  renderTimeline();
  const marks = screen.getAllByRole("button");
  expect(marks.map((m) => m.getAttribute("aria-label"))).toEqual([
    "2.4.0, Nov 1, 2025, published by release.yml in kestrel-weather/orbit-client, attested",
    "2.4.1, Feb 1, 2026, published by release.yml in kestrel-weather/orbit-client, attested",
    "2.5.0, Sep 30, 2026, no trusted publisher, not attested, yanked",
  ]);
  expect(screen.getByRole("group", { name: "Timeline of orbit-client releases" }).textContent).toContain("NO ATT");
  expect(screen.getByText("2026")).toBeTruthy();
  expect(document.querySelectorAll(".tl-g.end")).toHaveLength(2);
});

test("selecting a release compares it with its predecessor; shift makes it the start", () => {
  const onCompare = renderTimeline();
  const [first, second, third] = screen.getAllByRole("button");
  if (!first || !second || !third) throw new Error("missing marks");
  fireEvent.click(second);
  fireEvent.click(first);
  fireEvent.click(first, { shiftKey: true });
  fireEvent.keyDown(third, { key: "Enter" });
  fireEvent.keyDown(first, { key: "Enter", shiftKey: true });
  expect(onCompare.mock.calls).toEqual([
    ["2.4.0", "2.4.1"],
    ["2.4.0", "2.5.0"],
    ["2.4.1", "2.5.0"],
    ["2.4.0", "2.5.0"],
  ]);
});

test("the keyboard moves between releases, starting on the newer release of the pair", () => {
  renderTimeline();
  const marks = screen.getAllByRole("button");
  expect(marks.map((m) => m.getAttribute("tabindex"))).toEqual(["-1", "-1", "0"]);
  const last = marks[2];
  if (!last) throw new Error("missing mark");
  last.focus();
  fireEvent.keyDown(last, { key: "ArrowLeft" });
  expect(document.activeElement).toBe(marks[1]);
});

test("hovering or focusing a release shows its details; leaving hides them", () => {
  renderTimeline();
  const [first] = screen.getAllByRole("button");
  if (!first) throw new Error("missing mark");
  fireEvent.mouseEnter(first);
  expect(screen.getByRole("tooltip").textContent).toContain("2.4.0, Nov 1, 2025");
  fireEvent.mouseLeave(first);
  expect(screen.queryByRole("tooltip")).toBeNull();
  fireEvent.focus(first);
  expect(screen.getByRole("tooltip")).toBeTruthy();
  fireEvent.blur(first);
  expect(screen.queryByRole("tooltip")).toBeNull();
});

test("a history with no dates draws no marks", () => {
  render(<Timeline pkg="x" releases={[releases[3] as ReleaseSummary]} from="2.6.0" to="2.6.0" onCompare={vi.fn()} />);
  expect(screen.queryAllByRole("button")).toEqual([]);
});

test("on a narrow screen the chart scrolls to the newer release of the pair", () => {
  const scrollWidth = vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockReturnValue(760);
  const clientWidth = vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(320);
  renderTimeline();
  const tl = document.querySelector<HTMLDivElement>(".tl");
  expect(tl?.scrollLeft).toBeGreaterThan(0);
  scrollWidth.mockRestore();
  clientWidth.mockRestore();
});
