"""Contract tests for GET /api/{ecosystem}/{package}/releases, against Postgres with PyPI served by respx."""

import json
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sightglass.api import releases
from sightglass.api.app import create_app
from sightglass.api.deps import Index, get_index, get_session
from sightglass.db import models
from sightglass.ecosystems.http import Fetcher, default_client
from sightglass.ecosystems.provenance import IntegrityClient
from sightglass.ecosystems.pypi import PYPI_HOSTS, PypiClient

PYPI = "https://pypi.org"
SHA = {"2.4.1": "1" * 64, "2.5.0": "2" * 64, "2.6.0": "3" * 64}


def project(*versions: str) -> bytes:
    """A JSON API response with a wheel and an sdist per version."""
    files = {
        v: [
            {
                "filename": f"orbit_client-{v}{suffix}",
                "url": f"https://files.pythonhosted.org/packages/orbit_client-{v}{suffix}",
                "digests": {"sha256": SHA[v][:-1] + str(i)},
                "size": 100,
                "upload_time_iso_8601": f"2026-0{i + 7}-0{n + 1}T00:00:00Z",
                "packagetype": "bdist_wheel" if suffix.endswith(".whl") else "sdist",
            }
            for i, suffix in enumerate(("-py3-none-any.whl", ".tar.gz"))
        ]
        for n, v in enumerate(versions)
    }
    return json.dumps({"info": {"name": "Orbit_Client"}, "releases": files}).encode()


def simple(attested: dict[str, bool]) -> bytes:
    """A Simple API JSON response naming each file's provenance URL, or null."""
    return json.dumps(
        {
            "files": [
                {"filename": name, "provenance": f"{PYPI}/integrity/{name}/provenance" if yes else None}
                for name, yes in attested.items()
            ]
        }
    ).encode()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    """The app on the rolled-back test session, with index clients that don't wait between retries."""
    http = default_client()
    fetcher = Fetcher(http, PYPI_HOSTS, max_attempts=2, sleep=lambda _: None)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_index] = lambda: Index(PypiClient(fetcher), IntegrityClient(fetcher))
    yield TestClient(app)
    http.close()


def mock_index(provenance_payload: Callable[..., bytes], attested: dict[str, bool]) -> dict[str, respx.Route]:
    """Routes for the project, its Simple API listing and the Integrity API."""
    return {
        "project": respx.get(f"{PYPI}/pypi/orbit-client/json").respond(200, content=project("2.4.1", "2.5.0")),
        "simple": respx.get(f"{PYPI}/simple/orbit-client/").respond(200, content=simple(attested)),
        "integrity": respx.get(url__startswith=f"{PYPI}/integrity/").respond(200, content=provenance_payload()),
    }


@pytest.mark.integration
@respx.mock
def test_release_history(client: TestClient, db_session: Session, provenance_payload: Callable[..., bytes]) -> None:
    """Releases come oldest first with publish time, attestation state and publisher; the index is recorded."""
    routes = mock_index(
        provenance_payload,
        {
            "orbit_client-2.4.1-py3-none-any.whl": False,
            "orbit_client-2.4.1.tar.gz": False,
            "orbit_client-2.5.0-py3-none-any.whl": True,
            "orbit_client-2.5.0.tar.gz": False,
        },
    )
    response = client.get("/api/pypi/Orbit.Client/releases")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60"
    body: dict[str, Any] = response.json()
    assert (body["ecosystem"], body["package"], body["display_name"]) == ("pypi", "orbit-client", "Orbit_Client")
    assert [(r["version"], r["attestation"], r["yanked"]) for r in body["releases"]] == [
        ("2.4.1", "none", False),
        ("2.5.0", "some", False),
    ]
    assert [r["previous"] for r in body["releases"]] == [None, "2.4.1"]
    assert body["latest"] == "2.5.0"
    assert body["releases"][0]["publisher"] is None
    assert body["releases"][1]["publisher"] == {
        "kind": "GitHub",
        "repository": "kestrel-weather/orbit-client",
        "workflow": "release.yml",
        "environment": "pypi",
    }
    assert body["releases"][0]["published_at"].startswith("2026-07-01")
    assert db_session.scalar(select(func.count()).select_from(models.Artifact)) == 4
    assert routes["integrity"].call_count == 1


@pytest.mark.integration
@respx.mock
def test_publishers_are_fetched_once(client: TestClient, provenance_payload: Callable[..., bytes]) -> None:
    """A second request reuses stored attestations; files the Simple API doesn't list stay unknown."""
    routes = mock_index(
        provenance_payload,
        {"orbit_client-2.5.0-py3-none-any.whl": True, "orbit_client-2.5.0.tar.gz": False},
    )
    first = client.get("/api/pypi/orbit-client/releases").json()
    second = client.get("/api/pypi/orbit-client/releases").json()
    assert first == second
    assert routes["integrity"].call_count == 1
    assert [r["attestation"] for r in first["releases"]] == ["unknown", "some"]


@pytest.mark.integration
@respx.mock
def test_only_recent_publishers_are_fetched(
    client: TestClient, provenance_payload: Callable[..., bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publisher details are fetched for the newest attested releases only."""
    monkeypatch.setattr(releases, "RECENT_PUBLISHERS", 1)
    routes = mock_index(
        provenance_payload,
        {"orbit_client-2.4.1-py3-none-any.whl": True, "orbit_client-2.5.0-py3-none-any.whl": True},
    )
    body = client.get("/api/pypi/orbit-client/releases").json()
    assert [r["publisher"] is not None for r in body["releases"]] == [False, True]
    assert routes["integrity"].call_count == 1


@pytest.mark.integration
@respx.mock
def test_index_failures(client: TestClient, provenance_payload: Callable[..., bytes]) -> None:
    """Unknown packages are 404, an index outage is 503 with Retry-After, and a Simple API outage leaves states unknown."""
    respx.get(f"{PYPI}/pypi/tidepool/json").respond(404)
    respx.get(f"{PYPI}/pypi/kestrel/json").respond(503)
    respx.get(f"{PYPI}/pypi/orbit-client/json").respond(200, content=project("2.4.1"))
    respx.get(f"{PYPI}/simple/orbit-client/").mock(side_effect=httpx.ConnectError("down"))

    assert client.get("/api/pypi/tidepool/releases").status_code == 404
    outage = client.get("/api/pypi/kestrel/releases")
    assert (outage.status_code, outage.headers["retry-after"]) == (503, "30")
    assert client.get("/api/npm/orbit-client/releases").status_code == 404
    degraded = client.get("/api/pypi/orbit-client/releases")
    assert [r["attestation"] for r in degraded.json()["releases"]] == ["unknown"]


@pytest.mark.integration
@respx.mock
def test_unreadable_attestation_leaves_publisher_empty(client: TestClient) -> None:
    """An Integrity API answer that can't be parsed doesn't fail the history."""
    respx.get(f"{PYPI}/pypi/orbit-client/json").respond(200, content=project("2.4.1"))
    listing = {"orbit_client-2.4.1-py3-none-any.whl": False, "orbit_client-2.4.1.tar.gz": True}
    respx.get(f"{PYPI}/simple/orbit-client/").respond(200, content=simple(listing))
    respx.get(url__startswith=f"{PYPI}/integrity/").respond(200, content=b"{}")
    [release] = client.get("/api/pypi/orbit-client/releases").json()["releases"]
    assert (release["attestation"], release["publisher"]) == ("some", None)
