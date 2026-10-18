import { useState, type ReactNode, type SubmitEvent } from "react";
import { Link, useNavigate } from "react-router";
import { ReleaseExample, SignalList, type ExampleSignal } from "../home/ReleaseExample";
import { ThemeSwitch } from "../ThemeSwitch";
import "../home/home.css";

const REPO = "https://github.com/aesir-oss/sightglass";

const LOCKFILE_LINES: { text: string; tone?: "rm" | "add" }[] = [
  { text: "  - pypi: https://files.pythonhosted.org/..." },
  { text: "-   name: orbit-client", tone: "rm" },
  { text: "-   version: 2.4.1", tone: "rm" },
  { text: "-   sha256: 3f9a…c2e1", tone: "rm" },
  { text: "+   name: orbit-client", tone: "add" },
  { text: "+   version: 2.5.0", tone: "add" },
  { text: "+   sha256: 81bd…07fa", tone: "add" },
  { text: "    requires_dist:" },
  { text: "    - httpx>=0.27" },
  { text: "  … 1,184 more lines" },
];

const GAP_SIGNALS: ExampleSignal[] = [
  { level: "high", text: "Attestation present in 2.4.1, missing in 2.5.0." },
  { level: "high", text: "A package file in the wheel isn’t in the git tag." },
  { level: "high", text: "New code runs at import time." },
  { level: "check", text: "Published in the last 7 days." },
  { level: "note", text: "First release in 5 months." },
];

const PILLARS: { title: string; body: string; example?: string }[] = [
  {
    title: "Evidence, not alarms",
    body: "Every signal is an observation with its file, line or attestation field attached. Sightglass never labels a package safe or malicious. You decide, quickly.",
    example: "is in the wheel but not in the v2.5.0 git tag",
  },
  {
    title: "Checked against the source",
    body: "Each file in the wheel is compared with the git tag and the sdist, so code that was never in the repository stands out.",
    example: "matches tag · differs · missing from tag",
  },
  {
    title: "Provenance over time",
    body: "The release timeline shows who published each release and whether it was attested. A break in a long pattern is visible at a glance.",
    example: "14 attested releases, then one that isn’t",
  },
  {
    title: "Never runs package code",
    body: "No installs, no builds, no imports. Sightglass only reads archives and text, with safe unpacking and isolated workers, so the service itself isn’t a way in.",
  },
  {
    title: "Open and linkable",
    body: "Every comparison is a stable public URL that anyone can open without an account. Paste it into a review or cite it in an advisory. Apache-2.0, and self-hostable.",
    example: "/pypi/orbit-client/2.4.1...2.5.0",
  },
];

const STEPS: { title: string; body: string }[] = [
  {
    title: "Fetch",
    body: "Download both releases from the index and verify their hashes. Find the git tag from the project URLs. Read the PyPI attestations.",
  },
  {
    title: "Compare",
    body: "Pair every installed file across releases and against the tag and sdist. Look only at added lines, so code that was always there stays quiet.",
  },
  {
    title: "Show the evidence",
    body: "Rank the signals as high, check, note or clean, with a treemap of files, line diffs and a table of release facts. Each pair is analyzed once and cached for everyone.",
  },
];

const AUDIENCES: { who: string; what: string; when?: string }[] = [
  {
    who: "App maintainers",
    what: "One comment on your update pull request, one link, and only the packages that need a look.",
    when: "Coming",
  },
  {
    who: "Library maintainers",
    what: "Check your release came out as intended: attested, built by the right workflow, and matching the tag.",
  },
  {
    who: "Security researchers",
    what: "A linkable diff of a suspicious release, with the evidence laid out, ready to cite.",
  },
  {
    who: "Platform teams",
    what: "Run it for your organization, with a policy such as “hold any update without an attestation.”",
    when: "Later",
  },
];

