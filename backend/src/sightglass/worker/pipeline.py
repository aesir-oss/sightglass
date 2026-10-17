"""The analysis pipeline for one release pair: resolve, fetch, unpack, provenance, source, diff, rules, store.

Every step is cached by content: artifacts by their sha256, source archives by commit, file contents in the blob
store, and a pair's result under the rule-set version, so a pair is analyzed once per version. Nothing from a package
is imported or run.

Errors split in two. :class:`TransientError` (an index or host that is down) should be retried later. Anything else
about a pair (a hash mismatch, an archive the unpacker refuses) is recorded on its ``analysis`` row as a failure with
a reason, and the other pairs still run.
"""

import os
import re
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from sightglass import _core
from sightglass.db import models
from sightglass.ecosystems.artifacts import ArtifactPair, preferred_sdist, select_artifacts
from sightglass.ecosystems.github import GITHUB_HOSTS, GitHubClient, Repository
from sightglass.ecosystems.http import Fetcher, HttpError, NotFoundError, UnavailableError, default_client
from sightglass.ecosystems.provenance import IntegrityClient, Provenance, record_provenance
from sightglass.ecosystems.pypi import PYPI_HOSTS, IndexDataError, PypiClient, PypiFile, PypiProject, PypiRelease
from sightglass.ecosystems.sources import (
    CouldNotCompare,
    SourceSnapshot,
    fetch_source,
    find_repository,
    record_source_snapshot,
    repository_from_attestation,
)
from sightglass.log import get_logger
from sightglass.rules import patterns, scope
from sightglass.rules import provenance as provenance_rules
from sightglass.rules.base import PairAnalysis, ReleaseFacts, RuleSet
from sightglass.rules.pairing import (
    FilePair,
    IndexedFile,
    SourceComparison,
    check_source,
    normalize_path,
    pair_files,
    submodule_paths,
)
from sightglass.rules.ruleset import RULES
from sightglass.rules.scope import NOT_SHIPPED
from sightglass.rules.store import current_analysis, fail_analysis, mark_step, save_analysis
from sightglass.storage.blobs import BlobStore, LocalBlobStore
from sightglass.worker.catalog import record_artifact, record_files, record_package, record_release
from sightglass.worker.report import build_report

log = get_logger(__name__)

CACHE_DIR_ENV = "SIGHTGLASS_CACHE_DIR"
# The steps a pair goes through, in order; the current one is stored on its analysis row while it runs.
STEPS = ("downloading", "provenance", "diffing", "source", "rules")
# Text larger than this isn't decoded for the rules; it is still compared by hash.
MAX_TEXT = _core.DiffLimits().max_size
_METADATA_RE = re.compile(r"^(pyproject\.toml|setup\.cfg|PKG-INFO|\*\.dist-info/[^/]+)$")


def default_cache_dir() -> Path:
    """``SIGHTGLASS_CACHE_DIR``, or ``~/.cache/sightglass``: downloads, source archives and the blob store."""
    return Path(os.environ.get(CACHE_DIR_ENV) or Path.home() / ".cache" / "sightglass")


class TransientError(Exception):
    """A step failed in a way that retrying later may fix."""


class PipelineError(Exception):
    """The release pair can't be analyzed at all, for example because a version doesn't exist."""

    def __init__(self, reason: str, detail: str) -> None:
        """Record a short reason code and a human-readable detail."""
        super().__init__(f"{reason}: {detail}")
        self.reason = reason


@dataclass
class Services:
    """Clients and stores the pipeline uses."""

    pypi: PypiClient
    integrity: IntegrityClient
    github: GitHubClient
    blobs: BlobStore
    cache_dir: Path
    limits: _core.Limits | None = None

    @classmethod
    def default(cls, cache_dir: Path) -> Services:
        """Clients for pypi.org and GitHub, and a local blob store, with downloads cached under ``cache_dir``."""
        return cls(
            pypi=PypiClient.default(),
            integrity=IntegrityClient(Fetcher(default_client(), PYPI_HOSTS)),
            github=GitHubClient(Fetcher(default_client(), GITHUB_HOSTS)),
            blobs=LocalBlobStore(cache_dir / "blobs"),
            cache_dir=cache_dir,
        )


