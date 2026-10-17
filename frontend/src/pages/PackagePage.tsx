import { Navigate, useParams } from "react-router";
import { ApiError } from "../api/client";
import { useReleaseHistory } from "../api/queries";

/** `/:ecosystem/:package`: go to the newest release, compared with the one before it. */
export function PackagePage() {
  const { ecosystem = "", package: pkg = "" } = useParams();
  const history = useReleaseHistory(ecosystem, pkg);
  const latest = history.data?.releases.at(-1)?.version;
  if (latest) return <Navigate replace to={`/${ecosystem}/${encodeURIComponent(pkg)}/${encodeURIComponent(latest)}`} />;
  return (
    <main className="wrap stack">
      <h1>{pkg}</h1>
      {history.isPending && (
        <p className="notice" role="status">
          Loading releases…
        </p>
      )}
      {history.isError && (
        <p className="notice" data-tone="warn" role="alert">
          {history.error instanceof ApiError && history.error.status === 404
            ? history.error.message
            : "Sightglass couldn't load this package's releases. Try again shortly."}
        </p>
      )}
      {history.data && (
        <p className="notice" role="status">
          This package has no releases to compare.
        </p>
      )}
    </main>
  );
}
