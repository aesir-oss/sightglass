"""The review API: a pull request's lockfile changes, the ones that need a look first."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from sightglass.api.deps import get_session
from sightglass.db import models
from sightglass.rules.base import LEVELS
from sightglass.rules.ruleset import RULES

router = APIRouter()

AnalysisState = Literal["done", "pending", "failed", "not_analyzed"]
SignalLevel = Literal["high", "check", "note", "clean"]


class ChangeAnalysis(BaseModel):
    """Where a change's analysis is, and what it found."""

    state: AnalysisState
    # The most severe signal level across the package's analyzed artifacts, when done.
    level: SignalLevel | None
    # Signals by level, across the analyzed artifacts.
    counts: dict[str, int]


class ReviewChangeOut(BaseModel):
    """One package a lockfile change adds, removes or moves."""

    ecosystem: Literal["conda", "pypi"]
    package: str
    kind: Literal["added", "removed", "changed"]
    from_version: str | None
    to_version: str | None
    # The release the new version is compared with: from_version, or an added package's predecessor.
    compare_from: str | None
    environments: list[str]
    platforms: list[str]
    only_some_platforms: bool
    # Package names from a direct dependency of the project to this package.
    path: list[str]
    analysis: ChangeAnalysis


class Review(BaseModel):
    """The latest review of a pull request's lockfile, changes that need a look first."""

    repository: str
    number: int
    base_sha: str
    head_sha: str
    lockfile_path: str
    created_at: datetime
    # Every platform any change appears on, sorted.
    platforms: list[str]
    changes: list[ReviewChangeOut]


def _analysis(session: Session, change: models.ReviewChange) -> ChangeAnalysis:
    """The state of the analyses of ``compare_from`` to ``to_version``, from the database alone."""
    if change.ecosystem != "pypi" or change.compare_from is None or change.to_version is None:
        return ChangeAnalysis(state="not_analyzed", level=None, counts={})
    old_release, new_release = aliased(models.Release), aliased(models.Release)
    old_artifact, new_artifact = aliased(models.Artifact), aliased(models.Artifact)
    rows = session.execute(
        select(models.Analysis.id, models.Analysis.status)
        .join(old_artifact, models.Analysis.from_artifact_id == old_artifact.id)
        .join(old_release, old_artifact.release_id == old_release.id)
        .join(new_artifact, models.Analysis.to_artifact_id == new_artifact.id)
        .join(new_release, new_artifact.release_id == new_release.id)
        .join(models.Package, new_release.package_id == models.Package.id)
        .where(
            models.Package.ecosystem == "pypi",
            models.Package.name == change.package,
            old_release.version == change.compare_from,
            new_release.version == change.to_version,
            models.Analysis.ruleset_version == RULES.version,
        )
    ).all()
    done = [analysis_id for analysis_id, status in rows if status == "done"]
    if not done:
        state: AnalysisState = "failed" if rows and all(s == "failed" for _, s in rows) else "pending"
        return ChangeAnalysis(state=state, level=None, counts={})
    levels = list(session.scalars(select(models.Signal.level).where(models.Signal.analysis_id.in_(done))))
    counts: dict[str, int] = {level: levels.count(level) for level in LEVELS if level in levels}
    level: SignalLevel = next((lvl for lvl in LEVELS if lvl in counts), "clean")
    return ChangeAnalysis(state="done", level=level, counts=counts)


# Queue order: what needs a look first, then what's still analyzing, then the rest.
_RANK = {"high": 0, "check": 1, "pending": 2, "failed": 3, "note": 4, "clean": 4, "not_analyzed": 5}
_KIND = {"added": 0, "changed": 1, "removed": 2}


def _rank(change: ReviewChangeOut) -> tuple[int, int, str]:
    key = change.analysis.level if change.analysis.state == "done" and change.analysis.level else change.analysis.state
    return (_RANK[key], _KIND[change.kind], change.package)


@router.get(
    "/api/reviews/{owner}/{repo}/{number}",
    operation_id="getReview",
    responses={404: {"description": "No review of this pull request"}},
)
def get_review(
    owner: Annotated[str, Path(description="Repository owner")],
    repo: Annotated[str, Path(description="Repository name")],
    number: Annotated[int, Path(description="Pull request number", ge=1)],
    response: Response,
    session: Annotated[Session, Depends(get_session)],
) -> Review:
    """The latest review of a pull request's lockfile change, with each change's analysis."""
    review = session.scalars(
        select(models.Review)
        .where(models.Review.repository == f"{owner}/{repo}", models.Review.pull_number == number)
        .order_by(models.Review.created_at.desc(), models.Review.id.desc())
        .limit(1)
    ).first()
    if review is None:
        raise HTTPException(404, f"no review of {owner}/{repo}#{number}")
    rows = session.scalars(
        select(models.ReviewChange).where(models.ReviewChange.review_id == review.id).order_by(models.ReviewChange.id)
    )
    changes = [
        ReviewChangeOut(
            ecosystem=c.ecosystem,  # type: ignore[arg-type]
            package=c.package,
            kind=c.kind,  # type: ignore[arg-type]
            from_version=c.from_version,
            to_version=c.to_version,
            compare_from=c.compare_from,
            environments=[str(e) for e in c.environments],
            platforms=[str(p) for p in c.platforms],
            only_some_platforms=c.only_some_platforms,
            path=[str(p) for p in c.path],
            analysis=_analysis(session, c),
        )
        for c in rows
    ]
    changes.sort(key=_rank)
    # Analyses finish over time; the page polls while any is pending.
    response.headers["Cache-Control"] = "no-store"
    return Review(
        repository=review.repository,
        number=review.pull_number,
        base_sha=review.base_sha,
        head_sha=review.head_sha,
        lockfile_path=review.lockfile_path,
        created_at=review.created_at,
        platforms=sorted({p for c in changes for p in c.platforms}),
        changes=changes,
    )