@dataclass(frozen=True)
class PairResult:
    """The outcome for one artifact pair."""

    analysis_id: int
    kind: str
    old_filename: str
    new_filename: str
    status: Literal["done", "failed"]
    cached: bool
    error: str | None = None
    signals: tuple[dict[str, Any], ...] = ()


@dataclass
class _Unpacked:
    root: Path
    prefix: str
    entries: list[_core.ArchiveEntry]
    files: list[IndexedFile] = field(default_factory=list)
    # Paths as pair_files normalizes them, mapped to the path relative to `prefix`.
    by_pair_path: dict[str, str] = field(default_factory=dict)

    def read(self, path: str) -> bytes | None:
        relative = self.by_pair_path.get(path, path)
        target = self.root / (self.prefix + relative)
        return target.read_bytes() if target.is_file() else None


def _capabilities(unpacked: _Unpacked, kind: str) -> frozenset[str]:
    """The pattern rules whose calls an artifact's Python already makes, outside tests and docs for an sdist."""

    def sources() -> Iterator[tuple[str, bytes]]:
        for f in unpacked.files:
            top = f.path.split("/", 1)[0]
            if not f.path.endswith((".py", ".pyw")) or (
                kind == "sdist" and "/" in f.path and top.lower() in NOT_SHIPPED
            ):
                continue
            if (data := unpacked.read(normalize_path(f.path))) is not None:
                yield f.path, data

    return patterns.capabilities(sources())


def _unpack(archive: Path, dest: Path, limits: _core.Limits | None, *, strip: bool) -> _Unpacked:
    entries = _core.extract_archive(archive, dest, limits)
    tops = {e.path.split("/", 1)[0] for e in entries}
    prefix = tops.pop() + "/" if strip and len(tops) == 1 and all("/" in e.path for e in entries) else ""
    files = [IndexedFile.from_entry(e, prefix) for e in entries]
    return _Unpacked(dest, prefix, entries, files, {normalize_path(f.path): f.path for f in files})


def _decode(data: bytes | None) -> str | None:
    if data is None or len(data) > MAX_TEXT:
        return None
    return data.decode("utf-8", "replace")


