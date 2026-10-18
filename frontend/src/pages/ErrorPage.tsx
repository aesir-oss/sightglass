import { Link, useRouteError } from "react-router";

/** What a page shows when it fails while rendering, instead of React Router's developer screen. */
export function ErrorPage() {
  const error = useRouteError();
  const detail = error instanceof Error ? error.message : null;
  return (
    <main className="wrap stack">
      <h1>Something went wrong on this page</h1>
      <p className="notice" data-tone="warn" role="alert">
        Sightglass couldn't show this page. Reloading may help; if it doesn&apos;t, the details below say what failed.
      </p>
      {detail && (
        <details>
          <summary>Details</summary>
          <pre className="error-detail">{detail}</pre>
        </details>
      )}
      <p>
        <Link to="/">Back to the start page</Link>
      </p>
    </main>
  );
}
