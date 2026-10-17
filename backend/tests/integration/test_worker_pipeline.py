"""The full analysis pipeline against Postgres, with PyPI, the Integrity API and GitHub intercepted by respx.

The package, its releases, its repository and every file are invented.
"""

import hashlib
import io
import json
import tarfile
import zipfile
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sightglass.db import models
from sightglass.ecosystems.github import GITHUB_HOSTS, GitHubClient
from sightglass.ecosystems.http import Fetcher, default_client
from sightglass.ecosystems.provenance import IntegrityClient
from sightglass.ecosystems.pypi import PYPI_HOSTS, PypiClient
from sightglass.storage.blobs import LocalBlobStore
from sightglass.worker.pipeline import PipelineError, Services, TransientError, analyze_release_pair

COMMIT = "0123456789abcdef0123456789abcdef01234567"
NOW = datetime(2026, 10, 3, tzinfo=UTC)
FILES_URL = "https://files.pythonhosted.org/packages"
INIT_OLD = b'"""Orbit client."""\n\nVERSION = "2.4.1"\n'
INIT_NEW = b'"""Orbit client."""\n\nVERSION = "2.5.0"\n'
TELEMETRY = b"import requests\n\n\ndef ping():\n    requests.post('https://telemetry.example.net/v1', json={})\n"


def metadata(version: str, *requires: str) -> bytes:
    """Core metadata for orbit-client."""
    lines = [f"Metadata-Version: 2.4\nName: orbit-client\nVersion: {version}\n"]
    lines += [f"Requires-Dist: {r}\n" for r in requires]
    return "".join(lines).encode()


def wheel(version: str, files: dict[str, bytes], requires: tuple[str, ...] = ()) -> bytes:
    """A pure-Python wheel."""
    info = f"orbit_client-{version}.dist-info"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
        zf.writestr(f"{info}/METADATA", metadata(version, *requires))
        zf.writestr(f"{info}/WHEEL", "Wheel-Version: 1.0\nGenerator: hatchling 1.27.0\nTag: py3-none-any\n")
        zf.writestr(f"{info}/RECORD", "")
    return buf.getvalue()


def tarball(prefix: str, files: dict[str, bytes]) -> bytes:
    """A .tar.gz with every file under ``prefix``."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files.items():
            entry = tarfile.TarInfo(prefix + name)
            entry.size = len(data)
            tf.addfile(entry, io.BytesIO(data))
    return buf.getvalue()


PYPROJECT = b'[project]\nname = "orbit-client"\n[build-system]\nbuild-backend = "hatchling.build"\n'


def sdist(version: str, files: dict[str, bytes]) -> bytes:
    """An sdist with PKG-INFO and pyproject.toml."""
    content = {"PKG-INFO": metadata(version), "pyproject.toml": PYPROJECT, **files}
    return tarball(f"orbit_client-{version}/", content)


OLD_FILES = {"orbit/__init__.py": INIT_OLD}
NEW_FILES = {"orbit/__init__.py": INIT_NEW, "orbit/telemetry.py": TELEMETRY}
ARTIFACTS = {
    "orbit_client-2.4.1-py3-none-any.whl": wheel("2.4.1", OLD_FILES, ("httpx>=0.27",)),
    "orbit_client-2.4.1.tar.gz": sdist("2.4.1", {"src/" + k: v for k, v in OLD_FILES.items()}),
    "orbit_client-2.5.0-py3-none-any.whl": wheel("2.5.0", NEW_FILES, ("httpx>=0.27", "requests>=2.32")),
    "orbit_client-2.5.0.tar.gz": sdist("2.5.0", {"src/orbit/__init__.py": INIT_NEW}),
}
TAG_ARCHIVE = tarball(f"orbit-client-{COMMIT}/", {"src/orbit/__init__.py": INIT_NEW, "pyproject.toml": PYPROJECT})


def project_json(artifacts: dict[str, bytes] = ARTIFACTS) -> bytes:
    """The JSON API response for the invented project."""
    releases: dict[str, list[dict[str, Any]]] = {}
    for name, data in artifacts.items():
        version = name.split("-")[1].removesuffix(".tar.gz")
        releases.setdefault(version, []).append(
            {
                "filename": name,
                "url": f"{FILES_URL}/{name}",
                "digests": {"sha256": hashlib.sha256(data).hexdigest()},
                "size": len(data),
                "upload_time_iso_8601": "2026-09-01T00:00:00Z" if "2.4.1" in name else "2026-10-01T00:00:00Z",
                "packagetype": "bdist_wheel" if name.endswith(".whl") else "sdist",
            }
        )
    info = {"name": "orbit-client", "project_urls": {"Source": "https://github.com/kestrel-weather/orbit-client"}}
    return json.dumps({"info": info, "releases": releases}).encode()


def refs() -> bytes:
    """A ref advertisement with tag v2.5.0 at COMMIT."""

    def pkt(line: str) -> bytes:
        return f"{len(line.encode()) + 4:04x}".encode() + line.encode()

    return pkt("# service=git-upload-pack\n") + b"0000" + pkt(f"{COMMIT} refs/tags/v2.5.0\n") + b"0000"


@pytest.fixture
def services(tmp_path: Path) -> Iterator[Services]:
    """Real clients that don't wait between retries, with caches under tmp_path."""
    clients = [default_client() for _ in range(3)]
    sleep: Callable[[float], None] = lambda _: None  # noqa: E731
    yield Services(
        pypi=PypiClient(Fetcher(clients[0], PYPI_HOSTS, max_attempts=2, sleep=sleep)),
        integrity=IntegrityClient(Fetcher(clients[1], PYPI_HOSTS, max_attempts=2, sleep=sleep)),
        github=GitHubClient(Fetcher(clients[2], GITHUB_HOSTS, max_attempts=2, sleep=sleep)),
        blobs=LocalBlobStore(tmp_path / "blobs"),
        cache_dir=tmp_path / "cache",
    )
    for c in clients:
        c.close()


