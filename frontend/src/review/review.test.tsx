import { QueryClient } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "../App";
import type { Review, ReviewChange } from "../api/types";
import { pollWhileAnalyzing, POLL_MS } from "../api/queries";
import { routes } from "../routes";
import { fakeApi } from "../test/server";
import { describeChange } from "./Queue";

afterEach(cleanup);

function change(overrides: Partial<ReviewChange>): ReviewChange {
  return {
    ecosystem: "pypi",
    package: "kestrel",
    kind: "changed",
    from_version: "1.4.0",
    to_version: "1.5.0",
    compare_from: "1.4.0",
    environments: ["default"],
    platforms: ["linux-64", "osx-arm64"],
    only_some_platforms: false,
    path: ["orbit-client", "kestrel"],
    analysis: { state: "done", level: "high", counts: { high: 2 } },
    ...overrides,
  };
}

const REVIEW: Review = {
  repository: "kestrel-weather/orbit",
  number: 7,
  base_sha: "a".repeat(40),
  head_sha: "b".repeat(40),
  lockfile_path: "pixi.lock",
  created_at: "2026-10-17T00:00:00Z",
  platforms: ["linux-64", "osx-arm64"],
  changes: [
    change({}),
    change({
      package: "gale",
      kind: "added",
      from_version: null,
      compare_from: "0.9.0",
      to_version: "1.0.0",
      platforms: ["osx-arm64"],
      only_some_platforms: true,
      path: ["gale"],
      analysis: { state: "pending", level: null, counts: {} },
    }),
    change({
      ecosystem: "conda",
      package: "tidepool",
      kind: "removed",
      to_version: null,
      compare_from: "1.4.0",
      path: [],
      analysis: { state: "not_analyzed", level: null, counts: {} },
    }),
  ],
};

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<App router={router} queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
  return router;
}

test("the queue lists changes with what was found, and the first is selected", async () => {
  fakeApi({ "/api/reviews/kestrel-weather/orbit/7": { body: REVIEW } });
  renderAt("/reviews/kestrel-weather/orbit/7");
  const list = await screen.findByRole("listbox", { name: "Package changes" });
  const options = within(list).getAllByRole("option");
  expect(options.map((o) => o.getAttribute("aria-label") ?? o.textContent)).toHaveLength(3);
  expect(options[0]?.getAttribute("aria-selected")).toBe("true");
  expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("kestrel-weather/orbit #7");
  const detail = screen.getByRole("region", { name: "Package detail" });
  expect(detail.textContent).toContain("orbit-client → kestrel");
  expect(within(detail).getByRole("link").getAttribute("href")).toBe("/pypi/kestrel/1.4.0...1.5.0");
});

test("selecting a change and a platform updates the URL", async () => {
  fakeApi({ "/api/reviews/kestrel-weather/orbit/7": { body: REVIEW } });
  const router = renderAt("/reviews/kestrel-weather/orbit/7");
  const list = await screen.findByRole("listbox", { name: "Package changes" });
  const gale = within(list).getAllByRole("option")[1];
  if (!gale) throw new Error("missing gale");
  fireEvent.click(gale);
  expect(router.state.location.search).toContain("package=pypi%3Agale");
  const detail = screen.getByRole("region", { name: "Package detail" });
  expect(detail.textContent).toContain("New dependency at 1.0.0");
  expect(detail.textContent).toContain("The project asks for it directly");
  fireEvent.click(screen.getByRole("button", { name: "linux-64" }));
  expect(router.state.location.search).toContain("platform=linux-64");
  expect(within(screen.getByRole("listbox")).getAllByRole("option")).toHaveLength(2);
  expect(screen.getByText("2 of 3 packages")).toBeTruthy();
});

test("a platform with no changes, an empty review and a missing one say so", async () => {
  fakeApi({
    "/api/reviews/kestrel-weather/orbit/7": { body: { ...REVIEW, platforms: ["linux-64", "win-64"] } },
    "/api/reviews/kestrel-weather/orbit/8": { body: { ...REVIEW, changes: [], platforms: [] } },
    "/api/reviews/kestrel-weather/orbit/9": { status: 404, body: { detail: "no review of kestrel-weather/orbit#9" } },
  });
  renderAt("/reviews/kestrel-weather/orbit/7?platform=win-64");
  expect(await screen.findByText("No package changes on win-64.")).toBeTruthy();
  cleanup();
  renderAt("/reviews/kestrel-weather/orbit/8");
  expect(await screen.findByText("This change doesn't add, remove or move any package.")).toBeTruthy();
  cleanup();
  renderAt("/reviews/kestrel-weather/orbit/9");
  expect((await screen.findByRole("alert")).textContent).toBe("no review of kestrel-weather/orbit#9");
});

test("descriptions say what was found, and polling continues while anything is analyzing", () => {
  const [high, pending, conda] = REVIEW.changes;
  if (!high || !pending || !conda) throw new Error("missing changes");
  expect(describeChange(high)).toBe("kestrel, 1.4.0 → 1.5.0, 2 high signals");
  expect(describeChange(pending)).toBe("gale, new at 1.0.0, still analyzing, only on osx-arm64");
  expect(describeChange(conda)).toBe("tidepool, 1.4.0 removed, not analyzed");
  expect(describeChange({ ...high, analysis: { state: "done", level: "note", counts: {} } })).toContain(
    "nothing that needs a look",
  );
  expect(describeChange({ ...high, analysis: { state: "failed", level: null, counts: {} } })).toContain("failed");
  expect(pollWhileAnalyzing(REVIEW)).toBe(POLL_MS);
  expect(pollWhileAnalyzing({ ...REVIEW, changes: [high] })).toBe(false);
  expect(pollWhileAnalyzing(undefined)).toBe(false);
  vi.restoreAllMocks();
});
