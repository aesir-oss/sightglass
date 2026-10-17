// The theme choice: light, dark, or auto (follow the system). Stored per browser; theme.css does the rest.
export type Theme = "light" | "dark" | "auto";

export const THEME_KEY = "sightglass-theme";
export const THEMES: readonly Theme[] = ["light", "dark", "auto"];

/** The saved choice, or auto when there is none or storage isn't available. */
export function savedTheme(): Theme {
  try {
    const value = localStorage.getItem(THEME_KEY);
    return value === "light" || value === "dark" ? value : "auto";
  } catch {
    return "auto";
  }
}

/** Apply a choice to the page and remember it; auto removes the override so the system setting applies. */
export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "auto") delete root.dataset.theme;
  else root.dataset.theme = theme;
  try {
    if (theme === "auto") localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, theme);
  } catch {
    // Private windows and blocked storage: the choice applies to this page only.
  }
}