def mock_world(provenance_payload: Callable[..., bytes], *, attested_old: bool = True) -> dict[str, respx.Route]:
    """Routes for the project, its files, provenance (2.4.1 wheel attested, everything else not) and GitHub."""
    routes = {"project": respx.get("https://pypi.org/pypi/orbit-client/json").respond(200, content=project_json())}
    for name, data in ARTIFACTS.items():
        routes[name] = respx.get(f"{FILES_URL}/{name}").respond(200, content=data)
    sha_old = hashlib.sha256(ARTIFACTS["orbit_client-2.4.1-py3-none-any.whl"]).hexdigest()
    integrity = "https://pypi.org/integrity/orbit-client"
    old_wheel = respx.get(f"{integrity}/2.4.1/orbit_client-2.4.1-py3-none-any.whl/provenance")
    if attested_old:
        old_wheel.respond(200, content=provenance_payload(sha256=sha_old))
    else:
        old_wheel.respond(404)
    respx.get(url__startswith=integrity).respond(404)
    routes["refs"] = respx.get(
        "https://github.com/kestrel-weather/orbit-client.git/info/refs?service=git-upload-pack"
    ).respond(200, content=refs())
    routes["archive"] = respx.get(f"https://codeload.github.com/kestrel-weather/orbit-client/tar.gz/{COMMIT}").respond(
        200, content=TAG_ARCHIVE
    )
    return routes


def rule_ids(result: Any) -> set[str]:
    """The rule ids among a pair result's signals."""
    return {s["rule_id"] for s in result.signals}