// From docs/research/; update them when a new sample is run.
const STATS: { value: string; body: string; source: string; path: string }[] = [
  {
    value: "600",
    body: "Routine release pairs of popular packages analyzed to tune signal levels, including a held-out sample.",
    source: "docs/research/routine-*",
    path: "blob/main/docs/research/routine-sample.md",
  },
  {
    value: "94%",
    body: "Of popular packages’ latest stable releases matched to their git tag, so the source check has something to compare against.",
    source: "docs/research/tag-discovery.md",
    path: "blob/main/docs/research/tag-discovery.md",
  },
  {
    value: "44%",
    body: "Of the top 500 packages attest their latest release. That’s why Sightglass flags an attestation that disappears, not one that was never there.",
    source: "docs/research/pypi-publisher-data.md",
    path: "blob/main/docs/research/pypi-publisher-data.md",
  },
];

const PHASES: { state: string; title: string; items: string[]; now?: boolean }[] = [
  {
    state: "Now",
    title: "Release diff for PyPI",
    items: [
      "Release diff page: timeline, signals, treemap, diffs, source check",
      "Attestations from PyPI’s Integrity API",
    ],
    now: true,
  },
  {
    state: "Next",
    title: "Pull request review",
    items: [
      "GitHub App for pixi.lock and uv.lock",
      "One comment per update pull request",
      "Review page with the dependency path to each change",
    ],
  },
  {
    state: "Later",
    title: "More ecosystems and policy",
    items: ["conda-forge, then npm", "A policy file and a check run", "Self-hosted deployment"],
  },
];

function CompareForm() {
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
    <form id="compare" onSubmit={submit} aria-label="Compare releases" className="panel home-form">
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
  );
}

function SectionHead({
  id,
  eyebrow,
  title,
  children,
}: {
  id: string;
  eyebrow: string;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="block-h">
      <span className="eyebrow">{eyebrow}</span>
      <h2 id={id}>{title}</h2>
      {children}
    </div>
  );
}

