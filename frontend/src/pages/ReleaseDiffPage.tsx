import { useNavigate, useParams, useSearchParams } from "react-router";
import { ApiError, artifactFromSearch } from "../api/client";
import { usePairAnalysis, useReleaseHistory } from "../api/queries";
import { DiffViewer } from "../release/DiffViewer";
import { Files, sortFiles } from "../release/Files";
import { Header } from "../release/Header";
import { Failed, Progress } from "../release/Pending";
import { ReleaseFacts } from "../release/ReleaseFacts";
import { Signals } from "../release/Signals";
import { SourceCheck } from "../release/SourceCheck";
import { Timeline } from "../release/Timeline";
import { artifactLabel, pairPath } from "../release/urls";

/** The release diff page for `/:ecosystem/:package/:versions`. Its sections arrive with the page issues. */
export function ReleaseDiffPage() {
  const { ecosystem = "", package: pkg = "", versions = "" } = useParams();
  const [search, setSearch] = useSearchParams();
  const pair = usePairAnalysis(ecosystem, pkg, versions, artifactFromSearch(search));
  const history = useReleaseHistory(ecosystem, pkg);
  const data = pair.data;
  const navigate = useNavigate();
  // Without ?file=, show the first flagged or changed file.
  const selectedFile =
    search.get("file") ??
    (data?.status === "done" ? (sortFiles(data.files).find((f) => f.status !== "same")?.path ?? null) : null);

  function update(change: (params: URLSearchParams) => void) {
    const next = new URLSearchParams(search);
    change(next);
    setSearch(next);
  }

  function selectFile(path: string, base?: "source") {
    update((params) => {
      params.set("file", path);
      params.delete("line");
      if (base) params.set("base", base);
    });
  }

  return (
    <>
      {data ? (
        <Header
          ecosystem={ecosystem}
          pkg={data.package}
          from={data.from_version}
          to={data.to_version}
          versions={history.data?.releases.map((r) => r.version) ?? [data.from_version, data.to_version]}
          artifact={data.artifact}
          alternatives={data.alternatives}
        />
      ) : (
        <header className="top">
          <div className="wrap">
            <h1>
              {pkg} <span className="vs">{versions.replace("...", " → ")}</span>
            </h1>
          </div>
        </header>
      )}
      <div className="wrap stack">
        {data && history.data && (
          <Timeline
            pkg={data.package}
            releases={history.data.releases}
            from={data.from_version}
            to={data.to_version}
            onCompare={(from, to) => {
              // Wheel files differ between versions, so only an sdist choice carries over.
              const query = data.artifact.kind === "sdist" ? "?kind=sdist" : "";
              void navigate(pairPath(ecosystem, data.package, from, to, query));
            }}
          />
        )}
        {pair.isPending && (
          <p className="notice" role="status">
            Loading…
          </p>
        )}
        {pair.isError && (
          <p className="notice" data-tone="warn" role="alert">
            {pair.error instanceof ApiError && pair.error.status === 404
              ? pair.error.message
              : "Sightglass couldn't load this comparison. Try again shortly."}
          </p>
        )}
        {data?.downgrade && (
          <p className="notice" data-tone="warn" role="note">
            {data.to_version} is older than {data.from_version}. This compares moving back: the files and signals
            describe what changes when {data.from_version} is replaced by {data.to_version}.
          </p>
        )}
        {data?.status === "pending" && <Progress pending={data} />}
        {data?.status === "failed" && (
          <Failed
            ecosystem={ecosystem}
            pkg={data.package}
            versions={`${data.from_version}...${data.to_version}`}
            artifact={artifactFromSearch(search)}
            error={data.error}
          />
        )}
        {data?.status === "done" && <Signals signals={data.signals} source={data.source} />}
      </div>
      {data?.status === "done" && (
        <main className="wrap grid">
          <Files
            files={data.files}
            artifactLabel={artifactLabel(data.artifact).toLowerCase()}
            selected={selectedFile}
            onSelect={(path) => {
              selectFile(path);
            }}
          />
          <DiffViewer
            ecosystem={ecosystem}
            pkg={data.package}
            versions={`${data.from_version}...${data.to_version}`}
            artifact={artifactFromSearch(search)}
            file={selectedFile}
            line={Number(search.get("line")) || null}
            base={search.get("base") === "source" ? "source" : "previous"}
            inSource={data.source?.files.some((f) => f.path === selectedFile && f.source_path) ?? false}
            onBase={(base) => {
              update((params) => {
                if (base === "source") params.set("base", "source");
                else params.delete("base");
              });
            }}
          />
          <div className="full twocol">
            <SourceCheck
              source={data.source}
              sdist={data.sdist}
              onSelect={(path) => {
                selectFile(path, "source");
              }}
            />
            <ReleaseFacts facts={data.facts} />
          </div>
        </main>
      )}
      <footer className="wrap">
        Sightglass compares the files people install from the index with the previous release and with the
        project&apos;s source. It reads files and metadata only and never runs package code.
      </footer>
    </>
  );
}