@pytest.mark.integration
@respx.mock
def test_full_pipeline(db_session: Session, services: Services, provenance_payload: Callable[..., bytes]) -> None:
    """Both pairs are analyzed end to end, stored with their files and source, and report what changed."""
    routes = mock_world(provenance_payload)
    results = analyze_release_pair(db_session, services, "Orbit_Client", "2.4.1", "2.5.0", now=NOW)

    assert [(r.kind, r.status, r.cached) for r in results] == [("sdist", "done", False), ("wheel", "done", False)]
    wheel_result = results[1]
    assert {
        "provenance.attestation_dropped",
        "behavior.network",
        "source.not_in_tag",
        "source.not_in_sdist",
        "dependencies.added",
        "timing.recent",
    } <= rule_ids(wheel_result)
    network = next(s for s in wheel_result.signals if s["rule_id"] == "behavior.network")
    assert network["evidence"]["items"][0] == {
        "file": "orbit/telemetry.py",
        "line_start": 5,
        "line_end": 5,
        "side": "new",
    }
    assert "source.not_in_tag" not in rule_ids(results[0])

    assert db_session.scalar(select(func.count()).select_from(models.Analysis)) == 2
    snapshot = db_session.scalars(select(models.SourceSnapshot)).one()
    assert (snapshot.origin, snapshot.ref, snapshot.tag_pattern) == ("tag", "refs/tags/v2.5.0", "v{version}")
    source_files = db_session.scalars(
        select(models.File.path).where(models.File.source_snapshot_id == snapshot.id).order_by(models.File.path)
    )
    assert list(source_files) == [
        f"orbit-client-{COMMIT}/pyproject.toml",
        f"orbit-client-{COMMIT}/src/orbit/__init__.py",
    ]
    artifact = db_session.scalars(
        select(models.Artifact).where(models.Artifact.filename.endswith("2.4.1-py3-none-any.whl"))
    ).one()
    assert artifact.provenance_status == "present"
    assert (
        db_session.scalar(select(func.count()).select_from(models.File).where(models.File.artifact_id == artifact.id))
        == 4
    )
    assert services.blobs.read(hashlib.sha256(TELEMETRY).hexdigest()) == TELEMETRY
    assert routes["orbit_client-2.5.0.tar.gz"].call_count == 1

    report = db_session.get(models.Analysis, wheel_result.analysis_id).report  # type: ignore[union-attr]
    assert report is not None
    assert {f["path"]: f["status"] for f in report["files"]}["orbit/telemetry.py"] == "added"
    assert (report["source"]["state"], report["source"]["label"], report["source"]["commit"]) == (
        "compared",
        "tag v2.5.0",
        COMMIT,
    )
    assert {c["path"]: c["status"] for c in report["source"]["files"]}["orbit/telemetry.py"] == "missing"
    assert report["sdist"]["root"] == "src/"
    facts = report["facts"]
    assert (facts["old"]["attestation"], facts["new"]["attestation"]) == ("present", "absent")
    assert facts["old"]["publisher"]["workflow"] == "release.yml" and facts["new"]["publisher"] is None
    assert facts["new"]["build_tool"] == "hatchling"
    assert facts["new"]["requires_dist"] == ["httpx>=0.27", "requests>=2.32"]
    assert facts["new"]["file_count"] == 5 and facts["new"]["total_size"] > 0


@pytest.mark.integration
@respx.mock
def test_second_run_is_cached(
    db_session: Session, services: Services, provenance_payload: Callable[..., bytes]
) -> None:
    """A pair already analyzed under this rule set is returned from the database without downloads."""
    routes = mock_world(provenance_payload)
    first = analyze_release_pair(db_session, services, "orbit-client", "2.4.1", "2.5.0", now=NOW)
    downloads = sum(routes[name].call_count for name in ARTIFACTS)
    second = analyze_release_pair(db_session, services, "orbit-client", "2.4.1", "2.5.0", now=NOW)

    assert [r.cached for r in second] == [True, True]
    assert [r.signals for r in second] == [r.signals for r in first]
    assert sum(routes[name].call_count for name in ARTIFACTS) == downloads


@pytest.mark.integration
@respx.mock
def test_downloads_are_reused_across_rule_sets(
    db_session: Session, services: Services, provenance_payload: Callable[..., bytes]
) -> None:
    """A new rule set reruns the rules but reuses the verified downloads and the source archive."""
    from sightglass.rules.base import RuleSet

    routes = mock_world(provenance_payload)
    analyze_release_pair(db_session, services, "orbit-client", "2.4.1", "2.5.0", now=NOW)
    results = analyze_release_pair(db_session, services, "orbit-client", "2.4.1", "2.5.0", now=NOW, rules=RuleSet())
    assert [(r.cached, r.signals) for r in results] == [(False, ()), (False, ())]
    assert all(routes[name].call_count == 1 for name in ARTIFACTS)
    assert routes["archive"].call_count == 1