/** Start page: what Sightglass is, and a form to pick a PyPI package and the releases to compare. */
export function HomePage() {
  return (
    <>
      <header className="wrap home-top">
        <a className="brand" href="/" aria-label="Sightglass home">
          <svg width="28" height="28" viewBox="0 0 30 30" aria-hidden="true">
            <rect x="0" y="10" width="30" height="10" className="brand-pipe" />
            <circle cx="15" cy="15" r="12" className="brand-glass" />
            <path d="M8 17 q3.5 -4 7 0 t7 0" className="brand-flow" />
          </svg>
          Sightglass
        </a>
        <nav aria-label="Sections">
          <a href="#why">Why</a>
          <a href="#how">How it works</a>
          <a href="#results">Results</a>
          <Link to="/reviews">Reviews</Link>
          <a href={REPO}>GitHub</a>
        </nav>
        <ThemeSwitch />
      </header>

      <main>
        <div className="wrap home">
          <span className="eyebrow">Open source · Apache-2.0 · PyPI first</span>
          <h1>
            See what you’re <em>merging.</em>
          </h1>
          <p className="lede">
            Dependency updates get approved on a version number.{" "}
            <strong>Sightglass shows what the release actually contains</strong>, compared with the previous release and
            with the git tag it claims to come from, before you merge.
          </p>
          <CompareForm />
          <p className="hint-text">
            Leave the releases empty to see the newest release compared with the one before it. Sightglass reads files
            and metadata only and never runs package code.
          </p>
        </div>

        <ReleaseExample />

        <div className="wrap">
          <section className="block" aria-labelledby="why">
            <SectionHead id="why" eyebrow="The gap" title="Nobody reads lockfile diffs.">
              <p>
                An update pull request shows a version bump and hundreds of changed lockfile lines. It gets approved
                because there’s nothing in it a reviewer can read. Compromised accounts and CI tokens have used exactly
                that gap: releases that looked like routine bumps, with the evidence sitting in the published files.
              </p>
            </SectionHead>
            <div className="contrast">
              <div className="pane">
                <div className="pane-h">What the reviewer sees · pixi.lock</div>
                <pre tabIndex={0} aria-label="An example pixi.lock diff">
                  {LOCKFILE_LINES.map((line, i) => (
                    <span key={i} className={line.tone ?? "dim"}>
                      {line.text}
                    </span>
                  ))}
                </pre>
                <div className="pane-f">
                  <strong>Looks routine.</strong> A new version and a new hash.
                </div>
              </div>
              <div className="pane">
                <div className="pane-h">What Sightglass shows · the published files</div>
                <div className="pane-sigs">
                  <SignalList signals={GAP_SIGNALS} />
                </div>
                <div className="pane-f">
                  <strong>Worth a look.</strong> Each line links to its evidence.
                </div>
              </div>
            </div>
          </section>

          <section className="block" aria-labelledby="pillars">
            <SectionHead id="pillars" eyebrow="What makes it different" title="Built for the moment you click merge." />
            <div className="pillars">
              {PILLARS.map((p) => (
                <div key={p.title} className="pillar">
                  <h3>{p.title}</h3>
                  <p>{p.body}</p>
                  {p.example && <div className="pillar-ex">{p.example}</div>}
                </div>
              ))}
            </div>
          </section>

          <section className="block" aria-labelledby="how">
            <SectionHead id="how" eyebrow="How it works" title="Fetch, compare, show the evidence." />
            <ol className="steps">
              {STEPS.map((s) => (
                <li key={s.title}>
                  <h3>{s.title}</h3>
                  <p>{s.body}</p>
                </li>
              ))}
            </ol>
            <p className="not-scanner">
              Sightglass isn’t a vulnerability scanner. It keeps no CVE database and works alongside OSV, Grype and
              GitHub’s dependency review. It shows what changed in the files, which is the part those tools don’t look
              at.
            </p>
          </section>

          <section className="block" aria-labelledby="who">
            <SectionHead id="who" eyebrow="Who it’s for" title="One view, four jobs." />
            <div className="who">
              {AUDIENCES.map((a) => (
                <div key={a.who} className="who-row">
                  <h3>{a.who}</h3>
                  <p>
                    {a.what}
                    {a.when && <span className="soon">{a.when}</span>}
                  </p>
                </div>
              ))}
            </div>
          </section>

          <section className="block" aria-labelledby="results">
            <SectionHead id="results" eyebrow="Measured, not assumed" title="Tuned against real releases.">
              <p>
                The rules are checked against samples of routine releases from popular PyPI packages, so ordinary
                updates stay quiet and the page is worth opening.
              </p>
            </SectionHead>
            <div className="proof">
              {STATS.map((s) => (
                <div key={s.value} className="stat">
                  <b>{s.value}</b>
                  <p>{s.body}</p>
                  <a className="stat-src" href={`${REPO}/${s.path}`}>
                    {s.source}
                  </a>
                </div>
              ))}
            </div>
          </section>

          <section className="block" aria-labelledby="status">
            <SectionHead id="status" eyebrow="Status" title="Where it is today." />
            <div className="roadmap">
              {PHASES.map((p) => (
                <div key={p.title} className={p.now ? "phase now" : "phase"}>
                  <span className="state">{p.state}</span>
                  <h3>{p.title}</h3>
                  <ul>
                    {p.items.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </section>

          <section className="final" aria-labelledby="final">
            <h2 id="final">Look before you merge.</h2>
            <p>Compare any two releases of a PyPI package. Nothing from the package is executed.</p>
            <div className="ctas">
              <a className="btn primary" href="#compare">
                Compare releases
              </a>
              <a className="btn" href={REPO}>
                View on GitHub
              </a>
              <a className="btn" href={`${REPO}/blob/main/docs/design.md`}>
                Read the design
              </a>
            </div>
          </section>
        </div>
      </main>

      <footer className="wrap home-foot">
        <span>Sightglass · Apache-2.0 · a project of aesir-oss</span>
        <span>A sight glass is the window in a pipe that shows what’s flowing through it.</span>
      </footer>
    </>
  );
}
