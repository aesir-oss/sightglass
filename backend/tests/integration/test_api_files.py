"""Contract tests for GET /api/{ecosystem}/{package}/{versions}/files/{path}, with real blobs and Postgres."""

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from sightglass.api.app import create_app
from sightglass.api.deps import Index, get_blobs, get_index, get_session
from sightglass.db import models
from sightglass.ecosystems.github import Repository
from sightglass.ecosystems.http import Fetcher, default_client
from sightglass.ecosystems.provenance import IntegrityClient
from sightglass.ecosystems.pypi import PYPI_HOSTS, PypiClient, parse_project
from sightglass.ecosystems.sources import SourceSnapshot, record_source_snapshot
from sightglass.rules.base import Evidence, Signal
from sightglass.rules.ruleset import RULES
from sightglass.rules.store import save_analysis
from sightglass.storage.blobs import LocalBlobStore
from sightglass.storage.catalog import record_blob
from sightglass.worker.catalog import record_artifact, record_package, record_release

COMMIT = "0123456789abcdef0123456789abcdef01234567"
OLD = b"".join(f"line {i}\n".encode() for i in range(1, 21))
NEW = OLD.replace(b"line 10\n", b"import socket\nsocket.create_connection(('example.net', 443))\n")
TAG = OLD
BINARY = b"\x7fELF\x02\x01\x01"


def sha(data: bytes) -> str:
    """Hex sha256."""
    return hashlib.sha256(data).hexdigest()


def project_json() -> bytes:
    """Two releases with one wheel each."""
    releases = {
        v: [
            {
                "filename": f"orbit_client-{v}-py3-none-any.whl",
                "url": f"https://files.pythonhosted.org/packages/orbit_client-{v}-py3-none-any.whl",
                "digests": {"sha256": str(n) * 64},
                "size": 100,
                "upload_time_iso_8601": f"2026-0{n + 7}-01T00:00:00Z",
                "packagetype": "bdist_wheel",
            }
        ]
        for n, v in enumerate(("2.4.1", "2.5.0"))
    }
    return json.dumps({"info": {"name": "orbit-client"}, "releases": releases}).encode()


def entry(path: str, status: str, old: bytes | None, new: bytes | None, *, text: bool = True) -> dict[str, Any]:
    """A report file entry."""
    return {
        "path": path,
        "status": status,
        "text": text,
        "compiled": not text,
        "old_size": len(old) if old is not None else None,
        "new_size": len(new) if new is not None else None,
        "old_sha256": sha(old) if old is not None else None,
        "new_sha256": sha(new) if new is not None else None,
    }


@pytest.fixture
def client(db_session: Session, tmp_path: Path) -> Iterator[TestClient]:
    """An analyzed pair with its blobs stored, a source snapshot, and a signal pointing at the new lines."""
    blobs = LocalBlobStore(tmp_path / "blobs")
    for data in (OLD, NEW, BINARY):
        record_blob(db_session, blobs.put_bytes(data))
    project = parse_project(project_json())
    package_id = record_package(db_session, project)
    ids = []
    for release in project.releases:
        ids.append(record_artifact(db_session, record_release(db_session, package_id, release), release.files[0]))
    snapshot = SourceSnapshot(
        Repository("kestrel-weather", "orbit-client"), COMMIT, "refs/tags/v2.5.0", "tag", "v{version}", "f" * 64, ()
    )
    snapshot_id = record_source_snapshot(db_session, package_id, snapshot)
    db_session.add(
        models.File(
            source_snapshot_id=snapshot_id,
            path=f"orbit-client-{COMMIT}/src/orbit/sync.py",
            sha256=sha(TAG),
            size=len(TAG),
            file_type="python",
        )
    )
    report = {
        "version": 1,
        "files": [
            entry("orbit/sync.py", "changed", OLD, NEW),
            entry("orbit/_fast.so", "changed", BINARY, BINARY + b"x", text=False),
            entry("orbit/same.py", "same", OLD, OLD),
            entry("orbit/lost.py", "changed", OLD, b"gone\n"),
        ],
        "source": {
            "state": "compared",
            "label": "tag v2.5.0",
            "repository": "kestrel-weather/orbit-client",
            "commit": COMMIT,
            "files": [{"path": "orbit/sync.py", "status": "differs", "source_path": "src/orbit/sync.py", "text": True}],
        },
        "facts": None,
    }
    signal = Signal(
        "behavior.network", "high", "Added network calls in orbit/sync.py", (Evidence("orbit/sync.py", 11, 11, "new"),)
    )
    save_analysis(db_session, ids[0], ids[1], RULES.version, [signal], report)
    db_session.commit()

    http = default_client()
    fetcher = Fetcher(http, PYPI_HOSTS, max_attempts=2, sleep=lambda _: None)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_index] = lambda: Index(PypiClient(fetcher), IntegrityClient(fetcher))
    app.dependency_overrides[get_blobs] = lambda: blobs
    with respx.mock:
        respx.get("https://pypi.org/pypi/orbit-client/json").respond(200, content=project_json())
        yield TestClient(app)
    http.close()


URL = "/api/pypi/orbit-client/2.4.1...2.5.0/files/"


@pytest.mark.integration
def test_diff_against_previous_marks_signal_lines(client: TestClient) -> None:
    """The diff has hunks with line numbers, and the line the signal points at is marked."""
    body = client.get(URL + "orbit/sync.py").json()
    assert (body["diff"], body["base"], body["base_label"], body["added"], body["removed"]) == (
        "shown",
        "previous",
        "2.4.1",
        2,
        1,
    )
    lines = [line for h in body["hunks"] for line in h["lines"]]
    marked = [(line["new_line"], line["text"]) for line in lines if line["marked"]]
    assert marked == [(11, "socket.create_connection(('example.net', 443))")]
    assert body["signals"] == ["behavior.network"]


@pytest.mark.integration
def test_diff_against_source(client: TestClient) -> None:
    """``base=source`` diffs the package file with its path in the tag."""
    body = client.get(URL + "orbit/sync.py", params={"base": "source"}).json()
    assert (body["diff"], body["base_label"], body["old_path"]) == ("shown", "tag v2.5.0", "src/orbit/sync.py")
    assert (body["added"], body["removed"]) == (2, 1)
    assert client.get(URL + "orbit/same.py", params={"base": "source"}).status_code == 404


@pytest.mark.integration
def test_metadata_only_cases(client: TestClient) -> None:
    """Binary files, identical contents and contents not kept return metadata without hunks."""
    binary = client.get(URL + "orbit/_fast.so").json()
    assert (binary["diff"], binary["hunks"], binary["text"]) == ("binary", [], False)
    assert client.get(URL + "orbit/same.py").json()["diff"] == "identical"
    assert client.get(URL + "orbit/lost.py").json()["diff"] == "unavailable"
    assert client.get(URL + "orbit/missing.py").status_code == 404


@pytest.mark.integration
def test_unanalyzed_pair_is_404(client: TestClient) -> None:
    """A file diff needs the pair's analysis first."""
    assert client.get("/api/pypi/orbit-client/2.4.1...2.5.0/files/x.py", params={"kind": "sdist"}).status_code == 404