@pytest.mark.integration
@respx.mock
def test_corrupt_artifact_is_a_recorded_failure(
    db_session: Session, services: Services, provenance_payload: Callable[..., bytes]
) -> None:
    """A download that doesn't match the index fails that pair with a reason; the wheel pair runs without it."""
    routes = mock_world(provenance_payload)
    routes["orbit_client-2.5.0.tar.gz"].respond(200, content=b"x" * len(ARTIFACTS["orbit_client-2.5.0.tar.gz"]))
    sdist_result, wheel_result = analyze_release_pair(db_session, services, "orbit-client", "2.4.1", "2.5.0", now=NOW)

    assert sdist_result.status == "failed" and "ArtifactIntegrityError" in (sdist_result.error or "")
    row = db_session.get(models.Analysis, sdist_result.analysis_id)
    assert row is not None and row.status == "failed" and row.error == sdist_result.error
    assert wheel_result.status == "done" and "source.not_in_sdist" not in rule_ids(wheel_result)


@pytest.mark.integration
@respx.mock
def test_unreachable_repository_is_retried_until_the_last_attempt(
    db_session: Session, services: Services, provenance_payload: Callable[..., bytes]
) -> None:
    """GitHub being down raises a transient error, except on the last attempt, which stores "couldn't compare"."""
    routes = mock_world(provenance_payload, attested_old=False)
    routes["refs"].mock(return_value=httpx.Response(503))
    with pytest.raises(TransientError):
        analyze_release_pair(db_session, services, "orbit-client", "2.4.1", "2.5.0", now=NOW, final_attempt=False)
    results = analyze_release_pair(db_session, services, "orbit-client", "2.4.1", "2.5.0", now=NOW)
    assert [r.status for r in results] == ["done", "done"]
    assert "source.not_in_tag" not in rule_ids(results[1])


@pytest.mark.integration
@respx.mock
def test_unresolvable_requests(db_session: Session, services: Services) -> None:
    """Unknown packages and versions are pipeline errors; an index outage is transient."""
    respx.get("https://pypi.org/pypi/orbit-client/json").respond(200, content=project_json())
    respx.get("https://pypi.org/pypi/tidepool/json").respond(404)
    respx.get("https://pypi.org/pypi/kestrel/json").respond(503)
    with pytest.raises(PipelineError, match="release_not_found"):
        analyze_release_pair(db_session, services, "orbit-client", "2.4.1", "9.9.9")
    with pytest.raises(PipelineError, match="package_not_found"):
        analyze_release_pair(db_session, services, "tidepool", "1.0", "1.1")
    with pytest.raises(TransientError):
        analyze_release_pair(db_session, services, "kestrel", "1.0", "1.1")
    wheel_only = {k: v for k, v in ARTIFACTS.items() if "2.5.0" not in k or k.endswith(".tar.gz")}
    wheel_only = {k: v for k, v in wheel_only.items() if not (k.endswith(".tar.gz") and "2.4.1" in k)}
    respx.get("https://pypi.org/pypi/gale/json").respond(200, content=project_json(wheel_only))
    with pytest.raises(PipelineError, match="nothing_to_compare"):
        analyze_release_pair(db_session, services, "gale", "2.4.1", "2.5.0")


@pytest.mark.integration
@respx.mock
def test_a_chosen_wheel_only(db_session: Session, services: Services, provenance_payload: Callable[..., bytes]) -> None:
    """With a wheel named, only that pair is analyzed; an unknown wheel is a pipeline error."""
    mock_world(provenance_payload)
    [result] = analyze_release_pair(
        db_session, services, "orbit-client", "2.4.1", "2.5.0", now=NOW, wheel="orbit_client-2.5.0-py3-none-any.whl"
    )
    assert (result.kind, result.status) == ("wheel", "done")
    with pytest.raises(PipelineError, match="artifact_not_found"):
        analyze_release_pair(db_session, services, "orbit-client", "2.4.1", "2.5.0", wheel="nope.whl")


