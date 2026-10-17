import type { SdistCheck, SourceCheck as SourceCheckData, SourceFile } from "../api/types";
import "./release.css";

const REASONS: Record<string, string> = {
  no_repository: "The project doesn't link to a GitHub repository.",
  repository_not_found: "The linked repository doesn't exist or isn't public.",
  repository_unreachable: "The repository host couldn't be reached.",
  no_matching_tag: "No git tag matches this version.",
  no_per_package_tags: "The repository doesn't tag releases of this package separately.",
  archive_unreadable: "The source archive couldn't be read.",
  archive_refused: "The source archive was refused by the safe unpacker.",
};

interface SourceCheckProps {
  source: SourceCheckData | null | undefined;
  sdist: SdistCheck | null | undefined;
  /** Select a package file in the diff viewer, compared with the source. */
  onSelect: (path: string) => void;
}

function FileRows({ files, onSelect }: { files: SourceFile[]; onSelect: (path: string) => void }) {
  return (
    <ul className="srclist">
      {files.map((f) => (
        <li key={f.path}>
          <button
            type="button"
            onClick={() => {
              onSelect(f.path);
            }}
          >
            <span className={`st ${f.status}`}>{f.status}</span>
            <span>
              {f.path}
              {f.source_path && f.source_path !== f.path ? ` (${f.source_path})` : ""}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function count(files: SourceFile[], status: SourceFile["status"]): number {
  return files.filter((f) => f.status === status).length;
}

/** Section 6: every package file checked against the source it was built from. */
export function SourceCheck({ source, sdist, onSelect }: SourceCheckProps) {
  const files = source?.files ?? [];
  const problems = files.filter((f) => f.status !== "matches");
  const matching = files.filter((f) => f.status === "matches");
  const notInSdist = (sdist?.files ?? []).filter((f) => f.status === "missing");

  return (
    <section className="panel" aria-label="Source check">
      <h2>
        <span className="grow">Source check</span>
        {source?.state === "compared" && (
          <span className="hint">
            {count(files, "matches")} match, {count(files, "differs")} differ, {count(files, "missing")} missing
          </span>
        )}
      </h2>
      {source?.state === "compared" && (
        <>
          <p className="srcsum">
            <span>
              Compared with <strong>{source.label}</strong>
              {source.origin === "attestation" ? " (the commit named by the attestation)" : ""}
            </span>
            {source.repository && source.commit && (
              <span>
                <a
                  href={`https://github.com/${source.repository}/tree/${source.commit}`}
                  rel="noopener noreferrer"
                  target="_blank"
                >
                  <code>
                    {source.repository}@{source.commit.slice(0, 12)}
                  </code>
                </a>
              </span>
            )}
            {source.root ? (
              <span>
                Package files found under <code>{source.root}</code>
              </span>
            ) : null}
          </p>
          {problems.length > 0 ? (
            <FileRows files={problems} onSelect={onSelect} />
          ) : (
            <p className="note">Every package file matches the source.</p>
          )}
          {matching.length > 0 && (
            <details className="more-files">
              <summary>{matching.length} matching files</summary>
              <FileRows files={matching} onSelect={onSelect} />
            </details>
          )}
          {source.excluded.length > 0 && (
            <details className="more-files">
              <summary>{source.excluded.length} build metadata files not compared</summary>
              <ul className="srclist">
                {source.excluded.map((path) => (
                  <li key={path}>
                    <code>{path}</code>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
      {source?.state === "could_not_compare" && (
        <p className="note" role="status">
          Couldn&apos;t compare with the source. {REASONS[source.reason ?? ""] ?? source.reason}
          {source.detail ? ` (${source.detail})` : ""}
          {source.repository ? (
            <>
              {" "}
              Repository: <code>{source.repository}</code>.
            </>
          ) : null}
        </p>
      )}
      {(!source || source.state === "unknown") && <p className="note">The source wasn&apos;t checked for this pair.</p>}
      {notInSdist.length > 0 && (
        <>
          <p className="srcsum">
            <strong>
              {notInSdist.length} file{notInSdist.length === 1 ? " is" : "s are"} in the wheel but not in the sdist
            </strong>
          </p>
          <FileRows files={notInSdist} onSelect={onSelect} />
        </>
      )}
    </section>
  );
}
