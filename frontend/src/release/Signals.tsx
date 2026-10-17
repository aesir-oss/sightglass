import { Link, useLocation } from "react-router";
import type { SignalOut, SourceCheck } from "../api/types";
import { MessageText } from "./text";
import "./release.css";

const ORDER = ["high", "check", "note", "clean"] as const;

interface Evidence {
  file?: string;
  line_start?: number;
  line_end?: number;
  side?: "old" | "new";
  attestation_field?: string;
  before?: string;
  after?: string;
}

/** The current page URL with `file` (and `line`) selecting a file for the diff viewer. */
export function fileHref(pathname: string, search: string, file: string, line?: number): string {
  const params = new URLSearchParams(search);
  params.set("file", file);
  if (line === undefined) params.delete("line");
  else params.set("line", String(line));
  return `${pathname}?${params.toString()}`;
}

const ISO_TIME = /^\d{4}-\d{2}-\d{2}T[\d:.]+(Z|[+-]\d{2}:\d{2})$/;

/** Evidence values as written, except timestamps, which show as their UTC date. */
export function evidenceValue(value: string): string {
  return ISO_TIME.test(value) ? new Date(value).toISOString().slice(0, 10) : value;
}

function EvidenceItem({ item }: { item: Evidence }) {
  const location = useLocation();
  if (item.file) {
    const lines =
      item.line_start === undefined
        ? ""
        : item.line_end && item.line_end !== item.line_start
          ? `:${String(item.line_start)}–${String(item.line_end)}`
          : `:${String(item.line_start)}`;
    return (
      <li>
        <Link to={fileHref(location.pathname, location.search, item.file, item.line_start)}>
          <code>
            {item.file}
            {lines}
          </code>
        </Link>
        {item.side === "old" ? " (previous release)" : ""}
      </li>
    );
  }
  const change =
    item.before !== undefined || item.after !== undefined
      ? `${evidenceValue(item.before ?? "none")} → ${evidenceValue(item.after ?? "none")}`
      : "";
  return (
    <li>
      {item.attestation_field ? <code>{item.attestation_field}</code> : null}
      {item.attestation_field && change ? ": " : ""}
      {change}
    </li>
  );
}

interface SignalsProps {
  signals: SignalOut[];
  source: SourceCheck | null | undefined;
}

/** Section 3: what changed that matters, most severe first, with links to the evidence. */
export function Signals({ signals, source }: SignalsProps) {
  const sorted = [...signals].sort((a, b) => ORDER.indexOf(a.level) - ORDER.indexOf(b.level));
  const high = signals.filter((s) => s.level === "high").length;
  const check = signals.filter((s) => s.level === "check").length;
  const summary = high || check ? `${String(high)} high, ${String(check)} to check` : "Nothing unusual";

  return (
    <section className="panel" aria-label="Signals">
      <h2>
        <span className="grow">What changed that matters</span>
        <span className="hint">{summary}</span>
      </h2>
      <ul className="sigs">
        {sorted.map((signal, i) => (
          <li key={`${signal.rule_id}-${String(i)}`}>
            <span className={`lvl ${signal.level}`}>{signal.level}</span>
            <div>
              <MessageText text={signal.message} />
              {signal.evidence.length > 0 && (
                <ul className="evidence" aria-label="Evidence">
                  {(signal.evidence as Evidence[]).slice(0, 12).map((item, j) => (
                    <EvidenceItem key={j} item={item} />
                  ))}
                  {signal.evidence.length > 12 && <li>and {signal.evidence.length - 12} more</li>}
                </ul>
              )}
            </div>
          </li>
        ))}
        {source?.state === "could_not_compare" && (
          <li>
            <span className="lvl info">note</span>
            <span>
              Couldn&apos;t compare with the source
              {source.repository ? (
                <>
                  {" "}
                  in <code>{source.repository}</code>
                </>
              ) : (
                ""
              )}
              : {source.detail ?? source.reason}
            </span>
          </li>
        )}
        {source?.state === "unknown" && (
          <li>
            <span className="lvl info">note</span>
            <span>The source wasn&apos;t checked for this pair.</span>
          </li>
        )}
        {sorted.length === 0 && (
          <li>
            <span className="lvl clean">clean</span>
            <span>No signals for this pair: nothing the rules look for changed.</span>
          </li>
        )}
      </ul>
    </section>
  );
}
