import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import type { Facts } from "../api/types";
import { ReleaseFacts } from "./ReleaseFacts";

afterEach(cleanup);

const old: Facts["old"] = {
  version: "2.4.1",
  published_at: "2026-09-01T12:00:00Z",
  attestation: "present",
  publisher: {
    kind: "GitHub",
    repository: "kestrel-weather/orbit-client",
    workflow: "release.yml",
    environment: "pypi",
  },
  build_tool: "hatchling",
  file_count: 12,
  total_size: 40_000,
  artifact_sha256: "a".repeat(64),
  requires_dist: ["httpx>=0.27"],
};

function row(name: string): HTMLElement {
  const header = screen.getByRole("rowheader", { name: new RegExp(`^${name}`) });
  const tr = header.closest("tr");
  if (!tr) throw new Error(`no row ${name}`);
  return tr;
}

test("rows compare both releases and highlight what changed", () => {
  const facts: Facts = {
    old,
    new: {
      ...old,
      version: "2.5.0",
      published_at: "2026-10-01T09:30:00Z",
      attestation: "absent",
      publisher: null,
      file_count: 13,
      total_size: 2_500_000,
      artifact_sha256: "b".repeat(64),
      requires_dist: ["httpx>=0.27", "requests>=2.32"],
    },
  };
  render(<ReleaseFacts facts={facts} />);
  expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Fact", "2.4.1", "2.5.0"]);
  expect(row("Published").textContent).toContain("Sep 1, 2026, 12:00 PM UTC");
  expect(row("Publisher").className).toBe("changed");
  expect(row("Publisher").textContent).toContain(
    "GitHub kestrel-weather/orbit-client, workflow release.yml, environment pypi",
  );
  expect(row("Publisher").textContent).toContain("No trusted publisher");
  expect(row("Attestation").textContent).toBe("Attestation (changed)AttestedNot attested");
  expect(row("Build tool").className).toBe("");
  expect(row("Installed size").textContent).toContain("39.1 KB2.4 MB");
  expect(
    within(row("Declared dependencies"))
      .getAllByRole("listitem")
      .map((li) => li.textContent),
  ).toEqual(["httpx>=0.27", "httpx>=0.27", "requests>=2.32"]);
});

test("unknown values say unknown and are never counted as changes", () => {
  const unknown: Facts["old"] = {
    ...old,
    version: "2.5.0",
    published_at: null,
    attestation: "unknown",
    publisher: null,
    build_tool: null,
    requires_dist: null,
    total_size: 500,
  };
  render(<ReleaseFacts facts={{ old, new: unknown }} />);
  for (const name of ["Published", "Publisher", "Attestation", "Build tool", "Declared dependencies"]) {
    expect(row(name).className).toBe("");
    expect(within(row(name)).getByText("unknown")).toBeTruthy();
  }
  expect(row("Installed size").textContent).toContain("500 B");
});

test("no dependencies, and missing facts", () => {
  render(<ReleaseFacts facts={{ old: { ...old, requires_dist: [] }, new: { ...old, requires_dist: [] } }} />);
  expect(row("Declared dependencies").textContent).toBe("Declared dependenciesNoneNone");
  cleanup();
  render(<ReleaseFacts facts={null} />);
  expect(screen.getByText("Release facts aren't available for this analysis.")).toBeTruthy();
});
