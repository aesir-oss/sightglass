import { Fragment, useEffect, useRef } from "react";
import { ApiError, type Artifact } from "../api/client";
import { useFileDiff } from "../api/queries";
import type { FileDiff } from "../api/types";
import "./release.css";

export type Base = "previous" | "source";

interface DiffViewerProps {
  ecosystem: string;
  pkg: string;
  /** `<from>...<to>`. */
  versions: string;
  artifact: Artifact;
  file: string | null;
  line: number | null;
  base: Base;
  /** Whether the selected file has a counterpart in the source to diff against. */
  inSource: boolean;
  onBase: (base: Base) => void;
}

const MARK = { context: " ", added: "+", removed: "−" } as const;
const ROW = { context: "", added: "a", removed: "d" } as const;

function short(sha: string | null): string {
  return sha ? sha.slice(0, 12) : "none";
}

function MetadataNote({ diff }: { diff: FileDiff }) {
  const sizes = `${String(diff.old_size ?? 0)} → ${String(diff.new_size ?? 0)} bytes`;
  const hashes = `sha256 ${short(diff.old_sha256)} → ${short(diff.new_sha256)}`;
  const text = {
    binary: `Binary file, so no line diff: ${sizes}, ${hashes}.`,
    too_large: `Too large to diff here: ${sizes}, ${hashes}.`,
    unavailable: `The contents weren't kept, so there is no line diff: ${sizes}, ${hashes}.`,
    identical: "The contents are identical.",
    shown: "",
  }[diff.diff];
  return <p className="note">{text}</p>;
}

function DiffTable({ diff, line }: { diff: FileDiff; line: number | null }) {
  const target = useRef<HTMLTableRowElement>(null);
  useEffect(() => {
    const row: Partial<Pick<HTMLElement, "scrollIntoView">> | null = target.current;
    // jsdom has no scrollIntoView.
    row?.scrollIntoView?.({ block: "center" });
  }, [line, diff]);
  return (
    <div className="diff">
      <table aria-label={`Diff of ${diff.path}`}>
        <tbody>
          {diff.hunks.map((h, i) => (
            <Fragment key={i}>
              <tr className="gap">
                <td
                  colSpan={4}
                >{`@@ −${String(h.old_start)},${String(h.old_len)} +${String(h.new_start)},${String(h.new_len)} @@`}</td>
              </tr>
              {h.lines.map((l, j) => {
                const isTarget = line !== null && l.new_line === line;
                return (
                  <tr
                    key={j}
                    ref={isTarget ? target : undefined}
                    className={[ROW[l.kind], l.marked ? "hit" : "", isTarget ? "target" : ""].join(" ").trim()}
                  >
                    <td className="n">{l.old_line ?? ""}</td>
                    <td className="n">{l.new_line ?? ""}</td>
                    <td className="m" aria-hidden="true">
                      {MARK[l.kind]}
                    </td>
                    <td className="c">
                      {l.marked && <span className="sr-only">Flagged: </span>}
                      {l.kind !== "context" && (
                        <span className="sr-only">{l.kind === "added" ? "Added: " : "Removed: "}</span>
                      )}
                      {l.text}
                      {l.missing_newline && <span className="sr-only"> (no newline at end of file)</span>}
                    </td>
                  </tr>
                );
              })}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Section 5: the selected file's diff against the previous release or the source, with signal lines marked. */
export function DiffViewer(props: DiffViewerProps) {
  const { ecosystem, pkg, versions, artifact, file, line, base, inSource, onBase } = props;
  const effectiveBase = base === "source" && !inSource ? "previous" : base;
  const query = useFileDiff(ecosystem, pkg, versions, file, effectiveBase, artifact);
  const diff = query.data;

  return (
    <section className="wrap" aria-label="Diff">
      <div className="panel">
        <h2>
          <span className="grow">Diff</span>
          <span className="seg" role="group" aria-label="Compare against">
            <button
              type="button"
              aria-pressed={effectiveBase === "previous"}
              onClick={() => {
                onBase("previous");
              }}
            >
              Previous release
            </button>
            <button
              type="button"
              aria-pressed={effectiveBase === "source"}
              disabled={!inSource}
              title={inSource ? undefined : "This file has no counterpart in the source"}
              onClick={() => {
                onBase("source");
              }}
            >
              Source
            </button>
          </span>
        </h2>
        {file === null && <p className="note">Select a file in the map or list to see its diff.</p>}
        {query.isLoading && (
          <p className="note" role="status">
            Loading the diff…
          </p>
        )}
        {query.isError && (
          <p className="note" role="alert">
            {query.error instanceof ApiError ? query.error.message : "The diff couldn't be loaded."}
          </p>
        )}
        {diff && (
          <>
            <div className="diffhead">
              <span className="path">{diff.path}</span>
              <span className="cmp">
                compared with {diff.base === "source" ? diff.base_label : `release ${diff.base_label}`}
                {diff.old_path && diff.old_path !== diff.path ? ` (${diff.old_path})` : ""}
              </span>
              {diff.diff === "shown" && (
                <span className="stat">
                  +{diff.added} −{diff.removed}
                </span>
              )}
            </div>
            {diff.diff === "shown" ? <DiffTable diff={diff} line={line} /> : <MetadataNote diff={diff} />}
          </>
        )}
      </div>
    </section>
  );
}
