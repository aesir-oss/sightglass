import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { fakeApi } from "../test/server";
import { pollWhilePending, POLL_MS, useFileDiff, usePairAnalysis, useReleaseHistory } from "./queries";

afterEach(() => {
  vi.unstubAllGlobals();
});

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

test("release history and file diffs are fetched; a file diff waits for a path", async () => {
  const { requests } = fakeApi({
    "/api/pypi/orbit-client/releases": { body: { package: "orbit-client", releases: [] } },
    "/api/pypi/orbit-client/2.5.0/files/orbit%2Fsync.py": { body: { path: "orbit/sync.py" } },
  });
  const history = renderHook(() => useReleaseHistory("pypi", "orbit-client"), { wrapper });
  await waitFor(() => {
    expect(history.result.current.data?.package).toBe("orbit-client");
  });
  const idle = renderHook(() => useFileDiff("pypi", "orbit-client", "2.5.0", null, "previous"), { wrapper });
  expect(idle.result.current.fetchStatus).toBe("idle");
  const diff = renderHook(() => useFileDiff("pypi", "orbit-client", "2.5.0", "orbit/sync.py", "previous"), {
    wrapper,
  });
  await waitFor(() => {
    expect(diff.result.current.data?.path).toBe("orbit/sync.py");
  });
  expect(requests).toEqual([
    "/api/pypi/orbit-client/releases",
    "/api/pypi/orbit-client/2.5.0/files/orbit%2Fsync.py?base=previous",
  ]);
});

test("a pending pair is polled until it is done", async () => {
  fakeApi({
    "/api/pypi/orbit-client/2.5.0": [
      { status: 202, body: { status: "pending" } },
      { body: { status: "done", signals: [], files: [] } },
    ],
  });
  const pair = renderHook(() => usePairAnalysis("pypi", "orbit-client", "2.5.0"), { wrapper });
  await waitFor(() => {
    expect(pair.result.current.data?.status).toBe("pending");
  });
  await pair.result.current.refetch();
  await waitFor(() => {
    expect(pair.result.current.data?.status).toBe("done");
  });
  expect(pollWhilePending({ status: "pending" })).toBe(POLL_MS);
  expect(pollWhilePending({ status: "done" })).toBe(false);
  expect(pollWhilePending(undefined)).toBe(false);
});
