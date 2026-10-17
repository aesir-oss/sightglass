import { useState, type SubmitEvent } from "react";
import { useNavigate } from "react-router";

/** Start page: pick a PyPI package and the releases to compare. */
export function HomePage() {
  const navigate = useNavigate();
  const [pkg, setPkg] = useState("");
  const [versions, setVersions] = useState("");

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = pkg.trim();
    if (!name) return;
    const path = versions.trim() ? `/pypi/${name}/${versions.trim()}` : `/pypi/${name}`;
    void navigate(path);
  }

  return (
    <main className="wrap home">
      <h1>Sightglass</h1>
      <p className="lede">
        See what a package release actually ships: what changed since the last release, whether it matches its source,
        and how it was published.
      </p>
      <form onSubmit={submit} aria-label="Compare releases" className="panel home-form">
        <label>
          <span>PyPI package</span>
          <input
            className="field"
            name="package"
            placeholder="sampleproject"
            autoComplete="off"
            value={pkg}
            onChange={(e) => {
              setPkg(e.target.value);
            }}
            required
          />
        </label>
        <label>
          <span>Releases</span>
          <input
            className="field"
            name="versions"
            placeholder="3.0.0...4.0.0, or one version"
            autoComplete="off"
            value={versions}
            onChange={(e) => {
              setVersions(e.target.value);
            }}
          />
        </label>
        <button type="submit" className="btn primary">
          Compare
        </button>
      </form>
      <p className="hint-text">
        Leave the releases empty to see the newest release compared with the one before it. Sightglass reads files and
        metadata only and never runs package code.
      </p>
    </main>
  );
}
