import { useState } from "react";
import { applyTheme, savedTheme, THEMES, type Theme } from "./theme";

const LABELS: Record<Theme, string> = { light: "Light", dark: "Dark", auto: "Auto" };

function Icon({ theme }: { theme: Theme }) {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false">
      {theme === "light" && (
        <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </g>
      )}
      {theme === "dark" && (
        <path
          d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5Z"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinejoin="round"
        />
      )}
      {theme === "auto" && (
        <g>
          <circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" strokeWidth="2" />
          <path d="M12 4a8 8 0 0 1 0 16Z" fill="currentColor" />
        </g>
      )}
    </svg>
  );
}

/** One button that steps through light, dark and auto (follow the system), showing the current choice's icon. */
export function ThemeSwitch() {
  const [theme, setTheme] = useState<Theme>(savedTheme);
  const next = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length] ?? "auto";
  return (
    <button
      type="button"
      className="theme-switch"
      aria-label={`Theme: ${LABELS[theme]}`}
      title={`Theme: ${LABELS[theme]}. Switch to ${LABELS[next]}.`}
      onClick={() => {
        setTheme(next);
        applyTheme(next);
      }}
    >
      <Icon theme={theme} />
    </button>
  );
}
