import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { SdistCheck, SourceCheck as SourceCheckData } from "../api/types";
import { SourceCheck } from "./SourceCheck";

afterEach(cleanup);

const compared: SourceCheckData = {
  state: "compared",
  label: "tag v2.5.0",
  repository: "kestrel-weather/orbit-client",
  commit: "0123456789abcdef0123456789abcdef01234567",
  ref: "refs/tags/v2.5.0",
  origin: "tag",
  root: "src/",
  files: [
    { path: "orbit/__init__.py", status: "matches", source_path: "src/orbit/__init__.py", text: true },
    { path: "orbit/telemetry.py", status: "missing", source_path: null, text: true },
    { path: "orbit/client.py", status: "differs", source_path: "src/orbit/client.py", text: true },
  ],
  excluded: ["orbit_client-2.5.0.dist-info/RECORD"],
};

function renderCheck(source: SourceCheckData | null, sdist: SdistCheck | null = null) {
  const onSelect = vi.fn();
  render(<SourceCheck source={source} sdist={sdist} onSelect={onSelect} />);
  return onSelect;
}

test("a compared source names the tag and commit, lists problems first, and selects files", () => {
  const onSelect = renderCheck(compared);
  expect(screen.getByText("1 match, 1 differ, 1 missing")).toBeTruthy();
  expect(screen.getByText("tag v2.5.0")).toBeTruthy();
  const link = screen.getByRole("link", { name: "kestrel-weather/orbit-client@0123456789ab" });
  expect(link.getAttribute("href")).toBe(
    "https://github.com/kestrel-weather/orbit-client/tree/0123456789abcdef0123456789abcdef01234567",
  );
  expect(link.getAttribute("rel")).toBe("noopener noreferrer");
  expect(screen.getByText("src/").tagName).toBe("CODE");
  fireEvent.click(screen.getByRole("button", { name: /orbit\/client\.py \(src\/orbit\/client\.py\)/ }));
  expect(onSelect).toHaveBeenCalledWith("orbit/client.py");
  expect(screen.getByText("1 matching files")).toBeTruthy();
  expect(screen.getByText("1 build metadata files not compared")).toBeTruthy();
});

test("an attested commit and a clean source say so", () => {
  renderCheck({
    ...compared,
    origin: "attestation",
    label: "commit 0123456789ab",
    root: "",
    files: [compared.files[0] as SourceCheckData["files"][number]],
    excluded: [],
  });
  expect(screen.getByText(/the commit named by the attestation/)).toBeTruthy();
  expect(screen.getByText("Every package file matches the source.")).toBeTruthy();
});

test("couldn't compare gives the reason in words, with detail and repository", () => {
  renderCheck({
    state: "could_not_compare",
    reason: "no_matching_tag",
    detail: "no tag matched (tried v2.5.0, 2.5.0, ...)",
    repository: "kestrel-weather/orbit-client",
    files: [],
    excluded: [],
  });
  expect(screen.getByRole("status").textContent).toBe(
    "Couldn't compare with the source. No git tag matches this version. (no tag matched (tried v2.5.0, 2.5.0, ...)) Repository: kestrel-weather/orbit-client.",
  );
  cleanup();
  renderCheck({ state: "could_not_compare", reason: "something_new", files: [], excluded: [] });
  expect(screen.getByRole("status").textContent).toBe("Couldn't compare with the source. something_new");
});

test("an unchecked source and the wheel-versus-sdist check", () => {
  const onSelect = renderCheck(null, {
    root: "",
    files: [
      { path: "orbit/telemetry.py", status: "missing", source_path: null, text: true },
      { path: "orbit/__init__.py", status: "matches", source_path: "orbit/__init__.py", text: true },
    ],
    excluded: [],
  });
  expect(screen.getByText("The source wasn't checked for this pair.")).toBeTruthy();
  expect(screen.getByText("1 file is in the wheel but not in the sdist")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /orbit\/telemetry\.py/ }));
  expect(onSelect).toHaveBeenCalledWith("orbit/telemetry.py");
  cleanup();
  renderCheck(
    { state: "unknown", files: [], excluded: [] },
    {
      root: "",
      files: Array.from({ length: 2 }, (_, i) => ({
        path: `m${String(i)}.py`,
        status: "missing" as const,
        source_path: null,
        text: true,
      })),
      excluded: [],
    },
  );
  expect(screen.getByText("2 files are in the wheel but not in the sdist")).toBeTruthy();
});
