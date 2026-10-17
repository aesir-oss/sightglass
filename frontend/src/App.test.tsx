import { QueryClient } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "./App";
import { routes } from "./routes";
import { fakeApi } from "./test/server";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const ARTIFACT = {
  kind: "wheel",
  old_filename: "orbit_client-2.4.1-py3-none-any.whl",
  new_filename: "orbit_client-2.5.0-py3-none-any.whl",
  match: "same_tag",
};
const BASE = {
  ecosystem: "pypi",
  package: "orbit-client",
  from_version: "2.4.1",
  to_version: "2.5.0",
  artifact: ARTIFACT,
  alternatives: [ARTIFACT],
};
const PAIR = "/api/pypi/orbit-client/2.4.1...2.5.0";

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<App router={router} queryClient={queryClient} />);
  return router;
}

test("the start page navigates to the pair the user asks for", () => {
  const router = renderAt("/");
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Sightglass");
  fireEvent.change(screen.getByLabelText(/PyPI package/), { target: { value: " orbit-client " } });
  fireEvent.change(screen.getByLabelText(/Releases/), { target: { value: "2.4.1...2.5.0" } });
  fireEvent.click(screen.getByRole("button", { name: "Compare" }));
  expect(router.state.location.pathname).toBe("/pypi/orbit-client/2.4.1...2.5.0");
});

test("a single version or an empty name is handled on the start page", () => {
  const router = renderAt("/");
  fireEvent.click(screen.getByRole("button", { name: "Compare" }));
  expect(router.state.location.pathname).toBe("/");
  fireEvent.change(screen.getByLabelText(/PyPI package/), { target: { value: "orbit-client" } });
  fireEvent.click(screen.getByRole("button", { name: "Compare" }));
  expect(router.state.location.pathname).toBe("/pypi/orbit-client");
});

test("a pending analysis says so, rendering file names as text", async () => {
  const hostile = { ...ARTIFACT, new_filename: '<img src=x onerror="alert(1)">.whl' };
  fakeApi({ [PAIR]: { status: 202, body: { ...BASE, status: "pending", artifact: hostile } } });
  renderAt("/pypi/orbit-client/2.4.1...2.5.0");
  const status = await screen.findByText(/Analyzing/);
  expect(status.textContent).toContain('<img src=x onerror="alert(1)">.whl');
  expect(document.querySelector("img")).toBeNull();
});

test("a finished analysis is summarized, and the artifact choice is passed to the API", async () => {
  const { requests } = fakeApi({
    "/api/pypi/orbit-client/releases": {
      body: {
        releases: ["2.4.1", "2.5.0", "2.6.0"].map((version, i) => ({
          version,
          published_at: `2026-0${String(i + 1)}-01T00:00:00Z`,
          yanked: false,
          attestation: "none",
          publisher: null,
        })),
      },
    },
    [`${PAIR}?kind=sdist`]: {
      body: {
        ...BASE,
        status: "done",
        ruleset_version: "rs-1",
        signals: [],
        source: {
          state: "compared",
          files: [{ path: "orbit/__init__.py", status: "matches", source_path: "src/orbit/__init__.py", text: true }],
          excluded: [],
        },
        files: [
          {
            path: "orbit/__init__.py",
            status: "changed",
            text: true,
            compiled: false,
            old_size: 10,
            new_size: 12,
            old_sha256: null,
            new_sha256: null,
            flagged: false,
          },
        ],
      },
    },
  });
  const router = renderAt("/pypi/orbit-client/2.4.1...2.5.0?kind=sdist");
  expect((await screen.findByRole("region", { name: "Signals" })).textContent).toContain("No signals for this pair");
  fireEvent.click(screen.getByRole("button", { name: /^orbit\/__init__\.py, changed/ }));
  expect(router.state.location.search).toBe("?kind=sdist&file=orbit%2F__init__.py");
  fireEvent.click(screen.getByRole("button", { name: "Source" }));
  expect(router.state.location.search).toBe("?kind=sdist&file=orbit%2F__init__.py&base=source");
  fireEvent.click(screen.getByRole("button", { name: "Previous release" }));
  expect(router.state.location.search).toBe("?kind=sdist&file=orbit%2F__init__.py");
  fireEvent.click(screen.getByText("1 matching files"));
  fireEvent.click(screen.getByRole("button", { name: /^matchesorbit\/__init__\.py/ }));
  expect(router.state.location.search).toBe("?kind=sdist&file=orbit%2F__init__.py&base=source");
  expect(requests).toContain(`${PAIR}?kind=sdist`);
  expect(requests).toContain("/api/pypi/orbit-client/releases");
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("orbit-client 2.4.1 → 2.5.0");
  fireEvent.click(screen.getByRole("button", { name: /Show to versions/ }));
  expect(await screen.findByRole("option", { name: "2.6.0" })).toBeTruthy();
  fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
  // The pair is a wheel pair (from the response), so a timeline pick carries no ?kind=.
  fireEvent.click(await screen.findByRole("button", { name: /^2\.6\.0,/ }));
  expect(router.state.location.pathname + router.state.location.search).toBe("/pypi/orbit-client/2.5.0...2.6.0");
});

test("failed analyses and API errors are shown plainly", async () => {
  fakeApi({
    [PAIR]: { body: { ...BASE, status: "failed", ruleset_version: "rs-1", error: "ArtifactIntegrityError: sha256" } },
    "/api/pypi/tidepool/1.0...9.9": { status: 404, body: { detail: "tidepool has no release '9.9'" } },
    "/api/pypi/kestrel/1.0...1.1": { status: 503, body: { detail: "PyPI is unavailable" } },
  });
  renderAt("/pypi/orbit-client/2.4.1...2.5.0");
  expect((await screen.findByRole("alert")).textContent).toContain("ArtifactIntegrityError: sha256");
  cleanup();
  renderAt("/pypi/tidepool/1.0...9.9");
  expect((await screen.findByRole("alert")).textContent).toBe("tidepool has no release '9.9'");
  cleanup();
  renderAt("/pypi/kestrel/1.0...1.1");
  expect((await screen.findByRole("alert")).textContent).toContain("couldn't load this comparison");
});

test("unknown paths get the not-found page", () => {
  renderAt("/a/b/c/d");
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Page not found");
});

test("the app builds its own router and query client when none are given", () => {
  window.history.pushState({}, "", "/");
  render(<App />);
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Sightglass");
});
