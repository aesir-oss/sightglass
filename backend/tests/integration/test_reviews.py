"""Reviewing a lockfile change: the shared review flow, the review API and the local command."""

import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from sightglass import review as review_command
from sightglass.api.app import create_app
from sightglass.api.deps import get_session
from sightglass.db import models
from sightglass.db.local import LocalPostgres
from sightglass.db.migrate import upgrade
from sightglass.ecosystems.http import NotFoundError
from sightglass.ecosystems.pypi import PypiFile, PypiProject, PypiRelease
from sightglass.lockfiles.pixi import LockfileError
from sightglass.lockfiles.review import Snapshot, manifest_names, parse_lockfile, review_lockfile
from sightglass.rules.ruleset import RULES

FIXTURES = Path(__file__).parents[1] / "fixtures" / "lockfiles"
BASE_LOCK = (FIXTURES / "uv.lock").read_bytes()
# The head moves kestrel to 1.5.0, adds gale to orbit-core and drops the probe dev dependency.
HEAD_LOCK = (
    BASE_LOCK.replace(b'version = "1.4.0"', b'version = "1.5.0"')
    .replace(b"kestrel-1.4.0", b"kestrel-1.5.0")
    .replace(b'    { name = "tinted", marker', b'    { name = "gale" },\n    { name = "tinted", marker')
    .replace(b'dev = [{ name = "probe" }]', b"dev = []")
    + b'\n[[package]]\nname = "gale"\nversion = "1.0.0"\nsource = { registry = "https://pypi.org/simple" }\n'
    b'wheels = [{ url = "https://files.example/gale-1.0.0-py3-none-any.whl", hash = "sha256:44" }]\n'
)
BASE_SHA, HEAD_SHA = "a" * 40, "b" * 40


def release(version: str, month: int) -> PypiRelease:
    """A release with one file."""
    f = PypiFile(
        f"g-{version}.whl", "https://x", "0" * 64, 1, datetime(2026, month, 1, tzinfo=UTC), "wheel", False, None, None
    )
    return PypiRelease(version, (f,))


class FakePypi:
    """An index that knows gale's releases and nothing else."""

    def project(self, name: str) -> PypiProject:
        """Gale's project, or not found."""
        if name != "gale":
            raise NotFoundError(f"{name} not found")
        return PypiProject("gale", "gale", {}, None, None, (release("0.9.0", 1), release("1.0.0", 2)))


def run_review(session: Session, queued: list[tuple[str, ...]], head: bytes = HEAD_LOCK) -> int:
    """Review the fixture's uv.lock change for kestrel-weather/orbit#7."""
    return review_lockfile(
        session,
        pypi=FakePypi(),  # type: ignore[arg-type]
        enqueue=lambda *args: queued.append(args),
        repository="kestrel-weather/orbit",
        pull_number=7,
        base_sha=BASE_SHA,
        head_sha=HEAD_SHA,
        lockfile_path="uv.lock",
        base=Snapshot(BASE_LOCK),
        head=Snapshot(head),
    )


@pytest.mark.integration
def test_review_records_changes_and_queues_pypi_analyses(db_session: Session) -> None:
    """Changed packages are analyzed against their old version, added ones against their predecessor."""
    queued: list[tuple[str, ...]] = []
    review_id = run_review(db_session, queued)
    rows = db_session.query(models.ReviewChange).filter_by(review_id=review_id).all()
    assert {(r.package, r.kind, r.compare_from) for r in rows} == {
        ("gale", "added", "0.9.0"),
        ("kestrel", "changed", "1.4.0"),
        ("probe", "removed", "8.0.0"),
    }
    assert sorted(queued) == [("pypi", "gale", "0.9.0", "1.0.0"), ("pypi", "kestrel", "1.4.0", "1.5.0")]


@pytest.mark.integration
def test_lockfile_names_and_manifests() -> None:
    """Lockfiles are parsed by name; pixi lockfiles look for a manifest beside them, uv ones don't."""
    assert parse_lockfile("app/uv.lock", BASE_LOCK).format == "uv.lock"
    with pytest.raises(LockfileError, match="isn't a supported lockfile"):
        parse_lockfile("poetry.lock", b"")
    assert manifest_names("services/api/pixi.lock") == ["services/api/pixi.toml", "services/api/pyproject.toml"]
    assert manifest_names("pixi.lock") == ["pixi.toml", "pyproject.toml"]
    assert manifest_names("uv.lock") == []


