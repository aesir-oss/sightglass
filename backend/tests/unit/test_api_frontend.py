"""Tests for serving the built frontend from the API."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sightglass.api import frontend
from sightglass.api.app import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """The app serving a fake build in tmp_path."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><div id=root></div>")
    (tmp_path / "assets" / "app-1234.js").write_text("console.log(1)")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    (tmp_path.parent / "secret.txt").write_text("no")
    app = create_app(serve_frontend=False)
    assert frontend.mount_frontend(app, tmp_path)
    return TestClient(app)


def test_pages_get_index_html(client: TestClient) -> None:
    """The root and any page route return index.html, uncached, for the React router."""
    for path in ("/", "/pypi/orbit-client/2.4.1...2.5.0", "/pypi/orbit-client/2.5.0"):
        response = client.get(path)
        assert response.status_code == 200 and "id=root" in response.text
        assert response.headers["cache-control"] == "no-cache"


def test_assets_and_top_level_files(client: TestClient) -> None:
    """Built assets and files at the top of the build are served as they are."""
    assert client.get("/assets/app-1234.js").text == "console.log(1)"
    assert client.get("/favicon.svg").text == "<svg/>"
    assert client.get("/assets/missing.js").status_code == 404


def test_api_paths_stay_api(client: TestClient) -> None:
    """Unknown API paths are JSON 404s, not the page; the API still answers."""
    response = client.get("/api/nope")
    assert response.status_code == 404 and response.json() == {"detail": "Not Found"}
    assert client.get("/api").status_code == 404
    assert client.get("/api/health").json()["status"] == "ok"


def test_paths_outside_the_build_are_not_served(client: TestClient) -> None:
    """A path that escapes the build directory gets the page, not the file."""
    response = client.get("/%2e%2e/secret.txt")
    assert "id=root" in response.text


def test_unbuilt_frontend_is_api_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a build the app serves only the API; the default directory comes from the environment."""
    monkeypatch.setenv(frontend.FRONTEND_DIR_ENV, str(tmp_path))
    assert frontend.frontend_dir() == tmp_path
    client = TestClient(create_app())
    assert client.get("/").status_code == 404
    assert client.get("/api/health").status_code == 200
