import { expect, test } from "vitest";
import { levelColor, statusColor } from "./colors";
import { timelineLayout, treemapLayout, type TreemapFile, type TreemapRect } from "./layout";

function at<T>(items: readonly T[], i: number): T {
  const item = items[i];
  if (item === undefined) throw new Error(`no item ${String(i)}`);
  return item;
}

const release = (version: string, day: number | null) => ({
  version,
  published_at: day === null ? null : new Date(Date.UTC(2026, 0, day)).toISOString(),
});

test("timeline places releases by time, oldest first, inside the padding", () => {
  const points = timelineLayout([release("2.5.0", 31), release("2.4.1", 1), release("2.4.2", 16)], 312);
  expect(points.map((p) => p.release.version)).toEqual(["2.4.1", "2.4.2", "2.5.0"]);
  expect(points.map((p) => Math.round(p.x))).toEqual([12, 156, 300]);
});

test("dense releases keep a minimum gap and still fit the width", () => {
  const points = timelineLayout([release("1", 1), release("2", 1), release("3", 1), release("4", 30)], 100, {
    minGap: 30,
  });
  const xs = points.map((p) => p.x);
  expect(at(xs, 0)).toBe(12);
  expect(at(xs, xs.length - 1)).toBeCloseTo(88);
  for (let i = 1; i < xs.length; i++) expect(at(xs, i) - at(xs, i - 1)).toBeGreaterThan(0);
});

test("undated releases are skipped; one release or none still lays out", () => {
  expect(timelineLayout([release("1", null)], 100)).toEqual([]);
  const [only] = timelineLayout([release("1", 5)], 100);
  expect(only?.x).toBe(12);
});

const file = (path: string, size: number, status: TreemapFile["status"] = "same"): TreemapFile => ({
  path,
  size,
  status,
  flagged: false,
});

test("treemap areas follow sizes, every file gets a rect inside the bounds", () => {
  const files = [file("orbit/big.py", 6000, "changed"), file("orbit/small.py", 2000), file("README.md", 2000, "added")];
  const rects = treemapLayout(files, 100, 100, { padding: 0 });
  expect(rects.map((r) => r.file.path).sort()).toEqual(["README.md", "orbit/big.py", "orbit/small.py"]);
  const rect = (path: string): TreemapRect => {
    const r = rects.find((x) => x.file.path === path);
    if (!r) throw new Error(`no rect for ${path}`);
    return r;
  };
  const area = (path: string) => rect(path).width * rect(path).height;
  expect(area("orbit/big.py") / area("orbit/small.py")).toBeCloseTo(3, 0);
  for (const r of rects) {
    expect(r.x).toBeGreaterThanOrEqual(0);
    expect(r.y).toBeGreaterThanOrEqual(0);
    expect(r.x + r.width).toBeLessThanOrEqual(100);
    expect(r.y + r.height).toBeLessThanOrEqual(100);
  }
});

test("empty files still get area, and nothing is laid out without files or space", () => {
  const rects = treemapLayout([file("a/empty.py", 0), file("a/b/c.py", 100)], 50, 50, { minSize: 10 });
  expect(rects.find((r) => r.file.path === "a/empty.py")?.width).toBeGreaterThan(0);
  expect(treemapLayout([], 50, 50)).toEqual([]);
  expect(treemapLayout([file("x", 1)], 0, 50)).toEqual([]);
});

test("colors are theme tokens", () => {
  expect([statusColor("added"), statusColor("removed"), statusColor("changed"), statusColor("same")]).toEqual([
    "var(--add)",
    "var(--rm)",
    "var(--up)",
    "var(--same)",
  ]);
  expect([levelColor("high"), levelColor("check"), levelColor("note"), levelColor("clean")]).toEqual([
    "var(--rm)",
    "var(--warn)",
    "var(--up)",
    "var(--add)",
  ]);
});
