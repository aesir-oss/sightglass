"""Pair analysis: the files, signals, source check and release facts for two releases of a package.

``/api/{ecosystem}/{package}/{from}...{to}`` compares two releases; ``/api/{ecosystem}/{package}/{version}`` compares a
release with the one before it. A pair that hasn't been analyzed under the current rule set is queued, and the
response is ``202`` until the analysis is done.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from sightglass.api.deps import Enqueue, Index, get_enqueue, get_index, get_session
from sightglass.api.releases import Publisher
from sightglass.db import models
from sightglass.ecosystems.artifacts import ArtifactPair, select_artifacts
from sightglass.ecosystems.http import HttpError, NotFoundError
from sightglass.ecosystems.pypi import PypiProject, PypiRelease
from sightglass.log import get_logger
from sightglass.rules.ruleset import RULES
from sightglass.rules.store import requeue_failed
from sightglass.worker.pipeline import STEPS

log = get_logger(__name__)

POLL_SECONDS = 3
router = APIRouter()


class ArtifactRef(BaseModel):
    """One artifact pair the page can show."""

    kind: Literal["sdist", "wheel"]
    old_filename: str
    new_filename: str
    match: Literal["same_tag", "platform_changed"]


class SignalOut(BaseModel):
    """A signal with its evidence items."""

    rule_id: str
    level: Literal["high", "check", "note", "clean"]
    message: str
    evidence: list[dict[str, Any]]


class FileEntry(BaseModel):
    """One path across the two artifacts."""

    path: str
    status: Literal["added", "removed", "changed", "same"]
    text: bool
    compiled: bool
    old_size: int | None
    new_size: int | None
    old_sha256: str | None
    new_sha256: str | None
    flagged: bool


class SourceFile(BaseModel):
    """Where a package file was found in the source."""

    path: str
    status: Literal["matches", "differs", "missing"]
    source_path: str | None
    text: bool


class SourceCheck(BaseModel):
    """The source check: compared with a tag or commit, couldn't compare, or unknown."""

    state: Literal["compared", "could_not_compare", "unknown"]
    label: str | None = None
    repository: str | None = None
    commit: str | None = None
    ref: str | None = None
    origin: Literal["attestation", "tag"] | None = None
    reason: str | None = None
    detail: str | None = None
    root: str | None = None
    files: list[SourceFile] = []
    excluded: list[str] = []


class SdistCheck(BaseModel):
    """The wheel compared with the release's sdist."""

    root: str
    files: list[SourceFile]
    excluded: list[str]


class ReleaseFacts(BaseModel):
    """One side of the before-and-after table."""

    version: str
    published_at: datetime | None
    attestation: Literal["present", "absent", "unknown"]
    publisher: Publisher | None
    build_tool: str | None
    file_count: int
    total_size: int
    artifact_sha256: str
    requires_dist: list[str] | None


class Facts(BaseModel):
    """Release facts before and after."""

    old: ReleaseFacts
    new: ReleaseFacts


class PairAnalysis(BaseModel):
    """A finished (or failed) analysis of one artifact pair."""

    status: Literal["done", "failed"]
    ecosystem: Literal["pypi"]
    package: str
    from_version: str
    to_version: str
    ruleset_version: str
    artifact: ArtifactRef
    alternatives: list[ArtifactRef]
    error: str | None = None
    signals: list[SignalOut] = []
    files: list[FileEntry] = []
    source: SourceCheck | None = None
    sdist: SdistCheck | None = None
    facts: Facts | None = None


class PairPending(BaseModel):
    """The analysis is queued or running; poll again after ``Retry-After`` seconds."""

    status: Literal["pending"]
    ecosystem: Literal["pypi"]
    package: str
    from_version: str
    to_version: str
    artifact: ArtifactRef
    alternatives: list[ArtifactRef]
    step: Literal["downloading", "provenance", "diffing", "source", "rules"] | None = None
    steps: list[str] = list(STEPS)


def _ref(pair: ArtifactPair) -> ArtifactRef:
    return ArtifactRef(kind=pair.kind, old_filename=pair.old.filename, new_filename=pair.new.filename, match=pair.match)