class _Run:
    """State shared by the pairs of one release pair."""

    def __init__(
        self,
        session: Session,
        services: Services,
        project: PypiProject,
        old: PypiRelease,
        new: PypiRelease,
        work: Path,
        rules: RuleSet,
        now: datetime,
        final_attempt: bool,
    ) -> None:
        self.session, self.services, self.project, self.old, self.new = session, services, project, old, new
        self.work, self.rules, self.now, self.final_attempt = work, rules, now, final_attempt
        self.package_id = record_package(session, project)
        self.release_ids = {r.version: record_release(session, self.package_id, r) for r in (old, new)}
        self._unpacked: dict[str, _Unpacked] = {}
        self._provenance: dict[str, Provenance | None] = {}
        self._sources: dict[str, _Unpacked] = {}
        self._capabilities: dict[str, frozenset[str]] = {}

    def artifact_id(self, release: PypiRelease, file: PypiFile) -> int:
        return record_artifact(self.session, self.release_ids[release.version], file)

    def unpacked(self, file: PypiFile) -> _Unpacked:
        """Download (or reuse) and extract an artifact, once per run."""
        if file.sha256 not in self._unpacked:
            cache = self.services.cache_dir / "artifacts" / file.sha256
            path = cache / file.filename
            if not path.is_file():
                cache.mkdir(parents=True, exist_ok=True)
                path = self.services.pypi.download(file, cache)
            dest = self.work / file.sha256
            self._unpacked[file.sha256] = _unpack(path, dest, self.services.limits, strip=file.kind == "sdist")
        return self._unpacked[file.sha256]

    def unpacked_source(self, snapshot: SourceSnapshot) -> _Unpacked:
        """Extract a source archive, once per run."""
        if snapshot.commit not in self._sources:
            assert snapshot.archive is not None
            dest = self.work / f"source-{snapshot.commit}"
            self._sources[snapshot.commit] = _unpack(snapshot.archive, dest, self.services.limits, strip=True)
        return self._sources[snapshot.commit]

    def provenance(self, release: PypiRelease, file: PypiFile) -> Provenance | None:
        """The file's provenance, or None when the index's answer couldn't be read."""
        if file.filename not in self._provenance:
            try:
                value: Provenance | None = self.services.integrity.provenance(
                    self.project.name, release.version, file.filename
                )
            except UnavailableError:
                raise
            except HttpError as exc:
                log.warning("provenance_unreadable", filename=file.filename, error=str(exc))
                value = None
            self._provenance[file.filename] = value
        return self._provenance[file.filename]

    def history(self, kind: str) -> tuple[ReleaseFacts, ...]:
        """Releases before ``old``, with provenance for the most recent ones of the same artifact kind."""
        versions = [r.version for r in self.project.releases]
        earlier = self.project.releases[: versions.index(self.old.version)]
        facts = []
        recent = {r.version for r in earlier[-provenance_rules.RECENT :]}
        for release in earlier:
            prov = None
            if release.version in recent:
                chosen = select_artifacts(release, self.old)
                pair = chosen.sdist if kind == "sdist" else chosen.wheel
                prov = self.provenance(release, pair.old) if pair else None
            facts.append(ReleaseFacts(release.version, release.published_at, prov))
        return tuple(facts)

    def sources(self, prov: Provenance | None, release: PypiRelease) -> Iterator[SourceSnapshot | CouldNotCompare]:
        """A release's source from the attestation's repository, then from the one the project lists, if different."""
        att = prov.attestations[0] if prov and prov.attestations else None
        attested = repository_from_attestation(att.claims.source_repository if att else None)
        declared = find_repository(self.project.project_urls, self.project.home_page)
        candidates: list[Repository | None] = [attested] if attested else []
        if declared is not None and (attested is None or declared.slug.lower() != attested.slug.lower()):
            candidates.append(declared)
        if not candidates:
            candidates = [None]
        preferred = self.session.scalar(
            select(models.SourceSnapshot.tag_pattern)
            .where(models.SourceSnapshot.package_id == self.package_id, models.SourceSnapshot.origin == "tag")
            .order_by(models.SourceSnapshot.fetched_at.desc())
            .limit(1)
        )
        work_dir = self.services.cache_dir / "sources"
        work_dir.mkdir(parents=True, exist_ok=True)
        for repository in candidates:
            from_attestation = att is not None and repository is attested
            result = fetch_source(
                self.services.github,
                project=self.project.name,
                version=release.version,
                repository=repository,
                attested_commit=att.claims.source_commit if att and from_attestation else None,
                attested_ref=att.claims.source_ref if att and from_attestation else None,
                preferred_pattern=preferred,
                work_dir=work_dir,
                limits=self.services.limits,
            )
            if (
                isinstance(result, CouldNotCompare)
                and result.reason == "repository_unreachable"
                and not self.final_attempt
            ):
                raise TransientError(result.detail)
            yield result

    def capabilities(self, file: PypiFile, kind: str) -> frozenset[str]:
        """What the artifact's code already does, once per run."""
        if file.sha256 not in self._capabilities:
            self._capabilities[file.sha256] = _capabilities(self.unpacked(file), kind)
        return self._capabilities[file.sha256]


