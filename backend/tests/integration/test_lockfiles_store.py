"""Tests for storing a lockfile review."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sightglass.db import models
from sightglass.lockfiles.diff import Change
from sightglass.lockfiles.store import record_review, review_changes

BASE, HEAD = "a" * 40, "b" * 40
ADDED = Change(
    "pypi", "telemetry", "added", None, "0.1", ("default",), ("linux-64",), True, ("orbit-client", "telemetry")
)
CHANGED = Change("conda", "kestrel", "changed", "1.4.0", "1.5.0", ("default",), ("linux-64",), False, ("kestrel",))


def record(session: Session, *changes: Change) -> int:
    """Record a review of kestrel-weather/orbit's pixi.lock with ``changes``."""
    return record_review(
        session,
        repository="kestrel-weather/orbit",
        pull_number=42,
        base_sha=BASE,
        head_sha=HEAD,
        lockfile_path="pixi.lock",
        changes=changes,
    )


@pytest.mark.integration
def test_review_and_changes_are_stored(db_session: Session) -> None:
    """A review keeps every field of its changes, in order."""
    review_id = record(db_session, ADDED, CHANGED)
    stored = review_changes(db_session, review_id)
    assert [(c.package, c.kind, c.from_version, c.to_version, c.path) for c in stored] == [
        ("telemetry", "added", None, "0.1", ["orbit-client", "telemetry"]),
        ("kestrel", "changed", "1.4.0", "1.5.0", ["kestrel"]),
    ]
    assert stored[0].only_some_platforms and stored[0].platforms == ["linux-64"]


@pytest.mark.integration
def test_recording_the_same_push_again_replaces_its_changes(db_session: Session) -> None:
    """The same pull request, head commit and lockfile is one review; its changes are the latest diff."""
    first = record(db_session, ADDED, CHANGED)
    second = record(db_session, CHANGED)
    assert first == second
    assert [c.package for c in review_changes(db_session, second)] == ["kestrel"]
    assert db_session.scalar(select(func.count()).select_from(models.Review)) == 1


@pytest.mark.integration
def test_versions_must_match_the_kind(db_session: Session) -> None:
    """An added package with a from version is refused by the database."""
    bad = Change("pypi", "x", "added", "1.0", "2.0", ("default",), ("linux-64",), False, ())
    with pytest.raises(IntegrityError):
        record(db_session, bad)
