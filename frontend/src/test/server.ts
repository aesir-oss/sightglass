// A fake API for tests: maps request paths to responses, and records the requests.
import { vi } from "vitest";

export interface Reply {
  status?: number;
  body: unknown;
}

export function fakeApi(routes: Record<string, Reply | Reply[]>) {
  const requests: string[] = [];
  const fetchMock = vi.fn((input: Request | string | URL) => {
    const url = new URL(input instanceof Request ? input.url : String(input), "http://localhost");
    const key = url.pathname + url.search;
    requests.push(key);
    const route = routes[key] ?? routes[url.pathname];
    const reply = Array.isArray(route) ? (route.length > 1 ? route.shift() : route[0]) : route;
    const { status = 200, body } = reply ?? { status: 404, body: { detail: "Not Found" } };
    return Promise.resolve(
      new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return { requests, fetchMock };
}
