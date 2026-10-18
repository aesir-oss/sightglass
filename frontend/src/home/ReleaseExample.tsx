import "./home.css";

// Invented data, matching docs/mockups/release-diff.html. Never a real package.
const RELEASE_COUNT = 15;

export type Level = "high" | "check" | "note" | "clean";

export interface ExampleSignal {
  level: Level;
  text: string;
}

const SIGNALS: ExampleSignal[] = [
  { level: "high", text: "No provenance attestation. 2.4.1 had one." },
  { level: "high", text: "Not from the trusted publisher that attested the previous 14 releases." },
  { level: "high", text: "orbit_client/_telemetry.py is in the wheel but not in the v2.5.0 git tag." },
  { level: "high", text: "orbit_client/__init__.py now runs code when the package is imported." },
  { level: "check", text: "Published in the last 7 days." },
];

const DIFF: { text: string; added?: boolean }[] = [
  { text: "from ._version import __version__" },
  { text: "from .errors import HTTPError, OrbitError" },
  { text: "from .retry import RetryPolicy" },
  { text: "from .session import Session" },
  { text: "+from . import _telemetry", added: true },
  { text: "+", added: true },
  { text: "+_telemetry.start()", added: true },
  { text: " " },
  { text: '__all__ = ["HTTPError", "OrbitError", ...]' },
];

const FACTS: { fact: string; before: string; after: string; changed: boolean }[] = [
  { fact: "Published by", before: "Trusted publisher: release.yml", after: "Not attested", changed: true },
  { fact: "Matches tag", before: "Every package file", after: "1 file not in tag", changed: true },
  { fact: "Since last release", before: "6 weeks", after: "5 months", changed: false },
];

const LEVEL_LABEL: Record<Level, string> = { high: "High", check: "Check", note: "Note", clean: "Clean" };

/** A list of signals with level badges, as the release diff page ranks them. */
export function SignalList({ signals }: { signals: ExampleSignal[] }) {
  return (
    <ul className="ex-sigs">
      {signals.map((s) => (
        <li key={s.text}>
          <span className={`ex-lvl ${s.level}`}>{LEVEL_LABEL[s.level]}</span>
          <span>{s.text}</span>
        </li>
      ))}
    </ul>
  );
}

function Timeline() {
  const x0 = 10;
  const x1 = 410;
  return (
    <svg
      viewBox="0 0 420 54"
      role="img"
      aria-label="Fourteen releases from the trusted publisher with attestations, then 2.5.0 without either"
    >
      <line className="ex-axis" x1={x0} y1={24} x2={x1} y2={24} />
      {Array.from({ length: RELEASE_COUNT }, (_, i) => {
        const last = i === RELEASE_COUNT - 1;
        const x = x0 + ((x1 - x0) * i) / (RELEASE_COUNT - 1);
        return <circle key={i} className={last ? "ex-dot broken" : "ex-dot"} cx={x} cy={24} r={last ? 7 : 5} />;
      })}
      <text x={x0} y={50}>
        1.12.0
      </text>
      <text x={x1} y={50} textAnchor="end" className="bad">
        2.5.0 · no attestation
      </text>
    </svg>
  );
}

/** The hero's example: a release diff for an invented package, seen through a sight glass in a pipe. */
export function ReleaseExample() {
  return (
    <figure className="pipe-band" aria-labelledby="example-caption">
      <div className="wrap">
        <div className="flange">
          <span className="bolt a" />
          <span className="bolt b" />
          <span className="bolt c" />
          <span className="bolt d" />
          <div className="window">
            <div className="win-bar">
              <span className="win-url">
                /pypi/<b>orbit-client</b>/2.4.1...2.5.0
              </span>
              <span className="example-tag">Invented example</span>
            </div>
            <div className="win-body">
              <div className="win-col">
                <div className="win-h">
                  <span className="win-pkg">orbit-client</span>
                  <span className="win-vs">2.4.1 → 2.5.0</span>
                </div>
                <div className="ex-block">
                  <span className="eyebrow">Release history</span>
                  <div className="ex-tl">
                    <Timeline />
                  </div>
                  <div className="ex-key">
                    <span>
                      <i />
                      Trusted publisher, attested
                    </span>
                    <span>
                      <i className="o" />
                      Neither
                    </span>
                  </div>
                </div>
                <div className="ex-block">
                  <span className="eyebrow">Signals</span>
                  <SignalList signals={SIGNALS} />
                </div>
              </div>
              <div className="win-col">
                <div className="ex-diff">
                  <div className="ex-diff-h">
                    <span>orbit_client/__init__.py</span>
                    <span>vs. 2.4.1</span>
                  </div>
                  <pre tabIndex={0} aria-label="Diff of orbit_client/__init__.py">
                    {DIFF.map((line, i) => (
                      <span key={i} className={line.added ? "add" : undefined}>
                        {line.text}
                      </span>
                    ))}
                  </pre>
                </div>
                <div className="ex-facts">
                  <table>
                    <thead>
                      <tr>
                        <th scope="col">Fact</th>
                        <th scope="col">2.4.1</th>
                        <th scope="col">2.5.0</th>
                      </tr>
                    </thead>
                    <tbody>
                      {FACTS.map((f) => (
                        <tr key={f.fact}>
                          <th scope="row">{f.fact}</th>
                          <td>{f.before}</td>
                          <td className={f.changed ? "changed" : undefined}>{f.after}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>
        </div>
        <figcaption id="example-caption" className="ex-caption">
          An example release diff. The package, its releases and its code are invented. Every signal comes with the
          evidence behind it: the file, the line, the attestation field.
        </figcaption>
      </div>
    </figure>
  );
}
