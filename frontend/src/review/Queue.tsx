import { ListBox, ListBoxItem, type Selection } from "react-aria-components";
import type { ReviewChange } from "../api/types";
import "./review.css";

export function changeKey(change: ReviewChange): string {
  return `${change.ecosystem}:${change.package}`;
}

function versions(change: ReviewChange): string {
  if (change.kind === "added") return `new at ${change.to_version ?? ""}`;
  if (change.kind === "removed") return `${change.from_version ?? ""} removed`;
  return `${change.from_version ?? ""} → ${change.to_version ?? ""}`;
}

function badge(change: ReviewChange): { className: string; text: string } {
  const { state, level } = change.analysis;
  if (state === "done" && level) return { className: `lvl ${level}`, text: level };
  if (state === "pending") return { className: "lvl info", text: "analyzing" };
  if (state === "failed") return { className: "lvl check", text: "failed" };
  return { className: "lvl info", text: change.ecosystem === "conda" ? "conda" : "not analyzed" };
}

/** What a screen reader hears for one change: the package, the change, and what the analysis found. */
export function describeChange(change: ReviewChange): string {
  const { state, level, counts } = change.analysis;
  const found =
    state === "done"
      ? level === "high" || level === "check"
        ? `${String(counts[level] ?? 0)} ${level} signals`
        : "nothing that needs a look"
      : state === "pending"
        ? "still analyzing"
        : state === "failed"
          ? "the analysis failed"
          : "not analyzed";
  const platforms = change.only_some_platforms ? `, only on ${change.platforms.join(", ")}` : "";
  const downgrade = change.downgrade ? ", a downgrade" : "";
  return `${change.package}, ${versions(change)}${downgrade}, ${found}${platforms}`;
}

interface QueueProps {
  changes: ReviewChange[];
  platforms: string[];
  platform: string | null;
  onPlatform: (platform: string | null) => void;
  selected: string | null;
  onSelect: (key: string) => void;
}

/** The changed packages, the ones that need a look first, filterable by platform. */
export function Queue({ changes, platforms, platform, onPlatform, selected, onSelect }: QueueProps) {
  const shown = platform ? changes.filter((c) => c.platforms.includes(platform)) : changes;
  return (
    <section className="panel" aria-label="Changes">
      <h2>
        <span className="grow">Changes</span>
        <span className="hint">
          {shown.length} of {changes.length} packages
        </span>
      </h2>
      {platforms.length > 1 && (
        <div className="seg" role="group" aria-label="Platform">
          {[null, ...platforms].map((p) => (
            <button
              key={p ?? "all"}
              type="button"
              aria-pressed={platform === p}
              onClick={() => {
                onPlatform(p);
              }}
            >
              {p ?? "All platforms"}
            </button>
          ))}
        </div>
      )}
      {shown.length === 0 ? (
        <p className="notice" role="status">
          {changes.length === 0
            ? "This change doesn't add, remove or move any package."
            : `No package changes on ${platform ?? ""}.`}
        </p>
      ) : (
        <ListBox
          className="queue"
          aria-label="Package changes"
          selectionMode="single"
          // Moving with the arrow keys selects, so the detail follows the keyboard as it does the mouse.
          selectionBehavior="replace"
          disallowEmptySelection
          selectedKeys={selected ? [selected] : []}
          onSelectionChange={(keys: Selection) => {
            const [key] = keys === "all" ? [] : [...keys];
            if (key !== undefined) onSelect(String(key));
          }}
          items={shown.map((c) => ({ id: changeKey(c), change: c }))}
        >
          {({ change }) => {
            const b = badge(change);
            return (
              <ListBoxItem id={changeKey(change)} textValue={describeChange(change)} className="qitem">
                <span className={b.className}>{b.text}</span>
                <span className="qname">{change.package}</span>
                <span className="qver">
                  {versions(change)}
                  {change.downgrade && <span className="qdown">downgrade</span>}
                </span>
                {change.only_some_platforms && <span className="qplat">only on {change.platforms.join(", ")}</span>}
                {change.path.length > 1 && <span className="qpath">via {change.path.slice(0, -1).join(" → ")}</span>}
              </ListBoxItem>
            );
          }}
        </ListBox>
      )}
    </section>
  );
}