def _texts(
    pairs: list[FilePair], old: _Unpacked, new: _Unpacked
) -> tuple[dict[str, _core.FileDiff], dict[str, str], dict[str, str]]:
    diffs: dict[str, _core.FileDiff] = {}
    old_text: dict[str, str] = {}
    new_text: dict[str, str] = {}
    for p in pairs:
        metadata = bool(_METADATA_RE.match(p.path))
        changed = p.status in ("added", "changed") and p.text
        if not (changed or metadata):
            continue
        before = old.read(p.path) if p.old is not None else None
        after = new.read(p.path) if p.new is not None else None
        if changed and after is not None:
            diffs[p.path] = _core.diff_lines(before or b"", after)
        if (text := _decode(after)) is not None:
            new_text[p.path] = text
        if p.status != "added" and (text := _decode(before)) is not None:
            old_text[p.path] = text
    return diffs, old_text, new_text


def _source_check(
    run: _Run, snapshot_id: int, snapshot: SourceSnapshot, package: _Unpacked
) -> tuple[SourceComparison, dict[str, _core.FileDiff], str]:
    source = run.unpacked_source(snapshot)
    record_files(run.session, run.services.blobs, source.root, source.entries, source_snapshot_id=snapshot_id)
    gitmodules = _decode(source.read(".gitmodules"))
    comparison = check_source(package.files, source.files, submodule_paths(gitmodules) if gitmodules else ())
    diffs = {}
    checks = []
    for check in comparison.files:
        if check.status == "differs" and check.text and check.source_path is not None:
            pkg, src = package.read(normalize_path(check.path)), source.read(check.source_path)
            if pkg is not None and src is not None:
                diffs[check.path] = _core.diff_lines(src, pkg)
                pkg_text, src_text = _decode(pkg), _decode(src)
                if (
                    (check.path.endswith((".py", ".pyw")) or normalize_path(check.path).startswith("*.data/scripts/"))
                    and pkg_text is not None
                    and src_text is not None
                    and scope.same_code(pkg_text, src_text, check.path)
                ):
                    check = replace(check, explained="the same code apart from comments, formatting or the version")
        checks.append(check)
    comparison = replace(comparison, files=tuple(checks))
    if snapshot.origin == "tag" and snapshot.ref:
        label = f"tag {snapshot.ref.removeprefix('refs/tags/')}"
    else:
        label = f"commit {snapshot.commit[:12]}"
    return comparison, diffs, label


# A source tree holding fewer of the package's files than this is taken to be the wrong repository, such as one that
# only builds releases and pulls the code in as a git submodule, which GitHub's archives leave out.
MIN_SOURCE_COVERAGE = 0.5


def _coverage(comparison: SourceComparison) -> float:
    return sum(c.status != "missing" for c in comparison.files) / len(comparison.files) if comparison.files else 1.0


def _find_source(
    run: _Run, prov: Provenance | None, package: _Unpacked, release: PypiRelease
) -> tuple[SourceComparison | CouldNotCompare, dict[str, _core.FileDiff], str | None, SourceSnapshot | None]:
    """Compare an artifact with the first candidate source that holds most of it, else the one that holds most."""
    best: tuple[SourceComparison, dict[str, _core.FileDiff], str, SourceSnapshot] | None = None
    first_failure: CouldNotCompare | None = None
    for found in run.sources(prov, release):
        if isinstance(found, CouldNotCompare):
            first_failure = first_failure or found
            continue
        snapshot_id = record_source_snapshot(run.session, run.package_id, found)
        comparison, diffs, label = _source_check(run, snapshot_id, found, package)
        if _coverage(comparison) >= MIN_SOURCE_COVERAGE:
            return comparison, diffs, label, found
        log.info("source_mostly_missing", repository=found.repository.slug, coverage=round(_coverage(comparison), 3))
        if best is None or _coverage(comparison) > _coverage(best[0]):
            best = (comparison, diffs, label, found)
    if best is not None:
        return best
    assert first_failure is not None  # sources() yields at least one result
    return first_failure, {}, None, None


