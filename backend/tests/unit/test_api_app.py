"""Tests for sightglass.api.app."""

from fastapi.testclient import TestClient

from sightglass import __version__
from sightglass.api.app import create_app


def test_health_reports_ok_and_version() -> None:
    """The health route answers with the package version."""
    response = TestClient(create_app()).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}
