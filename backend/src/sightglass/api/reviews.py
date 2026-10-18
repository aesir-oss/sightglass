"""The review API: a pull request's lockfile changes, the ones that need a look first."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session, aliased

from sightglass.api.deps import Enqueue, Index, get_enqueue, get_index, get_pulls, get_session
from sightglass.db import models
from sightglass.ecosystems.http import HttpError, RateLimitedError, ResponseTooLargeError
from sightglass.ecosystems.versions import is_downgrade
from sightglass.lockfiles.pixi import LockfileError
from sightglass.lockfiles.pulls import (
    TOKEN_ENV,
    PullRequestClient,
    PullRequestError,
    PullRequestNotFoundError,
    parse_pull_url,
)
from sightglass.lockfiles.review import review_lockfile
from sightglass.log import get_logger
from sightglass.rules.base import LEVELS
from sightglass.rules.ruleset import RULES

log = get_logger(__name__)
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
    # Whether a changed package moves to an older version.
    downgrade: bool
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


class ReviewSummary(BaseModel):
    """A pull request's latest review, for the list of reviews."""

    repository: str
    number: int
    head_sha: str
    lockfile_path: str
    created_at: datetime
    # Changes by kind: added, changed, removed.
    counts: dict[str, int]


class ReviewList(BaseModel):
    """The most recently reviewed pull requests, newest first."""

    reviews: list[ReviewSummary]


class ReviewRequest(BaseModel):
    """A public pull request to review, by its URL."""

    url: str = Field(max_length=500, examples=["https://github.com/owner/name/pull/12"])


class ReviewCreated(BaseModel):
    """Where a new review is: its page is ``/reviews/{repository}/{number}``."""

    repository: str
    number: int
    lockfile_path: str


# The most pull requests the list shows.
LIST_LIMIT = 200


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


@router.get("/api/reviews", operation_id="listReviews")
def list_reviews(response: Response, session: Annotated[Session, Depends(get_session)]) -> ReviewList:
    """Each pull request's latest review, newest first."""
    latest = (
        select(models.Review)
        .ext(distinct_on(models.Review.repository, models.Review.pull_number))
        .order_by(
            models.Review.repository,
            models.Review.pull_number,
            models.Review.created_at.desc(),
            models.Review.id.desc(),
        )
        .subquery()
    )
    review = aliased(models.Review, latest)
    rows = list(session.scalars(select(review).order_by(review.created_at.desc(), review.id.desc()).limit(LIST_LIMIT)))
    counts: dict[int, dict[str, int]] = {r.id: {} for r in rows}
    for review_id, kind, count in session.execute(
        select(models.ReviewChange.review_id, models.ReviewChange.kind, func.count())
        .where(models.ReviewChange.review_id.in_(counts))
        .group_by(models.ReviewChange.review_id, models.ReviewChange.kind)
    ):
        counts[review_id][kind] = count
    # New reviews appear as they are recorded.
    response.headers["Cache-Control"] = "no-store"
    return ReviewList(
        reviews=[
            ReviewSummary(
                repository=r.repository,
                number=r.pull_number,
                head_sha=r.head_sha,
                lockfile_path=r.lockfile_path,
                created_at=r.created_at,
                counts=counts[r.id],
            )
            for r in rows
        ]
    )


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
            downgrade=c.kind == "changed" and is_downgrade(c.ecosystem, c.from_version or "", c.to_version or ""),
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


@router.post(
    "/api/reviews",
    operation_id="createReview",
    status_code=201,
    responses={
        404: {"description": "No public pull request at that URL"},
        422: {"description": "Not a pull request URL, or no lockfile that can be reviewed"},
        502: {"description": "GitHub couldn't be reached"},
        503: {"description": "GitHub's rate limit is used up"},
    },
)
def create_review(
    request: ReviewRequest,
    session: Annotated[Session, Depends(get_session)],
    index: Annotated[Index, Depends(get_index)],
    enqueue: Annotated[Enqueue, Depends(get_enqueue)],
    pulls: Annotated[PullRequestClient, Depends(get_pulls)],
) -> ReviewCreated:
    """Review a public pull request's lockfile change from its URL, and queue the analyses it needs."""
    try:
        change = pulls.lockfile_change(parse_pull_url(request.url))
        review_lockfile(
            session,
            pypi=index.pypi,
            enqueue=lambda eco, pkg, old, new: enqueue(eco, pkg, old, new, None),
            repository=change.repository,
            pull_number=change.number,
            base_sha=change.base_sha,
            head_sha=change.head_sha,
            lockfile_path=change.lockfile_path,
            base=change.base,
            head=change.head,
        )
    except PullRequestNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (PullRequestError, LockfileError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except ResponseTooLargeError as exc:
        raise HTTPException(422, "the lockfile is too large to review") from exc
    except RateLimitedError as exc:
        log.warning("review_github_rate_limited", error=str(exc))
        raise HTTPException(503, f"GitHub's rate limit is used up; try again later, or set {TOKEN_ENV}") from exc
    except HttpError as exc:
        log.warning("review_github_failed", error=str(exc))
        raise HTTPException(502, "GitHub couldn't be reached; try again shortly") from exc
    session.commit()
    log.info("review_from_url", repository=change.repository, pull_number=change.number, lockfile=change.lockfile_path)
    return ReviewCreated(repository=change.repository, number=change.number, lockfile_path=change.lockfile_path)
