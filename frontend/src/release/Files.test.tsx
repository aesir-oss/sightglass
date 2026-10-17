import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { FileEntry } from "../api/types";
import { treemapLayout } from "../charts/layout";
import { describeFile, Files, LIST_LIMIT, sortFiles } from "./Files";

afterEach(cleanup);

function entry(path: string, status: FileEntry["status"], over: Partial<FileEntry> = {}): FileEntry {
  return {
    path,
    status,
    text: true,
    compiled: false,
    old_size: status === "added" ? null : 1000,
    new_size: status === "removed" ? null : 1200,
    old_sha256: null,
    new_sha256: null,
    flagged: false,
    ...over,
  };
}

const files = [
  entry("orbit/__init__.py", "changed"),
  entry("orbit/telemetry.py", "added", { flagged: true, new_size: 3_000_000 }),
  entry("orbit/legacy.py", "removed"),
  entry("orbit/client.py", "same"),
  entry("README.md", "added", { new_size: 10 }),
];

function renderFiles(selected: string | null = null, list = files) {
  const onSelect = vi.fn();
  render(<Files files={list} artifactLabel="wheel" selected={selected} onSelect={onSelect} />);
  return onSelect;
}

test("the map shows a tile per file, flagged and selected tiles marked, and selects on click", () => {
  const onSelect = renderFiles("orbit/__init__.py");
  const map = screen.getByRole("group", { name: "Files in the wheel, sized by bytes and colored by change" });
  const tiles = within(map).getAllByRole("button");
  expect(tiles).toHaveLength(5);
  expect(map.querySelector(".tile.flag")?.getAttribute("aria-label")).toBe(
    "orbit/telemetry.py, added, 2.9 MB, flagged by a signal",
  );
  expect(map.querySelector(".tile.sel")?.getAttribute("aria-label")).toContain("orbit/__init__.py, changed");
  fireEvent.click(within(map).getByRole("button", { name: /^README\.md/ }));
  expect(onSelect).toHaveBeenCalledWith("README.md");
  expect(screen.getByText("5 files: 2 added, 1 changed, 1 removed")).toBeTruthy();
});

test("the map is keyboard navigable", () => {
  const onSelect = renderFiles();
  const tiles = within(screen.getByRole("group", { name: /Files in the wheel/ })).getAllByRole("button");
  const [first, second] = tiles;
  if (!first || !second) throw new Error("missing tiles");
  first.focus();
  fireEvent.keyDown(first, { key: "ArrowRight" });
  expect(document.activeElement).toBe(second);
  fireEvent.keyDown(second, { key: "Enter" });
  expect(onSelect).toHaveBeenCalledTimes(1);
});

test("the list sorts flagged files first and selects on click", () => {
  const onSelect = renderFiles("orbit/client.py");
  fireEvent.click(screen.getByRole("button", { name: "List" }));
  const rows = within(screen.getByRole("list", { name: "Files" })).getAllByRole("button");
  expect(rows.map((r) => r.querySelector(".p")?.textContent)).toEqual([
    "orbit/telemetry.py",
    "README.md",
    "orbit/__init__.py",
    "orbit/legacy.py",
    "orbit/client.py",
  ]);
  expect(rows[4]?.getAttribute("aria-current")).toBe("true");
  expect(rows[0]?.textContent).toContain("Flagged by a signal");
  fireEvent.click(rows[2] as HTMLElement);
  expect(onSelect).toHaveBeenCalledWith("orbit/__init__.py");
  expect(screen.getByRole("button", { name: "List" }).getAttribute("aria-pressed")).toBe("true");
});

test("thousands of files lay out quickly", () => {
  const many = Array.from({ length: 5000 }, (_, i) => ({
    path: `orbit/pkg${String(i % 50)}/m${String(i)}.py`,
    status: i % 7 === 0 ? ("changed" as const) : ("same" as const),
    size: 100 + i,
    flagged: false,
  }));
  const started = performance.now();
  expect(treemapLayout(many, 640, 340)).toHaveLength(5000);
  expect(performance.now() - started).toBeLessThan(1000);
});

test("the list renders a first page until Show all", () => {
  const count = LIST_LIMIT + 5;
  const many = Array.from({ length: count }, (_, i) => entry(`orbit/m${String(i)}.py`, "same"));
  renderFiles(null, many);
  fireEvent.click(screen.getByRole("button", { name: "List" }));
  expect(within(screen.getByRole("list", { name: "Files" })).getAllByRole("listitem")).toHaveLength(LIST_LIMIT);
  fireEvent.click(screen.getByRole("button", { name: `Show all ${String(count)} files` }));
  expect(within(screen.getByRole("list", { name: "Files" })).getAllByRole("listitem")).toHaveLength(count);
});

test("descriptions and sort order", () => {
  expect(describeFile(entry("a.py", "same"))).toBe("a.py, unchanged");
  expect(describeFile(entry("b.py", "removed"))).toBe("b.py, removed, 1000 B");
  expect(describeFile(entry("c.py", "changed", { old_size: null, new_size: null }))).toBe("c.py, changed, 0 B → 0 B");
  expect(sortFiles([entry("b", "same"), entry("a", "same")]).map((f) => f.path)).toEqual(["a", "b"]);
});
