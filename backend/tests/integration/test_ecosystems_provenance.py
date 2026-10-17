"""Integration tests for the Integrity API client (respx) and for storing provenance (Postgres)."""

from collections.abc import Callable, Iterator

import pytest
import respx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sightglass.db.models import Artifact, Attestation, Package, Release
from sightglass.ecosystems.http import Fetcher, HttpError, default_client
from sightglass.ecosystems.provenance import ABSENT, IntegrityClient, parse_provenance, record_provenance
from sightglass.ecosystems.pypi import PYPI_HOSTS, IndexDataError

WHEEL = "orbit_client-2.5.0-py3-none-any.whl"
PROVENANCE_URL = f"https://pypi.org/integrity/orbit-client/2.5.0/{WHEEL}/provenance"


@pytest.fixture
def client() -> Iterator[IntegrityClient]:
    """An Integrity API client that doesn't wait between retries."""
    with default_client() as http:
        yield IntegrityClient(Fetcher(http, PYPI_HOSTS, max_attempts=2, sleep=lambda _: None))


@pytest.mark.integration
@respx.mock
def test_provenance_urls_from_simple_api(client: IntegrityClient) -> None:
    """The Simple API says which files are attested."""
    simple = {
        "meta": {"api-version": "1.4"},
        "files": [
            {"filename": WHEEL, "provenance": PROVENANCE_URL, "hashes": {}},
            {"filename": "orbit_client-2.5.0.tar.gz", "hashes": {}},
        ],
    }
    route = respx.get("https://pypi.org/simple/orbit-client/").respond(200, json=simple)

    assert client.provenance_urls("Orbit_Client") == {WHEEL: PROVENANCE_URL, "orbit_client-2.5.0.tar.gz": None}
    assert route.calls.last.request.headers["Accept"] == "application/vnd.pypi.simple.v1+json"


@pytest.mark.integration
@respx.mock
def test_malformed_simple_api_raises(client: IntegrityClient) -> None:
    """A Simple API response without files is IndexDataError."""
    respx.get("https://pypi.org/simple/orbit-client/").respond(200, json={"meta": {}})
    with pytest.raises(IndexDataError):
        client.provenance_urls("orbit-client")


@pytest.mark.integration
@respx.mock
def test_present_and_absent_provenance(client: IntegrityClient, provenance_payload: Callable[..., bytes]) -> None:
    """A 200 is present provenance; a 404 is absent, not an error."""
    respx.get(PROVENANCE_URL).respond(200, content=provenance_payload())
    respx.get("https://pypi.org/integrity/orbit-client/2.5.0/orbit_client-2.5.0.tar.gz/provenance").respond(404)

    present = client.provenance("orbit-client", "2.5.0", WHEEL)
    assert present.status == "present"
    assert present.attestations[0].publisher.repository == "kestrel-weather/orbit-client"
    assert client.provenance("orbit-client", "2.5.0", "orbit_client-2.5.0.tar.gz") is ABSENT


@pytest.mark.integration
@respx.mock
def test_server_errors_are_not_absence(client: IntegrityClient) -> None:
    """When PyPI can't answer, the status stays unknown: the caller gets an error, not 'absent'."""
    respx.get(PROVENANCE_URL).respond(503)
    with pytest.raises(HttpError):
        client.provenance("orbit-client", "2.5.0", WHEEL)


def make_artifact(session: Session) -> Artifact:
    """An invented artifact row to attach provenance to."""
    package = Package(ecosystem="pypi", name="orbit-client", display_name="orbit-client")
    artifact = Artifact(
        release=Release(package=package, version="2.5.0"), filename=WHEEL, kind="wheel", sha256="2" * 64, size=1
    )
    session.add(artifact)
    session.flush()
    return artifact


@pytest.mark.integration
def test_record_present_provenance(db_session: Session, provenance_payload: Callable[..., bytes]) -> None:
    """Present provenance sets the status and stores each attestation with the raw response."""
    artifact = make_artifact(db_session)
    assert artifact.provenance_status == "unknown"
    provenance = parse_provenance(provenance_payload())
    record_provenance(db_session, artifact.id, provenance)
    record_provenance(db_session, artifact.id, provenance)
    db_session.expire_all()

    rows = db_session.scalars(select(Attestation).where(Attestation.artifact_id == artifact.id)).all()
    assert len(rows) == 1
    row = rows[0]
    assert (row.publisher_kind, row.repository, row.workflow, row.environment) == (
        "GitHub",
        "kestrel-weather/orbit-client",
        "release.yml",
        "pypi",
    )
    assert (row.source_commit, row.source_ref, row.runner_environment, row.build_trigger) == (
        "0123456789abcdef0123456789abcdef01234567",
        "refs/tags/v2.5.0",
        "github-hosted",
        "release",
    )
    assert row.verified is False
    assert row.bundle == provenance.raw
    assert db_session.get(Artifact, artifact.id).provenance_status == "present"  # type: ignore[union-attr]


@pytest.mark.integration
def test_record_absent_provenance_clears_rows(db_session: Session, provenance_payload: Callable[..., bytes]) -> None:
    """Absence is a recorded fact, and replaces attestations stored earlier."""
    artifact = make_artifact(db_session)
    record_provenance(db_session, artifact.id, parse_provenance(provenance_payload()))
    record_provenance(db_session, artifact.id, ABSENT)
    db_session.expire_all()

    assert db_session.scalars(select(Attestation)).all() == []
    assert db_session.get(Artifact, artifact.id).provenance_status == "absent"  # type: ignore[union-attr]


@pytest.mark.integration
def test_provenance_status_is_constrained(db_session: Session) -> None:
    """Only unknown, absent and present are valid statuses."""
    artifact = make_artifact(db_session)
    artifact.provenance_status = "trusted"
    with pytest.raises(IntegrityError):
        db_session.flush()
