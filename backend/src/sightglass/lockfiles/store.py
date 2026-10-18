"""Storing a pull request's lockfile review: the review row and its changes."""

from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from sightglass.db import models
from sightglass.lockfiles.diff import Change


def record_review(
    session: Session,
    *,
    repository: str,
    pull_number: int,
    base_sha: str,
    head_sha: str,
    lockfile_path: str,
    changes: Iterable[Change],
) -> int:
    """Store a review and its changes; recording the same push and lockfile again replaces its changes.

    Args:
        session: The session to write through; the caller commits.
        repository: ``owner/name`` on GitHub.
        pull_number: The pull request's number.
        base_sha: The commit the pull request is compared against.
        head_sha: The pull request's head commit.
        lockfile_path: The lockfile's path in the repository.
        changes: The diff of the two lockfiles.

    Returns:
        The review's id.
    """
    stmt = insert(models.Review).values(
        repository=repository,
        pull_number=pull_number,
        base_sha=base_sha,
        head_sha=head_sha,
        lockfile_path=lockfile_path,
    )
    upsert = stmt.on_conflict_do_update(
        index_elements=["repository", "pull_number", "head_sha", "lockfile_path"],
        set_={"base_sha": stmt.excluded.base_sha},
    ).returning(models.Review.id)
    review_id = int(session.execute(upsert).scalar_one())
    session.execute(delete(models.ReviewChange).where(models.ReviewChange.review_id == review_id))
    session.add_all(
        models.ReviewChange(
            review_id=review_id,
            ecosystem=c.ecosystem,
            package=c.name,
            kind=c.kind,
            from_version=c.from_version,
            to_version=c.to_version,
            environments=list(c.environments),
            platforms=list(c.platforms),
            only_some_platforms=c.only_some_platforms,
            path=list(c.path),
        )
        for c in changes
    )
    session.flush()
    return review_id


def review_changes(session: Session, review_id: int) -> list[models.ReviewChange]:
    """A review's changes, in the order they were recorded."""
    return list(
        session.scalars(
            select(models.ReviewChange)
            .where(models.ReviewChange.review_id == review_id)
            .order_by(models.ReviewChange.id)
        )
    )
