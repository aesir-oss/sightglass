import { Link } from "react-router";

export function NotFoundPage() {
  return (
    <main className="wrap">
      <h1>Page not found</h1>
      <p>
        <Link to="/">Back to the start page</Link>
      </p>
    </main>
  );
}
