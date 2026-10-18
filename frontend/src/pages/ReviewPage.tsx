import { Link, useParams, useSearchParams } from "react-router";
import { ApiError } from "../api/client";
import { useReview } from "../api/queries";
import type { ReviewChange } from "../api/types";
import { pairPath } from "../release/urls";
import { changeKey, Queue } from "../review/Queue";
import { ThemeSwitch } from "../ThemeSwitch";
import "../release/release.css";

function Selected({ change }: { change: ReviewChange }) {
  const diff =
    change.ecosystem === "pypi" && change.compare_from && change.to_version
      ? pairPath("pypi", change.package, change.compare_from, change.to_version, "")
      : null;
  return (
    <section className="panel detail" aria-label="Package detail">
      <h2>
        <span className="grow">{change.package}</span>
      </h2>
      <dl>
        <dt>Change</dt>
        <dd>
          {change.kind === "added"
            ? `New dependency at ${change.to_version ?? ""}`
            : change.kind === "removed"
              ? `${change.from_version ?? ""} removed`
              : `${change.from_version ?? ""} → ${change.to_version ?? ""}${change.downgrade ? ", a downgrade to an older version" : ""}`}
        </dd>
        <dt>Why it's here</dt>
        <dd>
          {change.path.length > 1
            ? change.path.join(" → ")
            : change.path.length === 1
              ? "The project asks for it directly"
              : "No path from what the project asks for"}
        </dd>
        <dt>Platforms</dt>
        <dd>
          {change.platforms.join(", ")}
          {change.only_some_platforms ? " (not every platform the environment resolves)" : ""}
        </dd>
        <dt>Environments</dt>
        <dd>{change.environments.join(", ")}</dd>
      </dl>
      {diff && (
        <p>
          <Link className="btn" to={diff}>
            Open the release diff ({change.compare_from} → {change.to_version})
          </Link>
        </p>
      )}
    </section>
  );
}

/** `/reviews/:owner/:repo/:number`: a pull request's lockfile changes, the ones that need a look first. */
export function ReviewPage() {
  const { owner = "", repo = "", number = "" } = useParams();
  const [search, setSearch] = useSearchParams();
  const review = useReview(owner, repo, Number(number));
  const data = review.data;
  const platform = search.get("platform");
  const changes = data?.changes ?? [];
  const selectedKey = search.get("package") ?? (changes[0] ? changeKey(changes[0]) : null);
  const selected = changes.find((c) => changeKey(c) === selectedKey) ?? null;

  function update(name: string, value: string | null) {
    const next = new URLSearchParams(search);
    if (value === null) next.delete(name);
    else next.set(name, value);
    setSearch(next, { replace: true });
  }

  return (
    <>
      <header className="top">
        <div className="wrap">
          <div className="crumbrow">
            <nav className="crumbs" aria-label="Breadcrumb">
              <Link to="/">Sightglass</Link> / <span>Reviews</span> / <span>{`${owner}/${repo}`}</span>
            </nav>
            <ThemeSwitch />
          </div>
          <h1>
            {owner}/{repo} <span className="vs">#{number}</span>
          </h1>
          {data && (
            <p className="review-meta">
              <code>{data.lockfile_path}</code> from <code>{data.base_sha.slice(0, 7)}</code> to{" "}
              <code>{data.head_sha.slice(0, 7)}</code>
            </p>
          )}
        </div>
      </header>
      <main className="wrap stack">
        {review.isPending && (
          <p className="notice" role="status">
            Loading…
          </p>
        )}
        {review.isError && (
          <p className="notice" data-tone="warn" role="alert">
            {review.error instanceof ApiError && review.error.status === 404
              ? review.error.message
              : "Sightglass couldn't load this review. Try again shortly."}
          </p>
        )}
        {data && (
          <div className="review-grid">
            <Queue
              changes={changes}
              platforms={data.platforms}
              platform={platform}
              onPlatform={(p) => {
                update("platform", p);
              }}
              selected={selectedKey}
              onSelect={(key) => {
                update("package", key);
              }}
            />
            {selected && <Selected change={selected} />}
          </div>
        )}
      </main>
    </>
  );
}
