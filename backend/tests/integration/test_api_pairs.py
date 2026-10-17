"""Contract tests for GET /api/{ecosystem}/{package}/{versions}, against Postgres with PyPI served by respx."""

import json
from collections.abc import Iterator
from typing import Any

import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from sightglass.api.app import create_app
from sightglass.api.deps import Index, get_enqueue, get_index, get_session
from sightglass.db import models
from sightglass.ecosystems.http import Fetcher, default_client
from sightglass.ecosystems.provenance import IntegrityClient
from sightglass.ecosystems.pypi import PYPI_HOSTS, PypiClient, parse_project
from sightglass.rules.base import Evidence, Signal
from sightglass.rules.ruleset import RULES
from sightglass.rules.store import fail_analysis, mark_step, save_analysis
from sightglass.worker.catalog import record_artifact, record_package, record_release

VERSIONS = ("2.4.1", "2.5.0", "2.6.0")
WHEELS = ("py3-none-any", "cp314-cp314-manylinux_2_17_x86_64")


def project_json() -> bytes:
    """Three releases, each with an sdist and two wheels."""
    releases = {}
    for n, v in enumerate(VERSIONS):
        names = [f"orbit_client-{v}.tar.gz", *(f"orbit_client-{v}-{t}.whl" for t in WHEELS)]
        releases[v] = [
            {
                "filename": name,
                "url": f"https://files.pythonhosted.org/packages/{name}",
                "digests": {"sha256": f"{n}{i}".ljust(64, "a")},
                "size": 100,
                "upload_time_iso_8601": f"2026-0{n + 7}-01T00:00:00Z",
                "packagetype": "sdist" if name.endswith(".tar.gz") else "bdist_wheel",
            }
            for i, name in enumerate(names)
        ]
    return json.dumps({"info": {"name": "orbit-client"}, "releases": releases}).encode()


FACTS = {
    "version": "2.4.1",
    "published_at": "2026-07-01T00:00:00+00:00",
    "attestation": "present",
    "publisher": {
        "kind": "GitHub",
        "repository": "kestrel-weather/orbit-client",
        "workflow": "release.yml",
        "environment": None,
    },
    "build_tool": "hatchling",
    "file_count": 2,
    "total_size": 300,
    "artifact_sha256": "a" * 64,
    "requires_dist": ["httpx>=0.27"],
}
REPORT: dict[str, Any] = {
    "version": 1,
    "files": [
        {
            "path": "orbit/__init__.py",
            "status": "changed",
            "text": True,
            "compiled": False,
            "old_size": 10,
            "new_size": 12,
            "old_sha256": "b" * 64,
            "new_sha256": "c" * 64,
        },
        {
            "path": "orbit/telemetry.py",
            "status": "added",
            "text": True,
            "compiled": False,
            "old_size": None,
            "new_size": 80,
            "old_sha256": None,
            "new_sha256": "d" * 64,
        },
    ],
    "source": {
        "state": "compared",
        "label": "tag v2.5.0",
        "repository": "kestrel-weather/orbit-client",
        "commit": "0" * 40,
        "ref": "refs/tags/v2.5.0",
        "origin": "tag",
        "root": "src/",
        "files": [{"path": "orbit/telemetry.py", "status": "missing", "source_path": None, "text": True}],
        "excluded": ["orbit_client-2.5.0.dist-info/RECORD"],
    },
    "sdist": None,
    "facts": {"old": FACTS, "new": {**FACTS, "version": "2.5.0", "attestation": "absent", "publisher": None}},
}


@pytest.fixture
def world(db_session: Session) -> Iterator[tuple[TestClient, list[tuple[Any, ...]], dict[str, int]]]:
    """The app on the test session with a recording queue, and artifact rows for every file by name."""
    queued: list[tuple[Any, ...]] = []
    http = default_client()
    fetcher = Fetcher(http, PYPI_HOSTS, max_attempts=2, sleep=lambda _: None)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_index] = lambda: Index(PypiClient(fetcher), IntegrityClient(fetcher))
    app.dependency_overrides[get_enqueue] = lambda: lambda *args: queued.append(args) or 1

    project = parse_project(project_json())
    package_id = record_package(db_session, project)
    ids = {}
    for release in project.releases:
        release_id = record_release(db_session, package_id, release)
        for f in release.files:
            ids[f.filename] = record_artifact(db_session, release_id, f)
    db_session.commit()
    with respx.mock:
        respx.get("https://pypi.org/pypi/orbit-client/json").respond(200, content=project_json())
        respx.get("https://pypi.org/pypi/tidepool/json").respond(404)
        respx.get("https://pypi.org/pypi/kestrel/json").respond(503)
        yield TestClient(app), queued, ids
    http.close()


