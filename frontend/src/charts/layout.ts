// Layout functions for the charts: pure data in, positions out. React renders the SVG.
import { hierarchy, treemap, treemapSquarify } from "d3-hierarchy";
import { scaleUtc } from "d3-scale";
import type { FileStatus } from "./colors";

export interface TimelineInput {
  version: string;
  published_at: string | null;
}

export interface TimelinePoint<T extends TimelineInput> {
  release: T;
  x: number;
}

/** The time scale the timeline uses: first to last publish time across `width`, inside `padding`. */
export function timelineScale(
  releases: readonly TimelineInput[],
  width: number,
  padding = 12,
): ((date: Date) => number) | null {
  const times = releases.flatMap((r) => (r.published_at ? [new Date(r.published_at).getTime()] : []));
  if (times.length === 0) return null;
  const first = Math.min(...times);
  const last = Math.max(...times);
  const scale = scaleUtc()
    .domain([new Date(first), new Date(last === first ? first + 1 : last)])
    .range([padding, Math.max(padding, width - padding)]);
  return (date) => scale(date);
}

/**
 * Place releases along a time axis of `width` pixels, keeping at least `minGap` pixels between neighbours so every
 * release stays clickable and labelled. A long or dense history runs past `width` rather than being squeezed;
 * `timelineWidth` gives the width it needs. Releases without a publish time are left out.
 */
export function timelineLayout<T extends TimelineInput>(
  releases: readonly T[],
  width: number,
  { padding = 12, minGap = 10 } = {},
): TimelinePoint<T>[] {
  const dated = releases
    .filter((r): r is T & { published_at: string } => r.published_at !== null)
    .map((r) => ({ release: r, time: new Date(r.published_at) }))
    .sort((a, b) => a.time.getTime() - b.time.getTime());
  const scale = timelineScale(releases, width, padding);
  if (!scale) return [];
  const points: TimelinePoint<T>[] = [];
  for (const { release, time } of dated) {
    const previous = points[points.length - 1];
    const x = previous ? Math.max(scale(time), previous.x + minGap) : scale(time);
    points.push({ release, x });
  }
  return points;
}

/** The width a laid-out timeline needs: `width`, or more when its points run past it. */
export function timelineWidth(points: readonly { x: number }[], width: number, padding = 12): number {
  const last = points[points.length - 1];
  return last ? Math.max(width, last.x + padding) : width;
}

/**
 * A tick for each new year, halfway between the year's first release and the one before it, so ticks stay between the
 * right releases however far spacing has pushed them from the time scale.
 */
export function yearTicks<T extends TimelineInput>(points: readonly TimelinePoint<T>[]): { year: number; x: number }[] {
  const ticks: { year: number; x: number }[] = [];
  let previous: TimelinePoint<T> | undefined;
  for (const point of points) {
    const year = new Date(point.release.published_at ?? 0).getUTCFullYear();
    if (previous && new Date(previous.release.published_at ?? 0).getUTCFullYear() !== year) {
      ticks.push({ year, x: (previous.x + point.x) / 2 });
    }
    previous = point;
  }
  return ticks;
}

export interface TreemapFile {
  path: string;
  status: FileStatus;
  size: number;
  flagged: boolean;
}

export interface TreemapRect {
  file: TreemapFile;
  x: number;
  y: number;
  width: number;
  height: number;
}

interface Node {
  name: string;
  file?: TreemapFile;
  children?: Node[];
}

function tree(files: readonly TreemapFile[]): Node {
  const root: Node = { name: "", children: [] };
  for (const file of files) {
    let node = root;
    const parts = file.path.split("/");
    for (const part of parts.slice(0, -1)) {
      node.children ??= [];
      let child = node.children.find((c) => c.name === part && c.children);
      if (!child) {
        child = { name: part, children: [] };
        node.children.push(child);
      }
      node = child;
    }
    node.children ??= [];
    node.children.push({ name: parts[parts.length - 1] ?? file.path, file });
  }
  return root;
}

/**
 * A squarified treemap of files grouped by directory, sized by bytes. Every file gets at least `minSize` bytes of
 * area so empty and tiny files stay visible and clickable.
 */
export function treemapLayout(
  files: readonly TreemapFile[],
  width: number,
  height: number,
  { minSize = 1, padding = 1 } = {},
): TreemapRect[] {
  if (files.length === 0 || width <= 0 || height <= 0) return [];
  const root = hierarchy(tree(files))
    .sum((n) => (n.file ? Math.max(n.file.size, minSize) : 0))
    .sort((a, b) => (b.value ?? 0) - (a.value ?? 0));
  const laid = treemap<Node>().tile(treemapSquarify).size([width, height]).paddingInner(padding).round(true)(root);
  return laid
    .leaves()
    .flatMap((leaf) =>
      leaf.data.file
        ? [{ file: leaf.data.file, x: leaf.x0, y: leaf.y0, width: leaf.x1 - leaf.x0, height: leaf.y1 - leaf.y0 }]
        : [],
    );
}
