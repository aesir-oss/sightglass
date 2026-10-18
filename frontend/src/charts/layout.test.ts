import { expect, test } from "vitest";
import { levelColor, statusColor } from "./colors";
import { timelineLayout, timelineWidth, treemapLayout, yearTicks, type TreemapFile, type TreemapRect } from "./layout";

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

test("dense releases keep a minimum gap, and the timeline grows to fit them", () => {
  const points = timelineLayout([release("1", 1), release("2", 1), release("3", 1), release("4", 30)], 100, {
    minGap: 30,
  });
  const xs = points.map((p) => p.x);
  expect(xs).toEqual([12, 42, 72, 102]);
  expect(timelineWidth(points, 100)).toBe(114);
  expect(timelineWidth(timelineLayout([release("1", 1), release("2", 30)], 100), 100)).toBe(100);
  expect(timelineWidth([], 100)).toBe(100);
});

test("a long history keeps its spacing instead of being squeezed", () => {
  // 445 releases over 16 years, like django's.
  const many = Array.from({ length: 445 }, (_, i) => ({
    version: String(i),
    published_at: new Date(Date.UTC(2010, 0, 1 + i * 13)).toISOString(),
  }));
  const points = timelineLayout(many, 1000, { padding: 30, minGap: 30 });
  for (let i = 1; i < points.length; i++) expect(at(points, i).x - at(points, i - 1).x).toBeGreaterThanOrEqual(30);
  expect(timelineWidth(points, 1000, 30)).toBeGreaterThan(13000);
});

test("year ticks sit between the last release of a year and the first of the next", () => {
  const points = timelineLayout(
    [
      { version: "1", published_at: "2024-12-01T00:00:00Z" },
      { version: "2", published_at: "2025-01-02T00:00:00Z" },
      { version: "3", published_at: "2025-06-01T00:00:00Z" },
      { version: "4", published_at: "2026-02-01T00:00:00Z" },
    ],
    400,
    { minGap: 50 },
  );
  const ticks = yearTicks(points);
  expect(ticks.map((t) => t.year)).toEqual([2025, 2026]);
  expect(at(ticks, 0).x).toBe((at(points, 0).x + at(points, 1).x) / 2);
  expect(at(ticks, 1).x).toBe((at(points, 2).x + at(points, 3).x) / 2);
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
