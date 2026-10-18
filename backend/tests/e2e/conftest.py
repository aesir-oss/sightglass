"""The app as a browser sees it: Postgres, the API serving the built frontend, and PyPI and GitHub replayed by respx.

Everything runs in this process. uvicorn serves on a free port in a thread; respx intercepts the server's outbound
httpx requests and answers with an invented package. Analyses the page queues are recorded, and a test runs them
with :meth:`Live.run_queued` to move a pair from pending to done.
"""

import hashlib
import io
import json
import socket
import tarfile
import threading
import time
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import respx
import uvicorn
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from sightglass.api.app import create_app
from sightglass.api.deps import Index, get_blobs, get_enqueue, get_index, get_session
from sightglass.db.engine import make_engine
from sightglass.db.local import LocalPostgres
from sightglass.db.migrate import upgrade
from sightglass.ecosystems.github import GITHUB_HOSTS, GitHubClient
from sightglass.ecosystems.http import Fetcher, default_client
from sightglass.ecosystems.provenance import IntegrityClient
from sightglass.ecosystems.pypi import PYPI_HOSTS, PypiClient
from sightglass.storage.blobs import LocalBlobStore
from sightglass.worker.pipeline import Services, analyze_release_pair

REPO_ROOT = Path(__file__).resolve().parents[3]
AXE = REPO_ROOT / "frontend" / "node_modules" / "axe-core" / "axe.min.js"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
FILES_URL = "https://files.pythonhosted.org/packages"

INIT_OLD = b'"""Orbit client."""\n\nVERSION = "2.4.1"\n'
INIT_NEW = b'"""Orbit client."""\n\nVERSION = "2.5.0"\n'
TELEMETRY = b"import requests\n\n\ndef ping():\n    requests.post('https://telemetry.example.net/v1', json={})\n"
PYPROJECT = b'[project]\nname = "orbit-client"\n[build-system]\nbuild-backend = "hatchling.build"\n'


def _metadata(version: str, *requires: str) -> bytes:
    lines = [f"Metadata-Version: 2.4\nName: orbit-client\nVersion: {version}\n"]
    return "".join(lines + [f"Requires-Dist: {r}\n" for r in requires]).encode()


def _wheel(version: str, files: dict[str, bytes], requires: tuple[str, ...]) -> bytes:
    info = f"orbit_client-{version}.dist-info"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
        zf.writestr(f"{info}/METADATA", _metadata(version, *requires))
        zf.writestr(f"{info}/WHEEL", "Wheel-Version: 1.0\nGenerator: hatchling 1.27.0\nTag: py3-none-any\n")
        zf.writestr(f"{info}/RECORD", "")
    return buf.getvalue()


def _tarball(prefix: str, files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files.items():
            entry = tarfile.TarInfo(prefix + name)
            entry.size = len(data)
            tf.addfile(entry, io.BytesIO(data))
    return buf.getvalue()


def _sdist(version: str, files: dict[str, bytes]) -> bytes:
    return _tarball(f"orbit_client-{version}/", {"PKG-INFO": _metadata(version), "pyproject.toml": PYPROJECT, **files})


ARTIFACTS = {
    "orbit_client-2.4.1-py3-none-any.whl": _wheel("2.4.1", {"orbit/__init__.py": INIT_OLD}, ("httpx>=0.27",)),
    "orbit_client-2.4.1.tar.gz": _sdist("2.4.1", {"src/orbit/__init__.py": INIT_OLD}),
    "orbit_client-2.5.0-py3-none-any.whl": _wheel(
        "2.5.0", {"orbit/__init__.py": INIT_NEW, "orbit/telemetry.py": TELEMETRY}, ("httpx>=0.27", "requests>=2.32")
    ),
    "orbit_client-2.5.0.tar.gz": _sdist("2.5.0", {"src/orbit/__init__.py": INIT_NEW}),
    "orbit_client-2.6.0-py3-none-any.whl": _wheel("2.6.0", {"orbit/__init__.py": INIT_NEW}, ()),
    # Served with different bytes than the index lists, so analyzing it fails.
    "orbit_client-2.7.0-py3-none-any.whl": _wheel("2.7.0", {"orbit/__init__.py": INIT_NEW}, ()),
}
CORRUPT = "orbit_client-2.7.0-py3-none-any.whl"
TAG_ARCHIVE = _tarball(f"orbit-client-{COMMIT}/", {"src/orbit/__init__.py": INIT_NEW, "pyproject.toml": PYPROJECT})
DATES = {"2.4.1": "2026-06-01", "2.5.0": "2026-09-01", "2.6.0": "2026-10-01", "2.7.0": "2026-10-10"}


def _project_json() -> bytes:
    releases: dict[str, list[dict[str, Any]]] = {}
    for name, data in ARTIFACTS.items():
        version = name.split("-")[1].removesuffix(".tar.gz")
        releases.setdefault(version, []).append(
            {
                "filename": name,
                "url": f"{FILES_URL}/{name}",
                "digests": {"sha256": hashlib.sha256(data).hexdigest()},
                "size": len(data),
                "upload_time_iso_8601": f"{DATES[version]}T00:00:00Z",
                "packagetype": "bdist_wheel" if name.endswith(".whl") else "sdist",
            }
        )
    info = {"name": "orbit-client", "project_urls": {"Source": "https://github.com/kestrel-weather/orbit-client"}}
    return json.dumps({"info": info, "releases": releases}).encode()


def _refs() -> bytes:
    def pkt(line: str) -> bytes:
        return f"{len(line.encode()) + 4:04x}".encode() + line.encode()

    return pkt("# service=git-upload-pack\n") + b"0000" + pkt(f"{COMMIT} refs/tags/v2.5.0\n") + b"0000"


# An invented package with a long history, for the timeline: one wheel per release, about every two weeks.
LONGHAUL_RELEASES = 150


def _longhaul_json() -> bytes:
    releases = {}
    for i in range(LONGHAUL_RELEASES):
        name = f"longhaul-1.0.{i}-py3-none-any.whl"
        published = datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=14 * i)
        releases[f"1.0.{i}"] = [
            {
                "filename": name,
                "url": f"{FILES_URL}/{name}",
                "digests": {"sha256": "0" * 64},
                "size": 1,
                "upload_time_iso_8601": published.isoformat().replace("+00:00", "Z"),
                "packagetype": "bdist_wheel",
            }
        ]
    return json.dumps({"info": {"name": "longhaul", "project_urls": {}}, "releases": releases}).encode()


