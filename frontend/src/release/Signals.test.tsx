import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, expect, test } from "vitest";
import type { SignalOut, SourceCheck } from "../api/types";
import { fileHref, Signals } from "./Signals";
import { MessageText } from "./text";

afterEach(cleanup);

const signals: SignalOut[] = [
  { rule_id: "timing.recent", level: "check", message: "2.5.0 was published on 2026-10-15", evidence: [] },
  {
    rule_id: "provenance.publisher_changed",
    level: "high",
    message: "2.5.0 was attested by `publish.yml`",
    evidence: [{ attestation_field: "publisher.workflow", before: "release.yml", after: "publish.yml" }],
  },
  {
    rule_id: "behavior.network",
    level: "high",
    message: "Added network calls in orbit/sync.py: `requests.post` (line 10)",
    evidence: [
      { file: "orbit/sync.py", line_start: 10, line_end: 10, side: "new" },
      { file: "orbit/sync.py", line_start: 20, line_end: 24, side: "new" },
      { file: "orbit/old.py", side: "old" },
    ],
  },
  {
    rule_id: "timing.long_gap",
    level: "note",
    message: "2.5.0 came 400 days after 2.4.1",
    evidence: [{ before: "x" }],
  },
];

function renderSignals(list: SignalOut[], source: SourceCheck | null = null) {
  const router = createMemoryRouter([{ path: "*", element: <Signals signals={list} source={source} /> }], {
    initialEntries: ["/pypi/orbit-client/2.4.1...2.5.0?kind=sdist"],
  });
  render(<RouterProvider router={router} />);
  return router;
}

test("signals are sorted by level with a count, and code spans render as code", () => {
  renderSignals(signals);
  const items = within(screen.getByRole("region", { name: "Signals" })).getAllByRole("listitem");
  const levels = items.filter((li) => li.querySelector(".lvl")).map((li) => li.querySelector(".lvl")?.textContent);
  expect(levels).toEqual(["high", "high", "check", "note"]);
  expect(screen.getByText("2 high, 1 to check")).toBeTruthy();
  expect(screen.getByText("publish.yml", { selector: "code" })).toBeTruthy();
});

test("evidence links to the file and lines, and shows changed values", () => {
  const router = renderSignals(signals);
  expect(screen.getByText("publisher.workflow").parentElement?.textContent).toBe(
    "publisher.workflow: release.yml → publish.yml",
  );
  expect(screen.getByText("orbit/sync.py:20–24")).toBeTruthy();
  expect(screen.getByText("orbit/old.py").closest("li")?.textContent).toBe("orbit/old.py (previous release)");
  expect(screen.getByText("x → none")).toBeTruthy();
  fireEvent.click(screen.getByText("orbit/sync.py:10"));
  expect(router.state.location.search).toBe("?kind=sdist&file=orbit%2Fsync.py&line=10");
});

test("long evidence lists are cut off with a count", () => {
  const many: SignalOut = {
    rule_id: "source.not_in_tag",
    level: "high",
    message: "14 package files aren't in tag v2.5.0",
    evidence: Array.from({ length: 14 }, (_, i) => ({ file: `orbit/m${String(i)}.py` })),
  };
  renderSignals([many]);
  expect(screen.getByText("and 2 more")).toBeTruthy();
});

test("no signals is clean; couldn't compare and unchecked sources are noted", () => {
  renderSignals([], {
    state: "could_not_compare",
    reason: "no_matching_tag",
    detail: "no tag matched (tried v2.5.0)",
    repository: "kestrel-weather/orbit-client",
    files: [],
    excluded: [],
  });
  expect(screen.getByText("Nothing unusual")).toBeTruthy();
  expect(screen.getByText(/No signals for this pair/)).toBeTruthy();
  expect(screen.getByText(/Couldn't compare with the source/).textContent).toContain("no tag matched (tried v2.5.0)");
  cleanup();
  renderSignals([], { state: "could_not_compare", reason: "no_repository", files: [], excluded: [] });
  expect(screen.getByText(/Couldn't compare with the source/).textContent).toBe(
    "Couldn't compare with the source: no_repository",
  );
  cleanup();
  renderSignals([], { state: "unknown", files: [], excluded: [] });
  expect(screen.getByText("The source wasn't checked for this pair.")).toBeTruthy();
});

test("file links replace an earlier line; message text is never HTML", () => {
  expect(fileHref("/p", "?file=a&line=3", "b")).toBe("/p?file=b");
  render(<MessageText text="calls `<img src=x>` and an unclosed `tick" />);
  expect(document.querySelector("img")).toBeNull();
  expect(screen.getByText("<img src=x>", { selector: "code" })).toBeTruthy();
});
