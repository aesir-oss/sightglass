import { QueryClient } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "../App";
import { routes } from "../routes";
import { fakeApi } from "../test/server";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<App router={router} queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
  return router;
}

test("a package page goes to its highest stable release, not the last one published", async () => {
  fakeApi({
    // 2.4.2 is a backport published after 2.5.0; the API names 2.5.0 as the latest.
    "/api/pypi/orbit-client/releases": {
      body: { releases: [{ version: "2.4.1" }, { version: "2.5.0" }, { version: "2.4.2" }], latest: "2.5.0" },
    },
    "/api/pypi/orbit-client/2.5.0": { status: 404, body: { detail: "stop here" } },
  });
  const router = renderAt("/pypi/orbit-client");
  await vi.waitFor(() => {
    expect(router.state.location.pathname).toBe("/pypi/orbit-client/2.5.0");
  });
});

test("unknown packages, outages and empty histories are explained", async () => {
  fakeApi({
    "/api/pypi/tidepool/releases": { status: 404, body: { detail: "tidepool isn't on PyPI" } },
    "/api/pypi/kestrel/releases": { status: 503, body: { detail: "down" } },
    "/api/pypi/gale/releases": { body: { releases: [], latest: null } },
  });
  renderAt("/pypi/tidepool");
  expect((await screen.findByRole("alert")).textContent).toBe("tidepool isn't on PyPI");
  cleanup();
  renderAt("/pypi/kestrel");
  expect((await screen.findByRole("alert")).textContent).toContain("couldn't load this package's releases");
  cleanup();
  renderAt("/pypi/gale");
  expect(await screen.findByText("This package has no releases to compare.")).toBeTruthy();
});
