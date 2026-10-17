import type { ReactNode, SVGProps } from "react";

interface MarkProps extends Omit<SVGProps<SVGGElement>, "children"> {
  /** What the mark shows, read by screen readers and shown in the tooltip. */
  label: string;
  tabIndex: number;
  onActivate?: () => void;
  children: ReactNode;
}

/** A focusable chart mark with a text alternative; Enter or Space activates it like a click. */
export function Mark({ label, tabIndex, onActivate, children, ...rest }: MarkProps) {
  return (
    <g
      data-mark=""
      role="button"
      aria-label={label}
      tabIndex={tabIndex}
      onClick={onActivate}
      onKeyDown={(event) => {
        if (onActivate && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          onActivate();
        }
      }}
      {...rest}
    >
      <title>{label}</title>
      {children}
    </g>
  );
}