def _mock_index(router: respx.Router) -> None:
    router.get("https://pypi.org/pypi/orbit-client/json").respond(200, content=_project_json())
    router.get("https://pypi.org/simple/orbit-client/").respond(
        200, content=json.dumps({"files": [{"filename": n, "provenance": None} for n in ARTIFACTS]}).encode()
    )
    router.get(url__startswith="https://pypi.org/integrity/").respond(404)
    router.get("https://pypi.org/pypi/tidepool/json").respond(404)
    router.get("https://pypi.org/pypi/longhaul/json").respond(200, content=_longhaul_json())
    router.get("https://pypi.org/simple/longhaul/").respond(200, content=json.dumps({"files": []}).encode())
    for name, data in ARTIFACTS.items():
        served = bytes(len(data)) if name == CORRUPT else data
        router.get(f"{FILES_URL}/{name}").respond(200, content=served)
    router.get("https://github.com/kestrel-weather/orbit-client.git/info/refs?service=git-upload-pack").respond(
        200, content=_refs()
    )
    router.get(f"https://codeload.github.com/kestrel-weather/orbit-client/tar.gz/{COMMIT}").respond(
        200, content=TAG_ARCHIVE
    )


@dataclass
class Live:
    """The running app and what it queued."""

    url: str
    engine: Engine
    services: Services
    queued: list[tuple[Any, ...]] = field(default_factory=list)

    def run_queued(self) -> None:
        """Run every queued analysis, as a worker would."""
        while self.queued:
            _, package, from_version, to_version, wheel = self.queued.pop(0)
            with Session(self.engine) as session:
                analyze_release_pair(session, self.services, package, from_version, to_version, wheel=wheel)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


@pytest.fixture(scope="session")
def live(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Live]:
    """Start Postgres and the app for the session, with the invented package's 2.4.1...2.5.0 already analyzed."""
    if not (REPO_ROOT / "frontend" / "dist" / "index.html").is_file():
        pytest.fail("frontend/dist isn't built; run the browser tests with `pixi run test-e2e`")
    tmp = tmp_path_factory.mktemp("e2e")
    postgres = LocalPostgres(tmp / "pg")
    postgres.start()
    url = postgres.create_database("e2e")
    upgrade(url)
    engine = make_engine(url)

    router = respx.mock(assert_all_called=False)
    router.start()
    _mock_index(router)
    clients = [default_client() for _ in range(3)]
    no_wait: Callable[[float], None] = lambda _: None  # noqa: E731
    services = Services(
        pypi=PypiClient(Fetcher(clients[0], PYPI_HOSTS, max_attempts=1, sleep=no_wait)),
        integrity=IntegrityClient(Fetcher(clients[1], PYPI_HOSTS, max_attempts=1, sleep=no_wait)),
        github=GitHubClient(Fetcher(clients[2], GITHUB_HOSTS, max_attempts=1, sleep=no_wait)),
        blobs=LocalBlobStore(tmp / "blobs"),
        cache_dir=tmp / "cache",
    )
    state = Live(url="", engine=engine, services=services)

    def session_dep() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    def enqueue(*args: Any) -> int | None:
        # Like procrastinate's queueing lock: a pair already waiting isn't queued twice.
        if args in state.queued:
            return None
        state.queued.append(args)
        return len(state.queued)

    app = create_app()
    app.dependency_overrides[get_session] = session_dep
    app.dependency_overrides[get_index] = lambda: Index(services.pypi, services.integrity)
    app.dependency_overrides[get_blobs] = lambda: services.blobs
    app.dependency_overrides[get_enqueue] = lambda: enqueue

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            pytest.fail("the app didn't start")
        time.sleep(0.05)
    state.url = f"http://127.0.0.1:{port}"

    with Session(engine) as session:
        analyze_release_pair(session, services, "orbit-client", "2.4.1", "2.5.0")
    yield state

    server.should_exit = True
    thread.join(timeout=10)
    for c in clients:
        c.close()
    router.stop()
    engine.dispose()
    postgres.stop()


@pytest.fixture(scope="session")
def base_url(live: Live) -> str:
    """Pages are opened relative to the running app."""
    return live.url


@pytest.fixture
def axe() -> Callable[[Any], list[dict[str, Any]]]:
    """Run axe-core's WCAG 2.1 A and AA rules on a page and return the violations."""

    def run(page: Any) -> list[dict[str, Any]]:
        page.add_script_tag(path=str(AXE))
        violations: list[dict[str, Any]] = page.evaluate(
            """async () => (await axe.run(document, {runOnly: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]}))
                .violations.map(v => ({id: v.id, help: v.help, nodes: v.nodes.map(n => n.target.join(" "))}))"""
        )
        return violations

    return run
