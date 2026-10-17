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
    <main className="wrap">
      <h1>Sightglass</h1>
      <p>See what a package release actually ships.</p>
      <form onSubmit={submit} aria-label="Compare releases">
        <label>
          PyPI package{" "}
          <input
            name="package"
            value={pkg}
            onChange={(e) => {
              setPkg(e.target.value);
            }}
            required
          />
        </label>{" "}
        <label>
          Releases{" "}
          <input
            name="versions"
            placeholder="2.4.1...2.5.0"
            value={versions}
            onChange={(e) => {
              setVersions(e.target.value);
            }}
          />
        </label>{" "}
        <button type="submit">Compare</button>
      </form>
    </main>
  );
}
