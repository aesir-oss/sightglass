import { QueryClient } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { afterEach, expect, test } from "vitest";
import { App } from "../App";
import type { ReviewSummary } from "../api/types";
import { routes } from "../routes";
import { fakeApi } from "../test/server";
import { describeCounts } from "./ReviewsPage";

afterEach(cleanup);

const ORBIT: ReviewSummary = {
  repository: "kestrel-weather/orbit",
  number: 7,
  head_sha: "b".repeat(40),
  lockfile_path: "pixi.lock",
  created_at: "2026-10-17T12:30:00Z",
  counts: { added: 1, changed: 2 },
};

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<App router={router} queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
  return router;
}

test("the list links each pull request's review and says what changed", async () => {
  fakeApi({ "/api/reviews": { body: { reviews: [ORBIT, { ...ORBIT, number: 8, counts: {} }] } } });
  renderAt("/reviews");
  const list = await screen.findByRole("list", { name: "Reviews" });
  const items = within(list).getAllByRole("listitem");
  expect(items).toHaveLength(2);
  expect(
    within(items[0] as HTMLElement)
      .getByRole("link")
      .getAttribute("href"),
  ).toBe("/reviews/kestrel-weather/orbit/7");
  expect(items[0]?.textContent).toContain("pixi.lock at bbbbbbb, 1 added, 2 changed");
  expect(items[0]?.textContent).toContain("Oct 17, 2026");
  expect(items[1]?.textContent).toContain("no package changes");
});

test("no reviews and a failed load say so", async () => {
  fakeApi({ "/api/reviews": { body: { reviews: [] } } });
  renderAt("/reviews");
  expect((await screen.findByText(/No reviews yet/)).textContent).toContain("pull request URL");
  cleanup();
  fakeApi({ "/api/reviews": { status: 500, body: { detail: "boom" } } });
  renderAt("/reviews");
  expect((await screen.findByRole("alert")).textContent).toContain("couldn't load the reviews");
});

test("counts read in kind order", () => {
  expect(describeCounts({ removed: 1, added: 3 })).toBe("3 added, 1 removed");
  expect(describeCounts({})).toBe("no package changes");
});

test("a pull request URL opens its review once it's recorded", async () => {
  fakeApi({
    "/api/reviews": { body: { reviews: [] } },
    "POST /api/reviews": {
      status: 201,
      body: { repository: "kestrel-weather/orbit", number: 7, lockfile_path: "pixi.lock" },
    },
    "/api/reviews/kestrel-weather/orbit/7": { body: { ...REVIEW_BODY } },
  });
  const router = renderAt("/reviews");
  const form = await screen.findByRole("form", { name: "Review a pull request" });
  fireEvent.change(within(form).getByRole("textbox"), {
    target: { value: " https://github.com/kestrel-weather/orbit/pull/7 " },
  });
  fireEvent.submit(form);
  await waitFor(() => {
    expect(router.state.location.pathname).toBe("/reviews/kestrel-weather/orbit/7");
  });
});

test("a URL that can't be reviewed shows why, and an empty one isn't sent", async () => {
  const { requests } = fakeApi({
    "/api/reviews": { body: { reviews: [] } },
    "POST /api/reviews": { status: 422, body: { detail: "a/b#7 doesn't change a pixi.lock or uv.lock" } },
  });
  renderAt("/reviews");
  const form = await screen.findByRole("form", { name: "Review a pull request" });
  const before = requests.length;
  fireEvent.submit(form);
  expect(requests).toHaveLength(before);
  fireEvent.change(within(form).getByRole("textbox"), { target: { value: "https://github.com/a/b/pull/7" } });
  fireEvent.submit(form);
  expect((await within(form).findByRole("alert")).textContent).toBe("a/b#7 doesn't change a pixi.lock or uv.lock");
});

const REVIEW_BODY = {
  repository: "kestrel-weather/orbit",
  number: 7,
  base_sha: "a".repeat(40),
  head_sha: "b".repeat(40),
  lockfile_path: "pixi.lock",
  created_at: "2026-10-17T00:00:00Z",
  platforms: [],
  changes: [],
};
