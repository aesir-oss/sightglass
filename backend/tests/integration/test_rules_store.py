"""Storing analyses and signals under a rule-set version, against a real Postgres."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sightglass.db.models import Analysis, Artifact, Package, Release
from sightglass.db.models import Signal as SignalRow
from sightglass.rules.base import Evidence, Signal
from sightglass.rules.store import current_analysis, save_analysis


def artifact_pair(session: Session) -> tuple[int, int]:
    """Insert two releases of an invented package with one wheel each."""
    package = Package(ecosystem="pypi", name="orbit-client", display_name="orbit-client")
    old = Artifact(
        release=Release(package=package, version="2.4.1"),
        filename="orbit_client-2.4.1-py3-none-any.whl",
        kind="wheel",
        sha256="a" * 64,
        size=1,
    )
    new = Artifact(
        release=Release(package=package, version="2.5.0"),
        filename="orbit_client-2.5.0-py3-none-any.whl",
        kind="wheel",
        sha256="b" * 64,
        size=1,
    )
    session.add_all([old, new])
    session.flush()
    return old.id, new.id


SIGNALS = [
    Signal("files.example", "high", "orbit/telemetry.py isn't in tag v2.5.0", (Evidence("orbit/telemetry.py"),)),
    Signal("timing.example", "note", "Published 2 days after 2.4.1"),
]


@pytest.mark.integration
def test_saved_analysis_is_current_only_for_its_ruleset(db_session: Session) -> None:
    """An analysis is found under the rule-set version it ran with and is stale under any other."""
    old, new = artifact_pair(db_session)
    assert current_analysis(db_session, old, new, "rs-1") is None

    analysis_id = save_analysis(db_session, old, new, "rs-1", SIGNALS)

    found = current_analysis(db_session, old, new, "rs-1")
    assert found is not None and found.id == analysis_id and found.finished_at is not None
    assert current_analysis(db_session, old, new, "rs-2") is None
    rows = db_session.scalars(select(SignalRow).where(SignalRow.analysis_id == analysis_id).order_by(SignalRow.id))
    assert [(r.rule_id, r.level, r.evidence) for r in rows] == [
        ("files.example", "high", {"items": [{"file": "orbit/telemetry.py"}]}),
        ("timing.example", "note", {"items": []}),
    ]


@pytest.mark.integration
def test_saving_again_replaces_the_signals(db_session: Session) -> None:
    """Rerunning the same rule set keeps one analysis row and replaces its signals; a pending row is finished."""
    old, new = artifact_pair(db_session)
    pending = Analysis(from_artifact_id=old, to_artifact_id=new, ruleset_version="rs-1")
    db_session.add(pending)
    db_session.flush()
    assert current_analysis(db_session, old, new, "rs-1") is None

    first = save_analysis(db_session, old, new, "rs-1", SIGNALS)
    second = save_analysis(db_session, old, new, "rs-1", SIGNALS[:1])

    assert first == second == pending.id
    assert db_session.scalar(select(func.count()).select_from(SignalRow)) == 1
    assert db_session.scalar(select(func.count()).select_from(Analysis)) == 1
