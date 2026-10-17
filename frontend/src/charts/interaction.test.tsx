import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { Mark } from "./Mark";
import { Tooltip } from "./Tooltip";
import { useRovingFocus } from "./useRovingFocus";

function at<T>(items: readonly T[], i: number): T {
  const item = items[i];
  if (item === undefined) throw new Error(`no item ${String(i)}`);
  return item;
}

afterEach(cleanup);

function Chart({ onPick }: { onPick: (i: number) => void }) {
  const labels = ["2.4.1", "2.4.2", "2.5.0"];
  const focus = useRovingFocus(labels.length);
  return (
    <svg onKeyDown={focus.onKeyDown}>
      {labels.map((label, i) => (
        <Mark
          key={label}
          label={`Release ${label}`}
          tabIndex={focus.tabIndexFor(i)}
          onActivate={() => {
            onPick(i);
          }}
        >
          <circle r={4} />
        </Mark>
      ))}
    </svg>
  );
}

test("one mark is tabbable and arrow keys, Home and End move focus", () => {
  render(<Chart onPick={() => undefined} />);
  const marks = screen.getAllByRole("button");
  expect(marks.map((m) => m.getAttribute("tabindex"))).toEqual(["0", "-1", "-1"]);
  at(marks, 0).focus();
  fireEvent.keyDown(at(marks, 0), { key: "ArrowRight" });
  expect(document.activeElement).toBe(marks[1]);
  expect(marks.map((m) => m.getAttribute("tabindex"))).toEqual(["-1", "0", "-1"]);
  fireEvent.keyDown(at(marks, 1), { key: "End" });
  expect(document.activeElement).toBe(marks[2]);
  fireEvent.keyDown(at(marks, 2), { key: "ArrowDown" });
  expect(document.activeElement).toBe(marks[2]);
  fireEvent.keyDown(at(marks, 2), { key: "Home" });
  fireEvent.keyDown(at(marks, 0), { key: "ArrowUp" });
  expect(document.activeElement).toBe(marks[0]);
  fireEvent.keyDown(at(marks, 0), { key: "a" });
  expect(document.activeElement).toBe(marks[0]);
});

test("marks have a text alternative and activate with click, Enter or Space", () => {
  const onPick = vi.fn();
  render(<Chart onPick={onPick} />);
  const mark = screen.getByRole("button", { name: "Release 2.4.2" });
  expect(mark.querySelector("title")?.textContent).toBe("Release 2.4.2");
  fireEvent.click(mark);
  fireEvent.keyDown(mark, { key: "Enter" });
  fireEvent.keyDown(mark, { key: " " });
  fireEvent.keyDown(mark, { key: "x" });
  expect(onPick.mock.calls).toEqual([[1], [1], [1]]);
});

test("a mark without an action ignores keys; an empty chart has no focus target", () => {
  render(
    <svg>
      <Mark label="Static" tabIndex={0}>
        <rect />
      </Mark>
    </svg>,
  );
  fireEvent.keyDown(screen.getByRole("button", { name: "Static" }), { key: "Enter" });

  function Empty() {
    const focus = useRovingFocus(0);
    return (
      <svg onKeyDown={focus.onKeyDown} data-testid="empty" data-active={focus.active}>
        <g />
      </svg>
    );
  }
  render(<Empty />);
  fireEvent.keyDown(screen.getByTestId("empty"), { key: "ArrowRight" });
  expect(screen.getByTestId("empty").getAttribute("data-active")).toBe("0");
});

test("tooltips render text at a position, or nothing", () => {
  const { rerender } = render(<Tooltip at={null}>hidden</Tooltip>);
  expect(screen.queryByRole("tooltip")).toBeNull();
  rerender(<Tooltip at={{ x: 10, y: 20 }}>{"<b>orbit/sync.py</b>"}</Tooltip>);
  const tip = screen.getByRole("tooltip");
  expect(tip.textContent).toBe("<b>orbit/sync.py</b>");
  expect(tip.style.left).toBe("10px");
});