WHEEL_OLD, WHEEL_NEW = "orbit_client-2.4.1-py3-none-any.whl", "orbit_client-2.5.0-py3-none-any.whl"


@pytest.mark.integration
def test_missing_analysis_is_queued(world: tuple[TestClient, list[Any], dict[str, int]]) -> None:
    """A pair with no analysis under the current rule set is queued and answered with 202."""
    client, queued, _ = world
    response = client.get("/api/pypi/Orbit_Client/2.4.1...2.5.0")
    assert response.status_code == 202
    assert (response.headers["retry-after"], response.headers["cache-control"]) == ("3", "no-store")
    body = response.json()
    assert (body["status"], body["artifact"]["new_filename"]) == ("pending", WHEEL_NEW)
    assert [a["kind"] for a in body["alternatives"]] == ["sdist", "wheel", "wheel"]
    assert queued == [("pypi", "orbit-client", "2.4.1", "2.5.0", None)]


@pytest.mark.integration
def test_done_analysis(world: tuple[TestClient, list[Any], dict[str, int]], db_session: Session) -> None:
    """A finished analysis returns its signals, files (flagged where evidence points), source check and facts."""
    client, queued, ids = world
    signals = [
        Signal("source.not_in_tag", "high", "orbit/telemetry.py isn't in tag v2.5.0", (Evidence("orbit/telemetry.py"),))
    ]
    save_analysis(db_session, ids[WHEEL_OLD], ids[WHEEL_NEW], RULES.version, signals, REPORT)
    db_session.commit()

    response = client.get("/api/pypi/orbit-client/2.4.1...2.5.0")
    assert response.status_code == 200 and queued == []
    body = response.json()
    assert (body["status"], body["ruleset_version"]) == ("done", RULES.version)
    assert body["signals"] == [
        {
            "rule_id": "source.not_in_tag",
            "level": "high",
            "message": "orbit/telemetry.py isn't in tag v2.5.0",
            "evidence": [{"file": "orbit/telemetry.py"}],
        }
    ]
    assert [(f["path"], f["flagged"]) for f in body["files"]] == [
        ("orbit/__init__.py", False),
        ("orbit/telemetry.py", True),
    ]
    assert (body["source"]["state"], body["source"]["label"]) == ("compared", "tag v2.5.0")
    assert (body["facts"]["old"]["attestation"], body["facts"]["new"]["attestation"]) == ("present", "absent")


@pytest.mark.integration
def test_single_version_compares_with_its_predecessor(world: tuple[TestClient, list[Any], dict[str, int]]) -> None:
    """``/{version}`` compares the release before it with that one; the first release has nothing to compare."""
    client, _, _ = world
    body = client.get("/api/pypi/orbit-client/2.6.0").json()
    assert (body["from_version"], body["to_version"]) == ("2.5.0", "2.6.0")
    assert client.get("/api/pypi/orbit-client/2.4.1").status_code == 404


@pytest.mark.integration
def test_artifact_picker(world: tuple[TestClient, list[Any], dict[str, int]]) -> None:
    """The sdist and alternative wheels can be chosen; a non-default wheel is queued on its own."""
    client, queued, _ = world
    sdist = client.get("/api/pypi/orbit-client/2.4.1...2.5.0", params={"kind": "sdist"}).json()
    assert sdist["artifact"]["kind"] == "sdist"
    other = "orbit_client-2.5.0-cp314-cp314-manylinux_2_17_x86_64.whl"
    picked = client.get("/api/pypi/orbit-client/2.4.1...2.5.0", params={"wheel": other}).json()
    assert picked["artifact"]["new_filename"] == other
    assert queued[-1] == ("pypi", "orbit-client", "2.4.1", "2.5.0", other)
    assert client.get("/api/pypi/orbit-client/2.4.1...2.5.0", params={"wheel": "nope.whl"}).status_code == 404


