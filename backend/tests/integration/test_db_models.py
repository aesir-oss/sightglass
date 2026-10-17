"""Integration tests for the schema's constraints against a real Postgres."""

from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sightglass.db.models import Analysis, Artifact, Blob, File, Package, Release, Signal, SourceSnapshot

SHA_A = "a" * 64
SHA_B = "b" * 64


def make_artifact(session: Session, filename: str = "orbit_client-2.5.0-py3-none-any.whl") -> Artifact:
    """Insert a package, release and artifact for an invented package."""
    package = Package(ecosystem="pypi", name="orbit-client", display_name="Orbit_Client")
    release = Release(package=package, version="2.5.0")
    artifact = Artifact(release=release, filename=filename, kind="wheel", sha256=SHA_A, size=1024)
    session.add(artifact)
    session.flush()
    return artifact


def assert_rejected(session: Session, obj: Any) -> None:
    """Flushing ``obj`` violates a constraint; the session stays usable afterwards."""
    savepoint = session.begin_nested()
    session.add(obj)
    with pytest.raises(IntegrityError):
        session.flush()
    savepoint.rollback()


@pytest.mark.integration
def test_package_round_trip(db_session: Session) -> None:
    """A package, release and artifact can be stored and read back with server defaults filled."""
    artifact = make_artifact(db_session)
    db_session.expire_all()

    stored = db_session.get(Artifact, artifact.id)
    assert stored is not None
    assert stored.release.package.name == "orbit-client"
    assert stored.release.yanked is False
    assert stored.release.package.created_at.tzinfo is not None


@pytest.mark.integration
@pytest.mark.parametrize("name", ["Orbit-Client", "orbit_client", "orbit.client", ""])
def test_pypi_name_must_be_normalized(db_session: Session, name: str) -> None:
    """The database rejects PyPI names that aren't in PEP 503 form."""
    assert_rejected(db_session, Package(ecosystem="pypi", name=name, display_name=name or "x"))


@pytest.mark.integration
def test_unknown_ecosystem_rejected(db_session: Session) -> None:
    """Only known ecosystems are accepted."""
    assert_rejected(db_session, Package(ecosystem="cpan", name="tidepool", display_name="tidepool"))


@pytest.mark.integration
def test_duplicate_package_rejected(db_session: Session) -> None:
    """One row per ecosystem and name."""
    db_session.add(Package(ecosystem="pypi", name="tidepool", display_name="tidepool"))
    db_session.flush()
    assert_rejected(db_session, Package(ecosystem="pypi", name="tidepool", display_name="Tidepool"))


@pytest.mark.integration
@pytest.mark.parametrize("sha", ["A" * 64, "a" * 63, "g" * 64])
def test_artifact_sha256_must_be_lowercase_hex(db_session: Session, sha: str) -> None:
    """Hashes are stored as 64 lowercase hex characters."""
    artifact = make_artifact(db_session)
    assert_rejected(
        db_session, Artifact(release_id=artifact.release_id, filename="x.tar.gz", kind="sdist", sha256=sha, size=1)
    )


@pytest.mark.integration
def test_file_belongs_to_exactly_one_owner(db_session: Session) -> None:
    """A file row points at an artifact or a source snapshot, never both or neither."""
    artifact = make_artifact(db_session)
    db_session.add(Blob(sha256=SHA_B, size=10, storage_key="bb/" + SHA_B))
    snapshot = SourceSnapshot(
        package_id=artifact.release.package_id,
        repository="kestrel-weather/orbit-client",
        commit="c" * 40,
        archive_sha256=SHA_B,
        origin="attestation",
    )
    db_session.add(snapshot)
    db_session.flush()

    assert_rejected(db_session, File(path="orbit/__init__.py", sha256=SHA_B, size=10, file_type="python"))
    assert_rejected(
        db_session,
        File(
            artifact_id=artifact.id,
            source_snapshot_id=snapshot.id,
            path="orbit/__init__.py",
            sha256=SHA_B,
            size=10,
            file_type="python",
        ),
    )
    db_session.add(File(artifact_id=artifact.id, path="orbit/__init__.py", sha256=SHA_B, size=10, file_type="python"))
    db_session.flush()


@pytest.mark.integration
def test_tag_snapshot_needs_ref_and_pattern(db_session: Session) -> None:
    """A source found through a tag records which tag and which pattern matched."""
    artifact = make_artifact(db_session)
    assert_rejected(
        db_session,
        SourceSnapshot(
            package_id=artifact.release.package_id,
            repository="kestrel-weather/orbit-client",
            commit="d" * 40,
            archive_sha256=SHA_B,
            origin="tag",
        ),
    )


@pytest.mark.integration
def test_failed_analysis_needs_error(db_session: Session) -> None:
    """A failed analysis always says why."""
    artifact = make_artifact(db_session)
    assert_rejected(
        db_session,
        Analysis(from_artifact_id=artifact.id, to_artifact_id=artifact.id, ruleset_version="1", status="failed"),
    )


@pytest.mark.integration
def test_signal_evidence_round_trips_and_cascades(db_session: Session) -> None:
    """Evidence JSON is stored as given, and deleting an analysis deletes its signals."""
    artifact = make_artifact(db_session)
    evidence = {"file": "orbit/__init__.py", "lines": [12, 14], "added": True}
    analysis = Analysis(from_artifact_id=artifact.id, to_artifact_id=artifact.id, ruleset_version="1")
    analysis.signals.append(
        Signal(rule_id="behavior.import_time", level="high", message="New code runs on import.", evidence=evidence)
    )
    db_session.add(analysis)
    db_session.flush()
    db_session.expire_all()

    signal = db_session.scalars(select(Signal).where(Signal.analysis_id == analysis.id)).one()
    assert signal.evidence == evidence
    assert db_session.scalar(select(Analysis.status).where(Analysis.id == analysis.id)) == "pending"

    db_session.delete(db_session.get(Analysis, analysis.id))
    db_session.flush()
    assert db_session.scalar(select(func.count()).select_from(Signal)) == 0


@pytest.mark.integration
def test_signal_level_is_constrained(db_session: Session) -> None:
    """Levels are high, check, note or clean; never a verdict like malicious."""
    artifact = make_artifact(db_session)
    analysis = Analysis(from_artifact_id=artifact.id, to_artifact_id=artifact.id, ruleset_version="1")
    db_session.add(analysis)
    db_session.flush()
    assert_rejected(
        db_session, Signal(analysis_id=analysis.id, rule_id="x", level="malicious", message="x", evidence={})
    )


@pytest.mark.integration
@pytest.mark.parametrize("attempt", [1, 2])
def test_each_test_starts_empty(db_session: Session, attempt: int) -> None:
    """Rows from one test never leak into the next: each runs in a rolled-back transaction."""
    assert db_session.scalar(select(func.count()).select_from(Package)) == 0
    make_artifact(db_session)
    db_session.commit()
    assert db_session.scalar(select(func.count()).select_from(Package)) == 1
