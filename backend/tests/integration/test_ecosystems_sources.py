"""Integration tests for fetching sources from GitHub (respx), unpacking them (Rust core) and recording them."""

import hashlib
import io
import tarfile
from collections.abc import Iterator
from pathlib import Path

import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sightglass import _core
from sightglass.db.models import Package
from sightglass.db.models import SourceSnapshot as SnapshotRow
from sightglass.ecosystems.github import GITHUB_HOSTS, ArchiveTooLargeError, GitHubClient, Repository
from sightglass.ecosystems.http import Fetcher, default_client
from sightglass.ecosystems.sources import (
    CouldNotCompare,
    SourceSnapshot,
    fetch_source,
    record_source_snapshot,
)

ORBIT = Repository("kestrel-weather", "orbit-client")
COMMIT = "0123456789abcdef0123456789abcdef01234567"
REFS_URL = "https://github.com/kestrel-weather/orbit-client.git/info/refs?service=git-upload-pack"
ARCHIVE_URL = f"https://codeload.github.com/kestrel-weather/orbit-client/tar.gz/{COMMIT}"


def pkt(line: str) -> bytes:
    """Encode one pkt-line."""
    return f"{len(line.encode()) + 4:04x}".encode() + line.encode()


def refs(**tags: str) -> bytes:
    """A ref advertisement listing ``tags`` (name to commit)."""
    body = pkt("# service=git-upload-pack\n") + b"0000" + pkt(f"{COMMIT} HEAD\0caps\n")
    return body + b"".join(pkt(f"{sha} refs/tags/{name}\n") for name, sha in tags.items()) + b"0000"


def tarball(files: dict[str, bytes], prefix: str = f"orbit-client-{COMMIT}/") -> bytes:
    """A GitHub-style .tar.gz with every file under one top-level directory."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(prefix + name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


SOURCE = tarball({"src/orbit/__init__.py": b"VERSION = '2.5.0'\n", "pyproject.toml": b"[project]\nname = 'orbit'\n"})


@pytest.fixture
def github() -> Iterator[GitHubClient]:
    """A GitHub client that doesn't wait between retries."""
    with default_client() as http:
        yield GitHubClient(Fetcher(http, GITHUB_HOSTS, max_attempts=2, sleep=lambda _: None))


@pytest.mark.integration
@respx.mock
def test_source_from_tag(github: GitHubClient) -> None:
    """The tag is found, its commit's archive downloaded and indexed, and paths made relative to the repo root."""
    respx.get(REFS_URL).respond(200, content=refs(**{"v2.4.1": "f" * 40, "v2.5.0": COMMIT}))
    respx.get(ARCHIVE_URL).respond(200, content=SOURCE)
    result = fetch_source(github, project="orbit-client", version="2.5.0", repository=ORBIT)

    assert isinstance(result, SourceSnapshot)
    assert (result.commit, result.ref, result.origin, result.tag_pattern) == (
        COMMIT,
        "refs/tags/v2.5.0",
        "tag",
        "v{version}",
    )
    assert result.archive_sha256 == hashlib.sha256(SOURCE).hexdigest()
    assert sorted(result.relative_path(e) for e in result.entries) == ["pyproject.toml", "src/orbit/__init__.py"]


@pytest.mark.integration
@respx.mock
def test_tag_comes_before_the_attested_commit(github: GitHubClient) -> None:
    """When the release's tag exists it is used, even with an attested commit: the workflow may have run elsewhere."""
    tagged = "c" * 40
    respx.get(REFS_URL).respond(200, content=refs(**{"v2.5.0": tagged}))
    respx.get(f"https://codeload.github.com/kestrel-weather/orbit-client/tar.gz/{tagged}").respond(
        200, content=tarball({"a.py": b"x"}, prefix=f"orbit-client-{tagged}/")
    )
    result = fetch_source(github, project="orbit-client", version="2.5.0", repository=ORBIT, attested_commit=COMMIT)
    assert isinstance(result, SourceSnapshot)
    assert (result.origin, result.commit, result.ref) == ("tag", tagged, "refs/tags/v2.5.0")


@pytest.mark.integration
@respx.mock
@pytest.mark.parametrize("refs_status", [200, 404, 503])
def test_attested_commit_when_no_tag_matches(github: GitHubClient, refs_status: int) -> None:
    """Without a matching tag, or when tags can't be listed, the attested commit is used."""
    respx.get(REFS_URL).respond(refs_status, content=refs(**{"v2.4.1": "f" * 40}) if refs_status == 200 else b"")
    respx.get(ARCHIVE_URL).respond(200, content=SOURCE)
    result = fetch_source(
        github,
        project="orbit-client",
        version="2.5.0",
        repository=ORBIT,
        attested_commit=COMMIT,
        attested_ref="refs/heads/main",
    )

    assert isinstance(result, SourceSnapshot)
    assert (result.origin, result.ref, result.tag_pattern) == ("attestation", "refs/heads/main", None)


@pytest.mark.integration
@respx.mock
@pytest.mark.parametrize(
    ("refs_status", "refs_body", "archive", "reason"),
    [
        (404, b"", None, "repository_not_found"),
        (503, b"", None, "repository_unreachable"),
        (200, refs(**{"v2.4.1": COMMIT}), None, "no_matching_tag"),
        (200, refs(**{"v2.5.0": COMMIT}), tarball({"../../evil.py": b"x"}, prefix=""), "archive_refused"),
        (200, refs(**{"v2.5.0": COMMIT}), b"not an archive", "archive_unreadable"),
    ],
)
def test_could_not_compare(
    github: GitHubClient, refs_status: int, refs_body: bytes, archive: bytes | None, reason: str
) -> None:
    """Every failure is a CouldNotCompare with a reason, never an exception or a guess."""
    respx.get(REFS_URL).respond(refs_status, content=refs_body)
    if archive is not None:
        respx.get(ARCHIVE_URL).respond(200, content=archive)
    result = fetch_source(github, project="orbit-client", version="2.5.0", repository=ORBIT)

    assert isinstance(result, CouldNotCompare)
    assert result.reason == reason
    assert result.repository == ORBIT
    assert result.detail


