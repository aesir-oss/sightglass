import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import type { ArtifactRef } from "../api/types";
import { Header } from "./Header";
import { artifactLabel, artifactQuery, pairPath } from "./urls";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const sdist: ArtifactRef = {
  kind: "sdist",
  old_filename: "orbit_client-2.4.1.tar.gz",
  new_filename: "orbit_client-2.5.0.tar.gz",
  match: "same_tag",
};
const pure: ArtifactRef = {
  kind: "wheel",
  old_filename: "orbit_client-2.4.1-py3-none-any.whl",
  new_filename: "orbit_client-2.5.0-py3-none-any.whl",
  match: "same_tag",
};
const linux: ArtifactRef = {
  kind: "wheel",
  old_filename: "orbit_client-2.4.1-cp313-cp313-manylinux2014_x86_64.whl",
  new_filename: "orbit_client-2.5.0-cp314-cp314-manylinux_2_28_x86_64.whl",
  match: "platform_changed",
};

function renderHeader(artifact: ArtifactRef = pure, alternatives: ArtifactRef[] = [sdist, pure, linux]) {
  const router = createMemoryRouter(
    [
      {
        path: "*",
        element: (
          <Header
            ecosystem="pypi"
            pkg="orbit-client"
            from="2.4.1"
            to="2.5.0"
            versions={["2.4.0", "2.4.1", "2.5.0", "2.6.0"]}
            artifact={artifact}
            alternatives={alternatives}
          />
        ),
      },
    ],
    { initialEntries: ["/pypi/orbit-client/2.4.1...2.5.0"] },
  );
  render(<RouterProvider router={router} />);
  return router;
}

test("the header names the package and both versions", () => {
  renderHeader();
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("orbit-client 2.4.1 → 2.5.0");
  expect(screen.getByRole("navigation", { name: "Breadcrumb" }).textContent).toContain("PyPI");
});

test("picking a version updates the URL", () => {
  const router = renderHeader();
  const [from] = screen.getAllByRole("combobox");
  if (!from) throw new Error("no version picker");
  fireEvent.focus(from);
  fireEvent.click(screen.getByRole("button", { name: /Show compare versions/ }));
  fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: "2.4.0" }));
  expect(router.state.location.pathname).toBe("/pypi/orbit-client/2.4.0...2.5.0");
});

test("the to picker keeps the sdist choice", () => {
  const router = renderHeader(sdist);
  fireEvent.click(screen.getByRole("button", { name: /Show to versions/ }));
  fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: "2.6.0" }));
  expect(router.state.location.pathname + router.state.location.search).toBe(
    "/pypi/orbit-client/2.4.1...2.6.0?kind=sdist",
  );
});

test("picking an artifact updates the URL", () => {
  const router = renderHeader();
  fireEvent.click(screen.getByRole("button", { name: /Wheel py3-none-any/ }));
  fireEvent.click(
    screen.getByRole("option", { name: "Wheel cp314-cp314-manylinux_2_28_x86_64 (platform tag changed)" }),
  );
  expect(router.state.location.search).toBe("?wheel=orbit_client-2.5.0-cp314-cp314-manylinux_2_28_x86_64.whl");
});

test("one artifact is named without a picker", () => {
  renderHeader(sdist, [sdist]);
  expect(screen.getByText("Artifact: Source distribution (sdist)")).toBeTruthy();
});

test("copy link copies the canonical URL, or says it couldn't", async () => {
  const writeText = vi.fn(() => Promise.resolve());
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  renderHeader(sdist);
  fireEvent.click(screen.getByRole("button", { name: "Copy link" }));
  expect(await screen.findByText("Link copied")).toBeTruthy();
  expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/pypi/orbit-client/2.4.1...2.5.0?kind=sdist`);

  cleanup();
  vi.stubGlobal("navigator", { clipboard: { writeText: () => Promise.reject(new Error("denied")) } });
  renderHeader();
  fireEvent.click(screen.getByRole("button", { name: "Copy link" }));
  expect(await screen.findByText(/Couldn't copy/)).toBeTruthy();
});

test("URL helpers", () => {
  expect(artifactQuery(pure, pure)).toBe("");
  expect(artifactQuery(sdist, pure)).toBe("?kind=sdist");
  expect(artifactQuery(linux, pure)).toBe(`?wheel=${encodeURIComponent(linux.new_filename)}`);
  expect(artifactQuery(pure, undefined)).toBe(`?wheel=${encodeURIComponent(pure.new_filename)}`);
  expect(pairPath("pypi", "orbit client", "1.0", "2.0")).toBe("/pypi/orbit%20client/1.0...2.0");
  expect(artifactLabel(pure)).toBe("Wheel py3-none-any");
});
