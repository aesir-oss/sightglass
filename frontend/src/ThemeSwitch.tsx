import { useId, useState } from "react";
import { applyTheme, savedTheme, THEMES, type Theme } from "./theme";

const LABELS: Record<Theme, string> = { light: "Light", dark: "Dark", auto: "Auto" };

/** A light / dark / auto switch. Native radios, so arrow keys and screen readers work as for any radio group. */
export function ThemeSwitch() {
  const [theme, setTheme] = useState<Theme>(savedTheme);
  const name = useId();
  return (
    <fieldset className="theme-switch">
      <legend className="sr-only">Theme</legend>
      {THEMES.map((t) => (
        <label key={t} data-checked={theme === t}>
          <input
            type="radio"
            name={name}
            value={t}
            checked={theme === t}
            onChange={() => {
              setTheme(t);
              applyTheme(t);
            }}
          />
          {LABELS[t]}
        </label>
      ))}
    </fieldset>
  );
}