def _mismatched(comparison: SourceComparison | CouldNotCompare | None) -> bool:
    """Whether any text file is missing from or differs from the source, without an explanation from the build."""
    return isinstance(comparison, SourceComparison) and any(
        c.status != "matches" and c.text and c.explained is None for c in comparison.files
    )


def _sdist_check(
    run: _Run, release: PypiRelease, wheel: _Unpacked
) -> tuple[SourceComparison | None, frozenset[str] | None]:
    """A wheel compared with its release's sdist, and the sdist's paths; None when there's no readable sdist."""
    sdist_file = preferred_sdist(release)
    if sdist_file is None:
        return None, None
    try:
        sdist = run.unpacked(sdist_file)
    except UnavailableError:
        raise
    except (HttpError, _core.ArchiveError, OSError) as exc:
        # The wheel is still analyzed; only its comparison with the sdist is unknown.
        log.warning("sdist_unavailable", filename=sdist_file.filename, error=f"{type(exc).__name__}: {exc}")
        return None, None
    return check_source(wheel.files, sdist.files), frozenset(f.path for f in sdist.files)


def _signals(session: Session, analysis_id: int) -> tuple[dict[str, Any], ...]:
    rows = session.scalars(
        select(models.Signal).where(models.Signal.analysis_id == analysis_id).order_by(models.Signal.id)
    )
    return tuple({"rule_id": r.rule_id, "level": r.level, "message": r.message, "evidence": r.evidence} for r in rows)


def _analyze(run: _Run, pair: ArtifactPair) -> PairResult:
    session = run.session
    old_id, new_id = run.artifact_id(run.old, pair.old), run.artifact_id(run.new, pair.new)
    names = {"kind": pair.kind, "old_filename": pair.old.filename, "new_filename": pair.new.filename}

    def result(
        analysis_id: int, status: Literal["done", "failed"], cached: bool, error: str | None = None
    ) -> PairResult:
        signals = _signals(session, analysis_id) if status == "done" else ()
        return PairResult(analysis_id, pair.kind, pair.old.filename, pair.new.filename, status, cached, error, signals)

    version = run.rules.version
    session.commit()
    if (existing := current_analysis(session, old_id, new_id, version)) is not None:
        return result(existing.id, "done", cached=True)

    def step(name: str) -> None:
        mark_step(session, old_id, new_id, version, name)

    try:
        step("downloading")
        old, new = run.unpacked(pair.old), run.unpacked(pair.new)
        record_files(session, run.services.blobs, old.root, old.entries, artifact_id=old_id)
        record_files(session, run.services.blobs, new.root, new.entries, artifact_id=new_id)
        step("provenance")
        old_prov, new_prov = run.provenance(run.old, pair.old), run.provenance(run.new, pair.new)
        for artifact_id, prov in ((old_id, old_prov), (new_id, new_prov)):
            if prov is not None:
                record_provenance(session, artifact_id, prov)

        step("diffing")
        files = pair_files(old.files, new.files)
        diffs, old_text, new_text = _texts(files, old, new)

        step("source")
        source, source_diffs, label, snapshot = _find_source(run, new_prov, new, run.new)
        # The previous release against its own source, so a mismatch it already had reads as a kept pattern.
        old_source: SourceComparison | None = None
        if _mismatched(source):
            found_old = _find_source(run, old_prov, old, run.old)[0]
            old_source = found_old if isinstance(found_old, SourceComparison) else None

        sdist_check: SourceComparison | None = None
        old_sdist_check: SourceComparison | None = None
        sdist_files: frozenset[str] | None = frozenset(f.path for f in new.files)
        if pair.kind == "wheel":
            sdist_check, sdist_files = _sdist_check(run, run.new, new)
            if _mismatched(sdist_check):
                old_sdist_check = _sdist_check(run, run.old, old)[0]

        analysis = PairAnalysis(
            "pypi",
            run.project.normalized_name,
            ReleaseFacts(run.old.version, run.old.published_at, old_prov),
            ReleaseFacts(run.new.version, run.new.published_at, new_prov),
            files=tuple(files),
            diffs=diffs,
            new_text=new_text,
            old_text=old_text,
            source=source,
            source_label=label,
            source_diffs=source_diffs,
            sdist=sdist_check,
            old_source=old_source,
            old_sdist=old_sdist_check,
            sdist_files=sdist_files,
            history=run.history(pair.kind),
            analyzed_at=run.now,
            kind=pair.kind,
            old_capabilities=run.capabilities(pair.old, pair.kind),
        )
        step("rules")
        signals = run.rules.run(analysis)
        report = build_report(
            analysis,
            old_file=pair.old,
            new_file=pair.new,
            old_files=old.files,
            new_files=new.files,
            snapshot=snapshot,
        )
    except UnavailableError, TransientError:
        session.rollback()
        raise
    except (HttpError, IndexDataError, _core.ArchiveError, OSError) as exc:
        session.rollback()
        reason = f"{type(exc).__name__}: {exc}"
        log.warning("pair_failed", reason=reason, **names)
        analysis_id = fail_analysis(session, old_id, new_id, version, reason)
        session.commit()
        return result(analysis_id, "failed", cached=False, error=reason)
    analysis_id = save_analysis(session, old_id, new_id, version, signals, report)
    session.commit()
    log.info("pair_analyzed", signals=len(signals), **names)
    return result(analysis_id, "done", cached=False)


