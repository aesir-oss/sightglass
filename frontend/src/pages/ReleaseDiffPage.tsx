import { useParams, useSearchParams } from "react-router";
import { ApiError, artifactFromSearch } from "../api/client";
import { usePairAnalysis, useReleaseHistory } from "../api/queries";
import { Header } from "../release/Header";

/** The release diff page for `/:ecosystem/:package/:versions`. Its sections arrive with the page issues. */
export function ReleaseDiffPage() {
  const { ecosystem = "", package: pkg = "", versions = "" } = useParams();
  const [search] = useSearchParams();
  const pair = usePairAnalysis(ecosystem, pkg, versions, artifactFromSearch(search));
  const history = useReleaseHistory(ecosystem, pkg);
  const data = pair.data;

  return (
    <>
      {data ? (
        <Header
          ecosystem={ecosystem}
          pkg={data.package}
          from={data.from_version}
          to={data.to_version}
          versions={history.data?.releases.map((r) => r.version) ?? [data.from_version, data.to_version]}
          artifact={data.artifact}
          alternatives={data.alternatives}
        />
      ) : (
        <header className="top">
          <div className="wrap">
            <h1>
              {pkg} <span>{versions.replace("...", " → ")}</span>
            </h1>
          </div>
        </header>
      )}
      <main className="wrap">
        {pair.isPending && <p role="status">Loading…</p>}
        {pair.isError && (
          <p className="notice" data-tone="warn" role="alert">
            {pair.error instanceof ApiError && pair.error.status === 404
              ? pair.error.message
              : "Sightglass couldn't load this comparison. Try again shortly."}
          </p>
        )}
        {data?.status === "pending" && (
          <p className="notice" role="status">
            Analyzing {data.artifact.old_filename} and {data.artifact.new_filename}. This page updates when it is done.
          </p>
        )}
        {data?.status === "failed" && (
          <p className="notice" data-tone="warn" role="alert">
            This pair couldn&apos;t be analyzed: {data.error}
          </p>
        )}
        {data?.status === "done" && (
          <p>
            {data.signals.length} signals across {data.files.length} files.
          </p>
        )}
      </main>
    </>
  );
}
