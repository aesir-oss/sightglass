import { useState, type MouseEvent } from "react";
import type { ReleaseSummary } from "../api/types";
import { Mark } from "../charts/Mark";
import { Tooltip } from "../charts/Tooltip";
import { timelineLayout, timelineScale } from "../charts/layout";
import { useRovingFocus } from "../charts/useRovingFocus";
import "./release.css";

const W = 1000;
const H = 104;
const AXIS = 50;

interface TimelineProps {
  pkg: string;
  /** Every release, oldest first. */
  releases: ReleaseSummary[];
  from: string;
  to: string;
  /** Show the pair from `from` to `to`. */
  onCompare: (from: string, to: string) => void;
}

const DAY = new Intl.DateTimeFormat("en", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });

function describe(r: ReleaseSummary): string {
  const date = r.published_at ? DAY.format(new Date(r.published_at)) : "unknown date";
  const publisher = r.publisher
    ? `published by ${r.publisher.workflow ?? r.publisher.kind}${r.publisher.repository ? ` in ${r.publisher.repository}` : ""}`
    : "no trusted publisher";
  const attestation = {
    all: "attested",
    some: "some files attested",
    none: "not attested",
    unknown: "attestation unknown",
  }[r.attestation];
  return `${r.version}, ${date}, ${publisher}, ${attestation}${r.yanked ? ", yanked" : ""}`;
}

/** Section 2: every release on a time axis, showing how it was published and whether it is attested. */
export function Timeline({ pkg, releases, from, to, onCompare }: TimelineProps) {
  const points = timelineLayout(releases, W, { padding: 30, minGap: 14 });
  const focus = useRovingFocus(
    points.length,
    Math.max(
      0,
      points.findIndex((p) => p.release.version === to),
    ),
  );
  const [tip, setTip] = useState<{ x: number; label: string } | null>(null);
  const order = releases.map((r) => r.version);
  const x = (version: string) => points.find((p) => p.release.version === version)?.x;
  const [fromX, toX] = [x(from), x(to)];
  const scale = timelineScale(releases, W, 30);
  const years = [...new Set(points.map((p) => new Date(p.release.published_at ?? 0).getUTCFullYear()))];
  // A tick at the start of each year after the first.
  const ticks = scale ? years.slice(1).map((year) => ({ year, x: scale(new Date(Date.UTC(year, 0, 1))) })) : [];

  function activate(version: string, shift: boolean) {
    if (shift) {
      onCompare(version, to);
      return;
    }
    const before = order[order.indexOf(version) - 1];
    if (before) onCompare(before, version);
  }

  return (
    <section className="wrap" aria-label="Release history">
      <div className="panel">
        <h2>
          <span className="grow">Release history</span>
          <span className="hint">
            Select a release to compare it with the one before. Shift-select to make it the starting release.
          </span>
        </h2>
        <div className="tl">
          <svg
            className="timeline"
            viewBox={`0 0 ${String(W)} ${String(H)}`}
            role="group"
            aria-label={`Timeline of ${pkg} releases`}
            onKeyDown={focus.onKeyDown}
          >
            <line className="tl-axis" x1={30} x2={W - 30} y1={AXIS} y2={AXIS} />
            {fromX !== undefined && toX !== undefined && (
              <rect
                className="tl-band"
                x={Math.min(fromX, toX)}
                y={AXIS - 14}
                width={Math.max(2, Math.abs(toX - fromX))}
                height={28}
                rx={14}
              />
            )}
            {ticks.map(({ year, x: tx }) => (
              <g key={year}>
                <line className="tl-tick" x1={tx} x2={tx} y1={AXIS + 20} y2={AXIS + 30} />
                <text className="tl-year" x={tx + 4} y={AXIS + 39}>
                  {year}
                </text>
              </g>
            ))}
            {points.map(({ release: r, x: px }, i) => {
              const up = i % 2 === 0;
              const end = r.version === from || r.version === to;
              const label = describe(r);
              return (
                <Mark
                  key={r.version}
                  className={`tl-g${end ? " end" : ""}`}
                  label={label}
                  tabIndex={focus.tabIndexFor(i)}
                  onActivate={() => {
                    activate(r.version, false);
                  }}
                  onClick={(event: MouseEvent) => {
                    activate(r.version, event.shiftKey);
                  }}
                  onKeyDownCapture={(event) => {
                    if (event.shiftKey && (event.key === "Enter" || event.key === " ")) {
                      event.preventDefault();
                      event.stopPropagation();
                      activate(r.version, true);
                    }
                  }}
                  onFocus={() => {
                    focus.setActive(i);
                    setTip({ x: px, label });
                  }}
                  onBlur={() => {
                    setTip(null);
                  }}
                  onMouseEnter={() => {
                    setTip({ x: px, label });
                  }}
                  onMouseLeave={() => {
                    setTip(null);
                  }}
                >
                  <circle className="tl-ring" cx={px} cy={AXIS} r={11} />
                  <circle
                    className={`tl-dot ${r.publisher ? "trusted" : "other"}`}
                    cx={px}
                    cy={AXIS}
                    r={end ? 7 : 5.5}
                  />
                  <text className="tl-lbl" x={px} y={up ? AXIS - 20 : AXIS + 28} textAnchor="middle">
                    {r.version}
                  </text>
                  <text
                    className={`tl-att${r.attestation === "none" ? " no" : ""}`}
                    x={px}
                    y={up ? AXIS - 32 : AXIS + 40}
                    textAnchor="middle"
                  >
                    {r.attestation === "unknown" ? "?" : r.attestation === "none" ? "NO ATT" : "ATT"}
                  </text>
                </Mark>
              );
            })}
          </svg>
          <Tooltip at={tip ? { x: `${String((tip.x / W) * 100)}%`, y: 18 } : null}>{tip?.label}</Tooltip>
        </div>
        <div className="legend">
          <span>
            <i className="sw" style={{ background: "var(--accent)", borderColor: "var(--accent)" }} />
            Trusted publisher
          </span>
          <span>
            <i className="sw" style={{ background: "var(--surface)", borderColor: "var(--rm)" }} />
            No trusted publisher
          </span>
          <span>ATT: provenance attestation. ?: not yet known.</span>
        </div>
      </div>
    </section>
  );
}
