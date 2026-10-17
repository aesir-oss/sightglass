import { useMemo, useState } from "react";
import type { FileEntry } from "../api/types";
import { Mark } from "../charts/Mark";
import { treemapLayout } from "../charts/layout";
import { useRovingFocus } from "../charts/useRovingFocus";
import "./release.css";

const W = 640;
const H = 340;
// Rows rendered before "Show all", so very large packages don't stall the page.
export const LIST_LIMIT = 500;

const SYMBOL = { added: "A", removed: "D", changed: "M", same: "·" } as const;
const RANK = { added: 0, changed: 1, removed: 2, same: 3 } as const;

function size(f: FileEntry): number {
  return f.new_size ?? f.old_size ?? 0;
}

function bytes(n: number): string {
  return n < 1024
    ? `${String(n)} B`
    : n < 1024 * 1024
      ? `${(n / 1024).toFixed(1)} KB`
      : `${(n / 1048576).toFixed(1)} MB`;
}

export function describeFile(f: FileEntry): string {
  const change =
    f.status === "same"
      ? "unchanged"
      : f.status === "changed"
        ? `changed, ${bytes(f.old_size ?? 0)} → ${bytes(f.new_size ?? 0)}`
        : `${f.status}, ${bytes(size(f))}`;
  return `${f.path}, ${change}${f.flagged ? ", flagged by a signal" : ""}`;
}

/** Flagged files first, then added, changed, removed and unchanged, each by path. */
export function sortFiles(files: readonly FileEntry[]): FileEntry[] {
  return [...files].sort(
    (a, b) => Number(b.flagged) - Number(a.flagged) || RANK[a.status] - RANK[b.status] || a.path.localeCompare(b.path),
  );
}

interface FilesProps {
  files: FileEntry[];
  artifactLabel: string;
  selected: string | null;
  onSelect: (path: string) => void;
}

function Treemap({ files, selected, onSelect, artifactLabel }: FilesProps) {
  const tiles = useMemo(
    () =>
      treemapLayout(
        files.map((f) => ({ path: f.path, status: f.status, size: size(f), flagged: f.flagged })),
        W,
        H,
        { minSize: 350 },
      ),
    [files],
  );
  const byPath = useMemo(() => new Map(files.map((f) => [f.path, f])), [files]);
  const focus = useRovingFocus(tiles.length);
  return (
    <div className="mapwrap">
      <svg
        className="map"
        viewBox={`0 0 ${String(W)} ${String(H)}`}
        role="group"
        aria-label={`Files in the ${artifactLabel}, sized by bytes and colored by change`}
        onKeyDown={focus.onKeyDown}
      >
        {tiles.map((t, i) => {
          const entry = byPath.get(t.file.path);
          const name = t.file.path.split("/").pop() ?? t.file.path;
          const chars = Math.floor((t.width - 14) / 7);
          return (
            <Mark
              key={t.file.path}
              className={`tile ${t.file.status}${t.file.flagged ? " flag" : ""}${t.file.path === selected ? " sel" : ""}`}
              label={entry ? describeFile(entry) : t.file.path}
              tabIndex={focus.tabIndexFor(i)}
              onActivate={() => {
                onSelect(t.file.path);
              }}
              onFocus={() => {
                focus.setActive(i);
              }}
            >
              <rect x={t.x} y={t.y} width={t.width} height={t.height} rx={3} />
              {t.width > 58 && t.height > 20 && (
                <text x={t.x + 7} y={t.y + 16}>
                  {name.length > chars ? `${name.slice(0, Math.max(3, chars - 1))}…` : name}
                </text>
              )}
            </Mark>
          );
        })}
      </svg>
    </div>
  );
}

function List({ files, selected, onSelect }: FilesProps) {
  const [all, setAll] = useState(false);
  const sorted = useMemo(() => sortFiles(files), [files]);
  const shown = all ? sorted : sorted.slice(0, LIST_LIMIT);
  return (
    <>
      <ul className="flist" aria-label="Files">
        {shown.map((f) => (
          <li key={f.path}>
            <button
              type="button"
              aria-current={f.path === selected}
              aria-label={describeFile(f)}
              onClick={() => {
                onSelect(f.path);
              }}
            >
              <span className="s" aria-hidden="true">
                {SYMBOL[f.status]}
              </span>
              <span className="p">{f.path}</span>
              <span className="d">{f.status === "same" ? "same" : bytes(size(f))}</span>
              {f.flagged && <span className="fl">Flagged by a signal</span>}
            </button>
          </li>
        ))}
      </ul>
      {!all && sorted.length > LIST_LIMIT && (
        <p className="more">
          <button
            type="button"
            onClick={() => {
              setAll(true);
            }}
          >
            Show all {sorted.length} files
          </button>
        </p>
      )}
    </>
  );
}

/** Section 4: the installed files as a treemap or a list, sharing the selected file with the diff viewer. */
export function Files(props: FilesProps) {
  const [view, setView] = useState<"map" | "list">("map");
  const counts = props.files.reduce<Record<string, number>>((acc, f) => {
    acc[f.status] = (acc[f.status] ?? 0) + 1;
    return acc;
  }, {});
  return (
    <section className="wrap" aria-label="Files">
      <div className="panel">
        <h2>
          <span className="grow">Files</span>
          <span className="hint">
            {props.files.length} files: {counts.added ?? 0} added, {counts.changed ?? 0} changed, {counts.removed ?? 0}{" "}
            removed
          </span>
          <span className="seg" role="group" aria-label="File view">
            {(["map", "list"] as const).map((v) => (
              <button
                key={v}
                type="button"
                aria-pressed={view === v}
                onClick={() => {
                  setView(v);
                }}
              >
                {v === "map" ? "Map" : "List"}
              </button>
            ))}
          </span>
        </h2>
        {view === "map" ? <Treemap {...props} /> : <List {...props} />}
      </div>
    </section>
  );
}