def _resolve(project: PypiProject, versions: str) -> tuple[PypiRelease, PypiRelease]:
    by_version = {r.version: r for r in project.releases}
    if "..." in versions:
        old_v, _, new_v = versions.partition("...")
    else:
        new_v = versions
        order = [r.version for r in project.releases]
        if new_v in order and order.index(new_v) == 0:
            raise HTTPException(404, f"{new_v} is the first release of {project.name}; there is nothing before it")
        old_v = order[order.index(new_v) - 1] if new_v in order else ""
    for v in (old_v, new_v):
        if v not in by_version:
            raise HTTPException(404, f"{project.name} has no release {v or versions!r}")
    return by_version[old_v], by_version[new_v]


def _choose(
    old: PypiRelease, new: PypiRelease, kind: str | None, wheel: str | None
) -> tuple[ArtifactPair, list[ArtifactPair]]:
    selection = select_artifacts(old, new)
    alternatives = [p for p in (selection.sdist, *selection.wheels) if p is not None]
    if not alternatives:
        raise HTTPException(404, f"{old.version} and {new.version} have no artifact kind in common")
    if wheel is not None:
        chosen = next((p for p in selection.wheels if p.new.filename == wheel), None)
    elif kind == "sdist":
        chosen = selection.sdist
    elif kind == "wheel":
        chosen = selection.wheel
    else:
        chosen = selection.wheel or selection.sdist
    if chosen is None:
        raise HTTPException(404, f"no {wheel or kind} pair to compare between {old.version} and {new.version}")
    return chosen, alternatives


def locate(
    index: Index, ecosystem: str, package: str, versions: str, kind: str | None, wheel: str | None
) -> tuple[PypiProject, PypiRelease, PypiRelease, ArtifactPair, list[ArtifactPair]]:
    """Resolve a request to the project, both releases, the chosen artifact pair and its alternatives.

    Raises:
        HTTPException: 404 for unknown ecosystems, packages, versions or artifacts; 503 if the index is down.
    """
    if ecosystem != "pypi":
        raise HTTPException(404, f"unsupported ecosystem {ecosystem!r}")
    try:
        project = index.pypi.project(package)
    except NotFoundError as exc:
        raise HTTPException(404, f"{package} isn't on PyPI") from exc
    except HttpError as exc:
        log.warning("index_unavailable", package=package, error=str(exc))
        raise HTTPException(503, "PyPI is unavailable; try again shortly", headers={"Retry-After": "30"}) from exc
    old, new = _resolve(project, versions)
    pair, alternatives = _choose(old, new, kind, wheel)
    return project, old, new, pair, alternatives


def find_analysis(
    session: Session,
    project: PypiProject,
    pair: ArtifactPair,
    statuses: tuple[str, ...] = ("done", "failed"),
) -> models.Analysis | None:
    """The analysis of an artifact pair under the current rule set in one of ``statuses``, if there is one."""
    package = session.scalar(
        select(models.Package).where(models.Package.ecosystem == "pypi", models.Package.name == project.normalized_name)
    )
    if package is None:
        return None
    ids = {}
    for file in (pair.old, pair.new):
        ids[file.filename] = session.scalar(
            select(models.Artifact.id)
            .join(models.Release)
            .where(models.Release.package_id == package.id, models.Artifact.filename == file.filename)
        )
    if None in ids.values():
        return None
    return session.scalar(
        select(models.Analysis).where(
            models.Analysis.from_artifact_id == ids[pair.old.filename],
            models.Analysis.to_artifact_id == ids[pair.new.filename],
            models.Analysis.ruleset_version == RULES.version,
            models.Analysis.status.in_(statuses),
            # A done analysis from before reports existed is recomputed, like one that is missing.
            or_(models.Analysis.status != "done", models.Analysis.report.is_not(None)),
        )
    )


def _result(session: Session, row: models.Analysis, base: dict[str, Any]) -> PairAnalysis:
    if row.status == "failed":
        return PairAnalysis(status="failed", error=row.error, **base)
    signals = [
        SignalOut(rule_id=s.rule_id, level=s.level, message=s.message, evidence=s.evidence.get("items", []))  # type: ignore[arg-type]
        for s in session.scalars(
            select(models.Signal).where(models.Signal.analysis_id == row.id).order_by(models.Signal.id)
        )
    ]
    report = row.report or {}
    flagged = {e["file"] for s in signals for e in s.evidence if e.get("file")}
    files = [FileEntry(**f, flagged=f["path"] in flagged) for f in report.get("files", [])]
    return PairAnalysis(
        status="done",
        signals=signals,
        files=files,
        source=SourceCheck.model_validate(report["source"]) if "source" in report else None,
        sdist=SdistCheck.model_validate(report["sdist"]) if report.get("sdist") else None,
        facts=Facts.model_validate(report["facts"]) if "facts" in report else None,
        **base,
    )


