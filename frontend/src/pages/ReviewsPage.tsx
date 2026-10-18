import { Link } from "react-router";
import { useReviews } from "../api/queries";
import type { ReviewSummary } from "../api/types";
import { ReviewForm } from "../review/ReviewForm";
import { ThemeSwitch } from "../ThemeSwitch";
import "../release/release.css";
import "../review/review.css";

const DATE = new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" });
const KINDS = ["added", "changed", "removed"] as const;

/** "2 added, 1 changed", or that nothing moved. */
export function describeCounts(counts: ReviewSummary["counts"]): string {
  const parts = KINDS.filter((k) => counts[k]).map((k) => `${String(counts[k])} ${k}`);
  return parts.length ? parts.join(", ") : "no package changes";
}

/** `/reviews`: each reviewed pull request's latest review, newest first. */
export function ReviewsPage() {
  const reviews = useReviews();
  const rows = reviews.data?.reviews ?? [];
  return (
    <>
      <header className="top">
        <div className="wrap">
          <div className="crumbrow">
            <nav className="crumbs" aria-label="Breadcrumb">
              <Link to="/">Sightglass</Link> / <span>Reviews</span>
            </nav>
            <ThemeSwitch />
          </div>
          <h1>Pull request reviews</h1>
        </div>
      </header>
      <main className="wrap stack">
        <ReviewForm />
        {reviews.isPending && (
          <p className="notice" role="status">
            Loading…
          </p>
        )}
        {reviews.isError && (
          <p className="notice" data-tone="warn" role="alert">
            Sightglass couldn't load the reviews. Try again shortly.
          </p>
        )}
        {reviews.data && rows.length === 0 && (
          <p className="notice">No reviews yet. Paste a pull request URL above to start one.</p>
        )}
        {rows.length > 0 && (
          <ul className="review-list panel" aria-label="Reviews">
            {rows.map((r) => (
              <li key={`${r.repository}#${String(r.number)}`}>
                <Link to={`/reviews/${r.repository}/${String(r.number)}`}>
                  {r.repository} <span className="vs">#{r.number}</span>
                </Link>
                <span className="review-meta review-what">
                  <code>{r.lockfile_path}</code> at <code>{r.head_sha.slice(0, 7)}</code>, {describeCounts(r.counts)}
                </span>
                <time className="review-meta review-when" dateTime={r.created_at}>
                  {DATE.format(new Date(r.created_at))}
                </time>
              </li>
            ))}
          </ul>
        )}
      </main>
    </>
  );
}
