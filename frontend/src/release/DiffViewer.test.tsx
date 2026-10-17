import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { FileDiff } from "../api/types";
import { fakeApi } from "../test/server";
import { DiffViewer, type Base } from "./DiffViewer";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const URL = "/api/pypi/orbit-client/2.4.1...2.5.0/files/orbit%2Fsync.py";
const SHOWN: FileDiff = {
  path: "orbit/sync.py",
  base: "previous",
  base_label: "2.4.1",
  status: "changed",
  text: true,
  old_path: "orbit/sync.py",
  old_sha256: "a".repeat(64),
  new_sha256: "b".repeat(64),
  old_size: 10,
  new_size: 40,
  diff: "shown",
  added: 2,
  removed: 1,
  signals: ["behavior.network"],
  hunks: [
    {
      old_start: 9,
      old_len: 2,
      new_start: 9,
      new_len: 3,
      lines: [
        { kind: "context", old_line: 9, new_line: 9, text: "x = 1", missing_newline: false, marked: false },
        { kind: "removed", old_line: 10, new_line: null, text: "y = 2", missing_newline: false, marked: false },
        { kind: "added", old_line: null, new_line: 10, text: "import socket", missing_newline: false, marked: false },
        {
          kind: "added",
          old_line: null,
          new_line: 11,
          text: "<script>alert(1)</script>",
          missing_newline: true,
          marked: true,
        },
      ],
    },
  ],
};

function renderViewer(over: { file?: string | null; line?: number | null; base?: Base; inSource?: boolean } = {}) {
  const onBase = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <DiffViewer
        ecosystem="pypi"
        pkg="orbit-client"
        versions="2.4.1...2.5.0"
        artifact={{}}
        file={over.file === undefined ? "orbit/sync.py" : over.file}
        line={over.line ?? null}
        base={over.base ?? "previous"}
        inSource={over.inSource ?? true}
        onBase={onBase}
      />
    </QueryClientProvider>,
  );
  return onBase;
}

test("a diff renders hunks as text with line numbers, and marks signal lines", async () => {
  fakeApi({ [`${URL}?base=previous`]: { body: SHOWN } });
  const scroll = vi.fn();
  Element.prototype.scrollIntoView = scroll;
  renderViewer({ line: 11 });
  const table = await screen.findByRole("table", { name: "Diff of orbit/sync.py" });
  expect(screen.getByText("compared with release 2.4.1")).toBeTruthy();
  expect(screen.getByText("+2 −1")).toBeTruthy();
  const rows = table.querySelectorAll("tr");
  expect(rows[0]?.textContent).toBe("@@ −9,2 +9,3 @@");
  const hit = table.querySelector("tr.hit");
  expect(hit?.textContent).toContain("<script>alert(1)</script>");
  expect(hit?.textContent).toContain("Flagged: ");
  expect(hit?.className).toContain("target");
  expect(document.querySelector("script")).toBeNull();
  expect(scroll).toHaveBeenCalled();
});

test("the base toggles between the previous release and the source", async () => {
  fakeApi({
    [`${URL}?base=source`]: {
      body: { ...SHOWN, base: "source", base_label: "tag v2.5.0", old_path: "src/orbit/sync.py" },
    },
  });
  const onBase = renderViewer({ base: "source" });
  expect(await screen.findByText("compared with tag v2.5.0 (src/orbit/sync.py)")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Previous release" }));
  expect(onBase).toHaveBeenCalledWith("previous");
  fireEvent.click(screen.getByRole("button", { name: "Source" }));
  expect(onBase).toHaveBeenLastCalledWith("source");
});

test("without a source counterpart the source option is disabled and the previous release is used", async () => {
  const { requests } = fakeApi({ [`${URL}?base=previous`]: { body: SHOWN } });
  renderViewer({ base: "source", inSource: false });
  await screen.findByRole("table");
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "Source" }).disabled).toBe(true);
  expect(requests).toEqual([`${URL}?base=previous`]);
});

test.each([
  ["binary", "Binary file, so no line diff: 10 → 40 bytes, sha256 aaaaaaaaaaaa → bbbbbbbbbbbb."],
  ["too_large", "Too large to diff here"],
  ["unavailable", "The contents weren't kept"],
  ["identical", "The contents are identical."],
] as const)("%s files show metadata, not a diff", async (kind, text) => {
  fakeApi({ [`${URL}?base=previous`]: { body: { ...SHOWN, diff: kind, hunks: [] } } });
  renderViewer();
  expect((await screen.findByText(new RegExp(text.replace(/[.()]/g, "\\$&")))).className).toBe("note");
  expect(screen.queryByRole("table")).toBeNull();
});

test("no selection, missing hashes and errors are explained", async () => {
  renderViewer({ file: null });
  expect(screen.getByText("Select a file in the map or list to see its diff.")).toBeTruthy();
  cleanup();
  fakeApi({
    [`${URL}?base=previous`]: { body: { ...SHOWN, diff: "binary", old_sha256: null, old_size: null, hunks: [] } },
  });
  renderViewer();
  expect(await screen.findByText(/0 → 40 bytes, sha256 none/)).toBeTruthy();
  cleanup();
  fakeApi({ [`${URL}?base=previous`]: { status: 404, body: { detail: "this pair isn't analyzed yet" } } });
  renderViewer();
  expect((await screen.findByRole("alert")).textContent).toBe("this pair isn't analyzed yet");
  cleanup();
  vi.stubGlobal("fetch", () => Promise.reject(new TypeError("offline")));
  renderViewer();
  expect((await screen.findByRole("alert")).textContent).toBe("The diff couldn't be loaded.");
});
