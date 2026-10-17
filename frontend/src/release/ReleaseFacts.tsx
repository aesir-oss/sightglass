import type { ReactNode } from "react";
import type { Facts } from "../api/types";
import "./release.css";

type Side = Facts["old"];

const DATE = new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" });

function Unknown() {
  return <span className="unknown">unknown</span>;
}

function bytes(n: number): string {
  return n < 1024 ? `${String(n)} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`;
}

interface Row {
  label: string;
  /** Comparable text for both sides; null when the value is unknown. */
  value: (side: Side) => string | null;
  render?: (side: Side) => ReactNode;
  /** Values that differ between any two releases, so a difference isn't highlighted. */
  alwaysDiffers?: boolean;
}

const ROWS: Row[] = [
  {
    label: "Published",
    alwaysDiffers: true,
    value: (s) => s.published_at,
    render: (s) => (s.published_at ? `${DATE.format(new Date(s.published_at))} UTC` : <Unknown />),
  },
  {
    label: "Publisher",
    value: (s) =>
      s.publisher
        ? [s.publisher.kind, s.publisher.repository, s.publisher.workflow, s.publisher.environment].join("|")
        : s.attestation === "unknown"
          ? null
          : "none",
    render: (s) =>
      s.publisher ? (
        <>
          {s.publisher.kind}
          {s.publisher.repository ? (
            <>
              {" "}
              <span className="mono">{s.publisher.repository}</span>
            </>
          ) : null}
          {s.publisher.workflow ? (
            <>
              , workflow <span className="mono">{s.publisher.workflow}</span>
            </>
          ) : null}
          {s.publisher.environment ? (
            <>
              , environment <span className="mono">{s.publisher.environment}</span>
            </>
          ) : null}
        </>
      ) : s.attestation === "unknown" ? (
        <Unknown />
      ) : (
        "No trusted publisher"
      ),
  },
  {
    label: "Attestation",
    value: (s) => (s.attestation === "unknown" ? null : s.attestation),
    render: (s) =>
      s.attestation === "unknown" ? <Unknown /> : s.attestation === "present" ? "Attested" : "Not attested",
  },
  {
    label: "Build tool",
    value: (s) => s.build_tool,
    render: (s) => (s.build_tool ? <span className="mono">{s.build_tool}</span> : <Unknown />),
  },
  { label: "Files", value: (s) => String(s.file_count) },
  { label: "Installed size", value: (s) => String(s.total_size), render: (s) => bytes(s.total_size) },
  {
    label: "Artifact sha256",
    alwaysDiffers: true,
    value: (s) => s.artifact_sha256,
    render: (s) => <span className="mono">{s.artifact_sha256}</span>,
  },
  {
    label: "Declared dependencies",
    value: (s) => (s.requires_dist ? s.requires_dist.join("\n") : null),
    render: (s) =>
      s.requires_dist === null ? (
        <Unknown />
      ) : s.requires_dist.length === 0 ? (
        "None"
      ) : (
        <ul>
          {s.requires_dist.map((r) => (
            <li key={r} className="mono">
              {r}
            </li>
          ))}
        </ul>
      ),
  },
];

/** Section 7: a before-and-after table of release facts, with changed rows highlighted. */
export function ReleaseFacts({ facts }: { facts: Facts | null | undefined }) {
  return (
    <section className="panel" aria-label="Release facts">
      <h2>
        <span className="grow">Release facts</span>
      </h2>
      {facts ? (
        <div className="facts-wrap">
          <table className="facts">
            <thead>
              <tr>
                <th scope="col">
                  <span className="sr-only">Fact</span>
                </th>
                <th scope="col">{facts.old.version}</th>
                <th scope="col">{facts.new.version}</th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map((row) => {
                const before = row.value(facts.old);
                const after = row.value(facts.new);
                // Only a difference between two known values is a change; unknown is not a change.
                const changed = !row.alwaysDiffers && before !== null && after !== null && before !== after;
                const show = row.render ?? row.value;
                return (
                  <tr key={row.label} className={changed ? "changed" : undefined}>
                    <th scope="row">
                      {row.label}
                      {changed && <span className="sr-only"> (changed)</span>}
                    </th>
                    <td>{show(facts.old) ?? <Unknown />}</td>
                    <td>{show(facts.new) ?? <Unknown />}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="note">Release facts aren&apos;t available for this analysis.</p>
      )}
    </section>
  );
}
