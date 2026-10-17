import { useParams, useSearchParams } from "react-router";
import { ApiError, artifactFromSearch } from "../api/client";
import { usePairAnalysis } from "../api/queries";

/** The release diff page for `/:ecosystem/:package/:versions`. Its sections arrive with the page issues. */
export function ReleaseDiffPage() {
  const { ecosystem = "", package: pkg = "", versions = "" } = useParams();
  const [search] = useSearchParams();
  const pair = usePairAnalysis(ecosystem, pkg, versions, artifactFromSearch(search));

  return (
    <main className="wrap">
      <h1>
        {pkg} <span>{versions.replace("...", " → ")}</span>
      </h1>
      {pair.isPending && <p role="status">Loading…</p>}
      {pair.isError && (
        <p className="notice" data-tone="warn" role="alert">
          {pair.error instanceof ApiError && pair.error.status === 404
            ? pair.error.message
            : "Sightglass couldn't load this comparison. Try again shortly."}
        </p>
      )}
      {pair.data?.status === "pending" && (
        <p className="notice" role="status">
          Analyzing {pair.data.artifact.old_filename} and {pair.data.artifact.new_filename}. This page updates when it
          is done.
        </p>
      )}
      {pair.data?.status === "failed" && (
        <p className="notice" data-tone="warn" role="alert">
          This pair couldn't be analyzed: {pair.data.error}
        </p>
      )}
      {pair.data?.status === "done" && (
        <p>
          {pair.data.signals.length} signals across {pair.data.files.length} files.
        </p>
      )}
    </main>
  );
}
