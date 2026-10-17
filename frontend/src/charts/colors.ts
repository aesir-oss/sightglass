// Colors for chart marks, as theme tokens so light and dark follow theme.css.
export type FileStatus = "added" | "removed" | "changed" | "same";
export type SignalLevel = "high" | "check" | "note" | "clean";

const STATUS: Record<FileStatus, string> = {
  added: "var(--add)",
  removed: "var(--rm)",
  changed: "var(--up)",
  same: "var(--same)",
};

const LEVEL: Record<SignalLevel, string> = {
  high: "var(--rm)",
  check: "var(--warn)",
  note: "var(--up)",
  clean: "var(--add)",
};

export function statusColor(status: FileStatus): string {
  return STATUS[status];
}

export function levelColor(level: SignalLevel): string {
  return LEVEL[level];
}