@pytest.mark.integration
@respx.mock
def test_archive_download_failure_is_unreachable(github: GitHubClient) -> None:
    """An archive the host won't serve is reported as unreachable."""
    respx.get(REFS_URL).respond(200, content=refs())
    respx.get(ARCHIVE_URL).respond(503)
    result = fetch_source(github, project="orbit-client", version="2.5.0", repository=ORBIT, attested_commit=COMMIT)
    assert isinstance(result, CouldNotCompare)
    assert result.reason == "repository_unreachable"


@pytest.mark.integration
def test_no_repository_and_typeshed(github: GitHubClient) -> None:
    """Without a repository, or for typeshed stubs, there's nothing to fetch and no request is made."""
    none = fetch_source(github, project="orbit-client", version="2.5.0", repository=None)
    stubs = fetch_source(
        github, project="types-orbit", version="1.0.0.20261001", repository=Repository("python", "typeshed")
    )
    assert isinstance(none, CouldNotCompare) and none.reason == "no_repository"
    assert isinstance(stubs, CouldNotCompare) and stubs.reason == "no_per_package_tags"


@pytest.mark.integration
@respx.mock
def test_archive_kept_in_work_dir_and_limits_apply(github: GitHubClient, tmp_path: Path) -> None:
    """With a work directory the archive is kept there; unpacker limits are passed through."""
    respx.get(REFS_URL).respond(200, content=refs())
    respx.get(ARCHIVE_URL).respond(200, content=SOURCE)
    kept = fetch_source(
        github, project="orbit-client", version="2.5.0", repository=ORBIT, attested_commit=COMMIT, work_dir=tmp_path
    )
    assert isinstance(kept, SourceSnapshot)
    assert (tmp_path / f"kestrel-weather-orbit-client-{COMMIT}.tar.gz").read_bytes() == SOURCE
    assert kept.archive == tmp_path / f"kestrel-weather-orbit-client-{COMMIT}.tar.gz"

    limited = fetch_source(
        github,
        project="orbit-client",
        version="2.5.0",
        repository=ORBIT,
        attested_commit=COMMIT,
        limits=_core.Limits(max_files=1),
    )
    assert isinstance(limited, CouldNotCompare) and limited.reason == "archive_refused"


@pytest.mark.integration
@respx.mock
def test_download_archive_limits(github: GitHubClient, tmp_path: Path) -> None:
    """Archives over the size limit are refused and leave nothing; only full SHAs are accepted."""
    respx.get(ARCHIVE_URL).respond(200, content=SOURCE)
    with pytest.raises(ArchiveTooLargeError):
        github.download_archive(ORBIT, COMMIT, tmp_path, max_size=10)
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(ValueError, match="full commit SHA"):
        github.download_archive(ORBIT, "main", tmp_path)


@pytest.mark.integration
@respx.mock
def test_record_source_snapshot_is_idempotent(db_session: Session, github: GitHubClient) -> None:
    """The same repository and commit map to one row."""
    respx.get(REFS_URL).respond(200, content=refs())
    respx.get(ARCHIVE_URL).respond(200, content=SOURCE)
    snapshot = fetch_source(github, project="orbit-client", version="2.5.0", repository=ORBIT, attested_commit=COMMIT)
    assert isinstance(snapshot, SourceSnapshot)
    package = Package(ecosystem="pypi", name="orbit-client", display_name="orbit-client")
    db_session.add(package)
    db_session.flush()

    first = record_source_snapshot(db_session, package.id, snapshot)
    second = record_source_snapshot(db_session, package.id, snapshot)

    assert first == second
    row = db_session.get(SnapshotRow, first)
    assert row is not None
    assert (row.repository, row.commit, row.origin) == ("kestrel-weather/orbit-client", COMMIT, "attestation")
    assert db_session.scalar(select(func.count()).select_from(SnapshotRow)) == 1


@pytest.mark.integration
@respx.mock
def test_archive_without_top_level_directory_keeps_paths(github: GitHubClient) -> None:
    """When entries don't share one top-level directory, paths are used as they are."""
    respx.get(REFS_URL).respond(200, content=refs())
    respx.get(ARCHIVE_URL).respond(200, content=tarball({"a.py": b"x", "pkg/b.py": b"y"}, prefix=""))
    result = fetch_source(github, project="orbit-client", version="2.5.0", repository=ORBIT, attested_commit=COMMIT)
    assert isinstance(result, SourceSnapshot)
    assert (result.prefix, sorted(result.relative_path(e) for e in result.entries)) == ("", ["a.py", "pkg/b.py"])


@pytest.mark.integration
@respx.mock
def test_archive_already_downloaded_is_reused(github: GitHubClient, tmp_path: Path) -> None:
    """A commit's archive in the work directory is used without another request."""
    route = respx.get(ARCHIVE_URL).respond(200, content=SOURCE)
    first = github.download_archive(ORBIT, COMMIT, tmp_path)
    second = github.download_archive(ORBIT, COMMIT, tmp_path)
    assert route.call_count == 1
    assert (second.path, second.sha256, second.size) == (first.path, hashlib.sha256(SOURCE).hexdigest(), len(SOURCE))