@router.get(
    "/api/{ecosystem}/{package}/{versions}",
    operation_id="getPairAnalysis",
    responses={
        202: {"model": PairPending, "description": "Queued or running; poll again after Retry-After seconds"},
        404: {"description": "Unknown ecosystem, package, version or artifact"},
        503: {"description": "The index is unavailable"},
    },
)
def get_pair_analysis(
    ecosystem: Annotated[str, Path(description="Package ecosystem; only pypi for now")],
    package: Annotated[str, Path(description="Package name, in any spelling")],
    versions: Annotated[str, Path(description="`<from>...<to>`, or one version to compare with its predecessor")],
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    index: Annotated[Index, Depends(get_index)],
    enqueue: Annotated[Enqueue, Depends(get_enqueue)],
    kind: Annotated[Literal["wheel", "sdist"] | None, Query(description="Which artifact kind to show")] = None,
    wheel: Annotated[str | None, Query(description="The new release's wheel to compare, from `alternatives`")] = None,
) -> PairAnalysis | PairPending:
    """The analysis of one artifact pair of two releases; ``202`` while it is queued or running."""
    project, old, new, pair, alternatives = locate(index, ecosystem, package, versions, kind, wheel)
    base: dict[str, Any] = {
        "ecosystem": "pypi",
        "package": project.normalized_name,
        "from_version": old.version,
        "to_version": new.version,
        "artifact": _ref(pair),
        "alternatives": [_ref(p) for p in alternatives],
    }
    row = find_analysis(session, project, pair)
    if row is not None:
        response.headers["Cache-Control"] = "public, max-age=300"
        return _result(session, row, {**base, "ruleset_version": RULES.version})
    return _queue(session, project, old, new, pair, base, enqueue, response)


def _queue(
    session: Session,
    project: PypiProject,
    old: PypiRelease,
    new: PypiRelease,
    pair: ArtifactPair,
    base: dict[str, Any],
    enqueue: Enqueue,
    response: Response,
) -> PairPending:
    """Queue the pair (a no-op if it is queued already) and describe its progress."""
    default = select_artifacts(old, new).chosen
    enqueue("pypi", project.normalized_name, old.version, new.version, None if pair in default else pair.new.filename)
    running = find_analysis(session, project, pair, ("pending", "running"))
    response.status_code = 202
    response.headers["Retry-After"] = str(POLL_SECONDS)
    response.headers["Cache-Control"] = "no-store"
    return PairPending(status="pending", step=running.step if running else None, **base)  # type: ignore[arg-type]


@router.post(
    "/api/{ecosystem}/{package}/{versions}/retry",
    operation_id="retryPairAnalysis",
    status_code=202,
    responses={409: {"description": "The analysis hasn't failed, so there is nothing to retry"}},
)
def retry_pair_analysis(
    ecosystem: Annotated[str, Path(description="Package ecosystem; only pypi for now")],
    package: Annotated[str, Path(description="Package name, in any spelling")],
    versions: Annotated[str, Path(description="`<from>...<to>`, or one version")],
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    index: Annotated[Index, Depends(get_index)],
    enqueue: Annotated[Enqueue, Depends(get_enqueue)],
    kind: Annotated[Literal["wheel", "sdist"] | None, Query(description="Which artifact kind")] = None,
    wheel: Annotated[str | None, Query(description="The new release's wheel, from `alternatives`")] = None,
) -> PairPending:
    """Analyze a pair again after it failed."""
    project, old, new, pair, alternatives = locate(index, ecosystem, package, versions, kind, wheel)
    row = find_analysis(session, project, pair, ("failed",))
    if row is None:
        raise HTTPException(409, "this pair's analysis hasn't failed, so there is nothing to retry")
    requeue_failed(session, row.id)
    base: dict[str, Any] = {
        "ecosystem": "pypi",
        "package": project.normalized_name,
        "from_version": old.version,
        "to_version": new.version,
        "artifact": _ref(pair),
        "alternatives": [_ref(p) for p in alternatives],
    }
    return _queue(session, project, old, new, pair, base, enqueue, response)