def seed_analysis(session: Session, package: str, old: str, new: str, status: str, *levels: str) -> None:
    """An analysis of package old -> new under the current rule set, with signals at ``levels``."""
    pkg = models.Package(ecosystem="pypi", name=package, display_name=package)
    artifacts = []
    for version in (old, new):
        rel = models.Release(package=pkg, version=version)
        art = models.Artifact(release=rel, filename=f"{package}-{version}.whl", kind="wheel", sha256="c" * 64, size=1)
        artifacts.append(art)
    session.add_all(artifacts)
    session.flush()
    analysis = models.Analysis(
        from_artifact_id=artifacts[0].id,
        to_artifact_id=artifacts[1].id,
        ruleset_version=RULES.version,
        status=status,
        error="boom" if status == "failed" else None,
    )
    session.add(analysis)
    session.flush()
    session.add_all(
        models.Signal(analysis_id=analysis.id, rule_id="source.not_in_tag", level=lv, message="m", evidence={})
        for lv in levels
    )
    session.flush()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    """The API on the test session."""
    app = create_app(serve_frontend=False)
    app.dependency_overrides[get_session] = lambda: db_session
    yield TestClient(app)


@pytest.mark.integration
def test_review_api_orders_what_needs_a_look_first(db_session: Session, client: TestClient) -> None:
    """High signals first, then what's analyzing, then the rest; each change carries its analysis state."""
    run_review(db_session, [])
    seed_analysis(db_session, "kestrel", "1.4.0", "1.5.0", "done", "high", "check", "note")
    response = client.get("/api/reviews/kestrel-weather/orbit/7")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    body: dict[str, Any] = response.json()
    assert (body["repository"], body["number"], body["lockfile_path"]) == ("kestrel-weather/orbit", 7, "uv.lock")
    assert body["platforms"] == ["linux-64", "osx-arm64", "win-64"]
    order = [(c["package"], c["analysis"]["state"], c["analysis"]["level"]) for c in body["changes"]]
    assert order == [("kestrel", "done", "high"), ("gale", "pending", None), ("probe", "not_analyzed", None)]
    assert body["changes"][0]["analysis"]["counts"] == {"high": 1, "check": 1, "note": 1}
    # From the workspace's root project through its members.
    assert body["changes"][1]["path"] == ["orbit-platform", "orbit-cli", "orbit-core", "gale"]


@pytest.mark.integration
def test_review_api_failed_clean_and_missing(db_session: Session, client: TestClient) -> None:
    """A failed analysis says so, one with no signals is clean, and an unknown review is a 404."""
    run_review(db_session, [])
    seed_analysis(db_session, "kestrel", "1.4.0", "1.5.0", "failed")
    seed_analysis(db_session, "gale", "0.9.0", "1.0.0", "done")
    states = {c["package"]: c["analysis"] for c in client.get("/api/reviews/kestrel-weather/orbit/7").json()["changes"]}
    assert states["kestrel"]["state"] == "failed"
    assert (states["gale"]["state"], states["gale"]["level"]) == ("done", "clean")
    missing = client.get("/api/reviews/kestrel-weather/orbit/8")
    assert missing.status_code == 404 and missing.json()["detail"] == "no review of kestrel-weather/orbit#8"


def git(repo: Path, *args: str) -> None:
    """Run git in ``repo`` with a fixed identity."""
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )


@pytest.mark.integration
def test_review_command_reads_two_refs(
    postgres: LocalPostgres, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The command reads the lockfile at both refs of a checkout, records the review and queues the analyses."""
    repo = tmp_path / "orbit"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "uv.lock").write_bytes(BASE_LOCK)
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "checkout", "-q", "-b", "bump")
    (repo / "uv.lock").write_bytes(HEAD_LOCK)
    git(repo, "commit", "-q", "-am", "bump")

    url = postgres.create_database("review_command")
    upgrade(url)

    @contextmanager
    def database(cache: Path) -> Iterator[str]:
        yield url

    monkeypatch.setattr(review_command, "database", database)
    monkeypatch.setattr(review_command.PypiClient, "default", classmethod(lambda cls: FakePypi()))
    argv = ["kestrel-weather/orbit", "7", "main", "bump", "--checkout", str(repo), "--lockfile", "uv.lock"]
    assert review_command.main(argv) == 0
    assert review_command.main(["kestrel-weather/orbit", "7", "main", "nope", "--checkout", str(repo)]) == 1
    assert review_command.main(["orbit", "7", "main", "bump"]) == 2
    bad = ["kestrel-weather/orbit", "7", "main", "bump", "--checkout", str(repo), "--lockfile", "poetry.lock"]
    assert review_command.main(bad) == 1
