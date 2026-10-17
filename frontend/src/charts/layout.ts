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

/**
 * Place releases along a time axis of `width` pixels, keeping at least `minGap` pixels between neighbours so dense
 * release runs stay clickable. Releases without a publish time are left out.
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
  const first = dated[0];
  const last = dated[dated.length - 1];
  if (!first || !last) return [];
  const span = first.time.getTime() === last.time.getTime() ? 1 : 0;
  const scale = scaleUtc()
    .domain([first.time, new Date(last.time.getTime() + span)])
    .range([padding, Math.max(padding, width - padding)]);
  const points: TimelinePoint<T>[] = [];
  for (const { release, time } of dated) {
    const previous = points[points.length - 1];
    const x = previous ? Math.max(scale(time), previous.x + minGap) : scale(time);
    points.push({ release, x });
  }
  // Spacing can push the last points past the edge; squeeze them back proportionally.
  const start = points[0]?.x ?? padding;
  const end = points[points.length - 1]?.x ?? padding;
  const limit = width - padding;
  if (end > limit && end > start) {
    const factor = (limit - start) / (end - start);
    for (const p of points) p.x = start + (p.x - start) * factor;
  }
  return points;
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
