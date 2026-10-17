import { afterEach, expect, test, vi } from "vitest";
import { fakeApi } from "../test/server";
import { ApiError, artifactFromSearch, fetchFileDiff, fetchReleaseHistory } from "./client";
import { makeQueryClient, POLL_MS } from "./queries";

afterEach(() => {
  vi.unstubAllGlobals();
});

test("calls are typed paths with the right query", async () => {
  const { requests } = fakeApi({
    "/api/pypi/orbit-client/releases": { body: { ecosystem: "pypi", package: "orbit-client", releases: [] } },
    "/api/pypi/orbit-client/2.4.1...2.5.0/files/orbit%2F__init__.py": { body: { path: "orbit/__init__.py" } },
  });
  expect((await fetchReleaseHistory("pypi", "orbit-client")).package).toBe("orbit-client");
  const diff = await fetchFileDiff("pypi", "orbit-client", "2.4.1...2.5.0", "orbit/__init__.py", "source", {
    wheel: "x.whl",
  });
  expect(diff.path).toBe("orbit/__init__.py");
  expect(requests[1]).toBe("/api/pypi/orbit-client/2.4.1...2.5.0/files/orbit%2F__init__.py?base=source&wheel=x.whl");
});

test("errors carry the status and the server's detail, or a fallback", async () => {
  fakeApi({
    "/api/pypi/tidepool/releases": { status: 404, body: { detail: "tidepool isn't on PyPI" } },
    "/api/pypi/kestrel/releases": { status: 500, body: "oops" },
  });
  await expect(fetchReleaseHistory("pypi", "tidepool")).rejects.toEqual(new ApiError(404, "tidepool isn't on PyPI"));
  await expect(fetchReleaseHistory("pypi", "kestrel")).rejects.toMatchObject({
    status: 500,
    message: "request failed with status 500",
  });
});

test("artifact choice comes from known query parameters only", () => {
  expect(artifactFromSearch(new URLSearchParams("kind=sdist&wheel=a.whl"))).toEqual({ kind: "sdist", wheel: "a.whl" });
  expect(artifactFromSearch(new URLSearchParams("kind=egg"))).toEqual({});
});

test("client errors aren't retried; server errors are, twice", () => {
  const retry = makeQueryClient().getDefaultOptions().queries?.retry;
  expect(typeof retry).toBe("function");
  const decide = retry as (count: number, error: Error) => boolean;
  expect(decide(0, new ApiError(404, "x"))).toBe(false);
  expect(decide(0, new ApiError(503, "x"))).toBe(true);
  expect(decide(2, new ApiError(503, "x"))).toBe(false);
  expect(POLL_MS).toBe(5000);
});