def analyze_release_pair(
    session: Session,
    services: Services,
    package: str,
    from_version: str,
    to_version: str,
    *,
    rules: RuleSet = RULES,
    now: datetime | None = None,
    final_attempt: bool = True,
    wheel: str | None = None,
) -> list[PairResult]:
    """Analyze the chosen artifact pairs of two releases of a PyPI package.

    Args:
        session: Database session; the pipeline commits after each pair.
        services: Clients and stores.
        package: The project name, in any spelling.
        from_version: The earlier release.
        to_version: The later release.
        rules: The rule set to run.
        now: When the analysis runs, for timing rules; defaults to the current time.
        wheel: Analyze only the wheel pair whose new file is named this, instead of the default pairs; for the
            artifact picker.
        final_attempt: Whether this is the job's last try. Before it, an unreachable source repository raises
            :class:`TransientError` so the job is retried, instead of storing "couldn't compare".

    Returns:
        One result per artifact pair: the sdists and the default wheel pair, when the releases have them.

    Raises:
        PipelineError: If the package or a version doesn't exist, or there is nothing to compare.
        TransientError: If a step failed in a way that retrying may fix.
    """
    try:
        project = services.pypi.project(package)
    except NotFoundError as exc:
        raise PipelineError("package_not_found", str(exc)) from exc
    except UnavailableError as exc:
        raise TransientError(str(exc)) from exc
    releases = {r.version: r for r in project.releases}
    for version in (from_version, to_version):
        if version not in releases:
            raise PipelineError("release_not_found", f"{project.name} has no release {version}")
    old, new = releases[from_version], releases[to_version]
    selection = select_artifacts(old, new)
    if not selection.chosen:
        raise PipelineError("nothing_to_compare", f"{from_version} and {to_version} share no artifact kind")
    pairs = selection.chosen
    if wheel is not None:
        pairs = tuple(p for p in selection.wheels if p.new.filename == wheel)
        if not pairs:
            raise PipelineError("artifact_not_found", f"{to_version} has no wheel {wheel} to compare")
    with tempfile.TemporaryDirectory(prefix="sg-analysis-") as tmp:
        run = _Run(session, services, project, old, new, Path(tmp), rules, now or datetime.now(UTC), final_attempt)
        session.commit()
        return [_analyze(run, pair) for pair in pairs]
