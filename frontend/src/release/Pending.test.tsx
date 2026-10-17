import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, expect, test, vi } from "vitest";
import type { PairPending } from "../api/types";
import { fakeApi } from "../test/server";
import { Failed, Progress } from "./Pending";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const pending: PairPending = {
  status: "pending",
  ecosystem: "pypi",
  package: "orbit-client",
  from_version: "2.4.1",
  to_version: "2.5.0",
  artifact: { kind: "wheel", old_filename: "a-2.4.1.whl", new_filename: "a-2.5.0.whl", match: "same_tag" },
  alternatives: [],
  step: "diffing",
  steps: ["downloading", "provenance", "diffing", "source", "rules"],
};

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

test("progress marks finished steps and the current one", () => {
  render(<Progress pending={pending} />);
  const steps = screen.getAllByRole("listitem");
  expect(steps.map((s) => s.getAttribute("data-state"))).toEqual(["done", "done", "current", "todo", "todo"]);
  expect(steps[2]?.getAttribute("aria-current")).toBe("step");
  expect(steps[0]?.textContent).toBe("✓ Downloading and unpacking");
  expect(screen.getByRole("status").textContent).toContain("Analyzing: a-2.4.1.whl and a-2.5.0.whl");
});

test("a queued analysis has no current step yet; unknown step names show as they are", () => {
  render(<Progress pending={{ ...pending, step: null, steps: ["downloading", "later"] }} />);
  expect(screen.getByRole("status").textContent).toContain("Queued: ");
  expect(screen.getAllByRole("listitem").map((s) => s.textContent)).toEqual(["Downloading and unpacking", "later"]);
});

test("retry re-queues a failed pair", async () => {
  const { requests } = fakeApi({
    "/api/pypi/orbit-client/2.4.1...2.5.0/retry?kind=sdist": { status: 202, body: pending },
  });
  render(
    wrap(
      <Failed
        ecosystem="pypi"
        pkg="orbit-client"
        versions="2.4.1...2.5.0"
        artifact={{ kind: "sdist" }}
        error="ArtifactIntegrityError: x"
      />,
    ),
  );
  expect(screen.getByRole("alert").textContent).toContain("ArtifactIntegrityError: x");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await vi.waitFor(() => {
    expect(requests).toEqual(["/api/pypi/orbit-client/2.4.1...2.5.0/retry?kind=sdist"]);
  });
});

test("a retry that can't start says why", async () => {
  fakeApi({
    "/api/pypi/orbit-client/2.4.1...2.5.0/retry": { status: 409, body: { detail: "nothing to retry" } },
  });
  render(wrap(<Failed ecosystem="pypi" pkg="orbit-client" versions="2.4.1...2.5.0" artifact={{}} error="boom" />));
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("nothing to retry")).toBeTruthy();
  cleanup();
  vi.stubGlobal("fetch", () => Promise.reject(new TypeError("offline")));
  render(wrap(<Failed ecosystem="pypi" pkg="orbit-client" versions="2.4.1...2.5.0" artifact={{}} error="boom" />));
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("The retry couldn't be started.")).toBeTruthy();
});