@pytest.mark.integration
@respx.mock
def test_build_only_attested_repository_falls_back_to_the_listed_one(
    db_session: Session, services: Services, provenance_payload: Callable[..., bytes]
) -> None:
    """A release built in a separate repository that lacks the code is compared with the project's listed one."""
    release_commit = "f" * 40
    claims = {
        "9": "https://github.com/kestrel-weather/orbit-release/.github/workflows/wheels.yml@refs/heads/main",
        "11": "github-hosted",
        "12": "https://github.com/kestrel-weather/orbit-release",
        "13": release_commit,
        "14": "refs/heads/main",
        "20": "push",
        "21": "https://github.com/kestrel-weather/orbit-release/actions/runs/7/attempts/1",
    }
    sha_new = hashlib.sha256(ARTIFACTS["orbit_client-2.5.0-py3-none-any.whl"]).hexdigest()
    respx.get("https://pypi.org/integrity/orbit-client/2.5.0/orbit_client-2.5.0-py3-none-any.whl/provenance").respond(
        200, content=provenance_payload(sha256=sha_new, claims=claims)
    )
    respx.get("https://github.com/kestrel-weather/orbit-release.git/info/refs?service=git-upload-pack").respond(404)
    respx.get(f"https://codeload.github.com/kestrel-weather/orbit-release/tar.gz/{release_commit}").respond(
        200, content=tarball(f"orbit-release-{release_commit}/", {".github/workflows/wheels.yml": b"on: push\n"})
    )
    mock_world(provenance_payload)

    [_, wheel_result] = analyze_release_pair(db_session, services, "orbit-client", "2.4.1", "2.5.0", now=NOW)

    report = db_session.get(models.Analysis, wheel_result.analysis_id).report  # type: ignore[union-attr]
    assert report is not None
    assert (report["source"]["label"], report["source"]["commit"]) == ("tag v2.5.0", COMMIT)
    repositories = set(db_session.scalars(select(models.SourceSnapshot.repository)))
    assert repositories == {"kestrel-weather/orbit-release", "kestrel-weather/orbit-client"}


@pytest.mark.integration
@respx.mock
def test_tag_with_an_unbumped_version_is_a_note(
    db_session: Session, services: Services, provenance_payload: Callable[..., bytes]
) -> None:
    """A tag whose version string wasn't bumped differs from the package only in that value: a note, not high."""
    mock_world(provenance_payload)
    respx.get(f"https://codeload.github.com/kestrel-weather/orbit-client/tar.gz/{COMMIT}").respond(
        200,
        content=tarball(f"orbit-client-{COMMIT}/", {"src/orbit/__init__.py": INIT_OLD, "pyproject.toml": PYPROJECT}),
    )
    [sdist_result, _] = analyze_release_pair(db_session, services, "orbit-client", "2.4.1", "2.5.0", now=NOW)

    [signal] = [s for s in sdist_result.signals if s["rule_id"] == "source.differs_from_tag"]
    assert signal["level"] == "note"
    assert signal["message"].endswith("(the same code apart from comments, formatting or the version)")


@pytest.mark.integration
@respx.mock
def test_source_that_cannot_be_written_out_is_couldnt_compare(
    db_session: Session, services: Services, provenance_payload: Callable[..., bytes]
) -> None:
    """A source tree with a path too long for the file system leaves the release analyzed, without a comparison."""
    mock_world(provenance_payload)
    long_name = "src/orbit/" + "n" * 300 + ".py"
    respx.get(f"https://codeload.github.com/kestrel-weather/orbit-client/tar.gz/{COMMIT}").respond(
        200, content=tarball(f"orbit-client-{COMMIT}/", {"src/orbit/__init__.py": INIT_NEW, long_name: b"x = 1\n"})
    )
    results = analyze_release_pair(db_session, services, "orbit-client", "2.4.1", "2.5.0", now=NOW)

    assert [r.status for r in results] == ["done", "done"]
    for result in results:
        report = db_session.get(models.Analysis, result.analysis_id).report  # type: ignore[union-attr]
        assert report is not None
        assert report["source"]["state"] == "could_not_compare"
        assert report["source"]["reason"] == "archive_unreadable"
        assert "too long" in report["source"]["detail"]
