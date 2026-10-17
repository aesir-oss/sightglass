import type { ReactNode } from "react";

interface TooltipProps {
  /** Position in the chart container, in pixels or as CSS lengths; nothing is shown when null. */
  at: { x: number | string; y: number | string } | null;
  children: ReactNode;
}

/** A tooltip over a chart, positioned near the hovered or focused mark. Text only. */
export function Tooltip({ at, children }: TooltipProps) {
  if (!at) return null;
  return (
    <div
      role="tooltip"
      style={{
        position: "absolute",
        left: at.x,
        top: at.y,
        transform: "translate(-50%, calc(-100% - 8px))",
        pointerEvents: "none",
        background: "var(--surface)",
        color: "var(--ink)",
        border: "1px solid var(--line)",
        borderRadius: 6,
        padding: "6px 8px",
        fontSize: 13,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </div>
  );
}
