// Keyboard navigation across chart marks: one mark is in the tab order, arrow keys move between them.
import { useCallback, useState, type KeyboardEvent } from "react";

export function useRovingFocus(count: number, initial = 0) {
  const [active, setActive] = useState(initial);
  const current = Math.min(active, Math.max(count - 1, 0));

  const onKeyDown = useCallback(
    (event: KeyboardEvent) => {
      const moves: Record<string, number> = {
        ArrowRight: current + 1,
        ArrowDown: current + 1,
        ArrowLeft: current - 1,
        ArrowUp: current - 1,
        Home: 0,
        End: count - 1,
      };
      const next = moves[event.key];
      if (next === undefined || count === 0) return;
      event.preventDefault();
      const clamped = Math.min(Math.max(next, 0), count - 1);
      setActive(clamped);
      const marks = event.currentTarget.querySelectorAll<SVGElement | HTMLElement>("[data-mark]");
      marks[clamped]?.focus();
    },
    [count, current],
  );

  return { active: current, setActive, onKeyDown, tabIndexFor: (i: number) => (i === current ? 0 : -1) };
}