@pytest.mark.integration
def test_failed_analysis_and_errors(world: tuple[TestClient, list[Any], dict[str, int]], db_session: Session) -> None:
    """A failed analysis says why; unknown packages, versions and ecosystems are 404; an index outage is 503."""
    client, _, ids = world
    fail_analysis(db_session, ids[WHEEL_OLD], ids[WHEEL_NEW], RULES.version, "ArtifactIntegrityError: sha256 mismatch")
    db_session.commit()
    failed = client.get("/api/pypi/orbit-client/2.4.1...2.5.0").json()
    assert (failed["status"], failed["error"]) == ("failed", "ArtifactIntegrityError: sha256 mismatch")

    assert client.get("/api/pypi/orbit-client/2.4.1...9.9.9").status_code == 404
    assert client.get("/api/pypi/orbit-client/9.9.9").status_code == 404
    assert client.get("/api/pypi/tidepool/1.0...1.1").status_code == 404
    assert client.get("/api/npm/orbit-client/1.0...1.1").status_code == 404
    outage = client.get("/api/pypi/kestrel/1.0...1.1")
    assert (outage.status_code, outage.headers["retry-after"]) == (503, "30")


@pytest.mark.integration
def test_releases_route_still_wins(world: tuple[TestClient, list[Any], dict[str, int]]) -> None:
    """``/releases`` is the history, not a version."""
    client, queued, _ = world
    respx.get("https://pypi.org/simple/orbit-client/").respond(200, content=b'{"files": []}')
    assert "releases" in client.get("/api/pypi/orbit-client/releases").json()
    assert queued == []


@pytest.mark.integration
def test_pending_shows_the_current_step(
    world: tuple[TestClient, list[Any], dict[str, int]], db_session: Session
) -> None:
    """While a worker runs, the 202 says which step it is on, with the list of steps."""
    client, _, ids = world
    mark_step(db_session, ids[WHEEL_OLD], ids[WHEEL_NEW], RULES.version, "source")
    body = client.get("/api/pypi/orbit-client/2.4.1...2.5.0").json()
    assert (body["status"], body["step"]) == ("pending", "source")
    assert body["steps"] == ["downloading", "provenance", "diffing", "source", "rules"]


@pytest.mark.integration
def test_retry_a_failed_analysis(world: tuple[TestClient, list[Any], dict[str, int]], db_session: Session) -> None:
    """Retrying a failed pair makes it pending and queues it again; anything else is a 409."""
    client, queued, ids = world
    assert client.post("/api/pypi/orbit-client/2.4.1...2.5.0/retry").status_code == 409
    analysis_id = fail_analysis(db_session, ids[WHEEL_OLD], ids[WHEEL_NEW], RULES.version, "ArtifactIntegrityError: x")
    db_session.commit()

    response = client.post("/api/pypi/orbit-client/2.4.1...2.5.0/retry")
    assert response.status_code == 202 and response.json()["status"] == "pending"
    assert queued == [("pypi", "orbit-client", "2.4.1", "2.5.0", None)]
    row = db_session.get(models.Analysis, analysis_id)
    assert row is not None
    db_session.refresh(row)
    assert (row.status, row.error) == ("pending", None)
    assert client.get("/api/pypi/orbit-client/2.4.1...2.5.0").status_code == 202


@pytest.mark.integration
def test_an_analysis_without_a_report_is_queued_again(
    world: tuple[TestClient, list[Any], dict[str, int]], db_session: Session
) -> None:
    """A done analysis stored before reports existed is treated as missing: the pair is queued."""
    client, queued, ids = world
    save_analysis(db_session, ids[WHEEL_OLD], ids[WHEEL_NEW], RULES.version, [])
    db_session.commit()
    assert client.get("/api/pypi/orbit-client/2.4.1...2.5.0").status_code == 202
    assert queued == [("pypi", "orbit-client", "2.4.1", "2.5.0", None)]
