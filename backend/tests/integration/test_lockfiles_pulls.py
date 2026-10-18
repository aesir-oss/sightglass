"""Reading a pull request's lockfile change from GitHub, with the REST API and raw files served by respx."""

from typing import Any

import pytest
import respx

from sightglass.ecosystems.http import RateLimitedError
from sightglass.lockfiles.pulls import (
    PullRequestClient,
    PullRequestError,
    PullRequestNotFoundError,
    default_fetcher,
    parse_pull_url,
)

API = "https://api.github.com/repos/kestrel-weather/orbit"
RAW = "https://raw.githubusercontent.com"
BASE_TIP, MERGE_BASE, HEAD = "1" * 40, "2" * 40, "3" * 40


def pull(head_repo: str | None = "fork-owner/orbit") -> dict[str, Any]:
    """A pull request from a fork."""
    return {
        "base": {"sha": BASE_TIP, "repo": {"full_name": "kestrel-weather/orbit"}},
        "head": {"sha": HEAD, "repo": {"full_name": head_repo} if head_repo else None},
    }


def serve(files: list[dict[str, Any]], head_repo: str | None = "fork-owner/orbit") -> None:
    """The pull request, its compare and its files."""
    respx.get(f"{API}/pulls/7").respond(200, json=pull(head_repo))
    respx.get(f"{API}/compare/{BASE_TIP}...{HEAD}").respond(200, json={"merge_base_commit": {"sha": MERGE_BASE}})
    respx.get(f"{API}/pulls/7/files", params={"page": "1"}).respond(200, json=files)


def client() -> PullRequestClient:
    """A reader that doesn't wait between retries."""
    fetcher = default_fetcher()
    fetcher.backoff = 0
    return PullRequestClient(fetcher)


@pytest.mark.integration
@respx.mock
def test_reads_both_sides_from_the_merge_base_and_the_fork() -> None:
    """The base side is the merge base in the base repository; the head side comes from the fork."""
    serve([{"filename": "README.md", "status": "modified"}, {"filename": "pixi.lock", "status": "modified"}])
    respx.get(f"{RAW}/kestrel-weather/orbit/{MERGE_BASE}/pixi.lock").respond(200, content=b"old lock")
    respx.get(f"{RAW}/kestrel-weather/orbit/{MERGE_BASE}/pixi.toml").respond(200, content=b"old manifest")
    respx.get(f"{RAW}/fork-owner/orbit/{HEAD}/pixi.lock").respond(200, content=b"new lock")
    respx.get(f"{RAW}/fork-owner/orbit/{HEAD}/pixi.toml").respond(404)
    respx.get(f"{RAW}/fork-owner/orbit/{HEAD}/pyproject.toml").respond(200, content=b"new pyproject")
    change = client().lockfile_change(parse_pull_url("https://github.com/kestrel-weather/orbit/pull/7"))
    assert (change.repository, change.number, change.lockfile_path) == ("kestrel-weather/orbit", 7, "pixi.lock")
    assert (change.base_sha, change.head_sha) == (MERGE_BASE, HEAD)
    assert change.base.lockfile == b"old lock"
    assert change.base.manifest == ("pixi.toml", b"old manifest")
    assert change.head.manifest == ("pyproject.toml", b"new pyproject")


@pytest.mark.integration
@respx.mock
def test_renamed_lockfile_and_deleted_fork() -> None:
    """A renamed lockfile is read at its old path on the base; a deleted fork's head is read from the base."""
    serve([{"filename": "app/uv.lock", "status": "renamed", "previous_filename": "uv.lock"}], head_repo=None)
    respx.get(f"{RAW}/kestrel-weather/orbit/{MERGE_BASE}/uv.lock").respond(200, content=b"old")
    respx.get(f"{RAW}/kestrel-weather/orbit/{HEAD}/app/uv.lock").respond(200, content=b"new")
    change = client().lockfile_change(parse_pull_url("https://github.com/kestrel-weather/orbit/pull/7"))
    assert change.lockfile_path == "app/uv.lock"
    assert (change.base.lockfile, change.head.lockfile) == (b"old", b"new")
    assert change.base.manifest is None


@pytest.mark.integration
@respx.mock
def test_files_are_read_page_by_page() -> None:
    """A full page of files means another page."""
    respx.get(f"{API}/pulls/7").respond(200, json=pull())
    respx.get(f"{API}/compare/{BASE_TIP}...{HEAD}").respond(200, json={"merge_base_commit": {"sha": MERGE_BASE}})
    page_one = [{"filename": f"src/f{i}.py", "status": "modified"} for i in range(100)]
    respx.get(f"{API}/pulls/7/files", params={"page": "1"}).respond(200, json=page_one)
    respx.get(f"{API}/pulls/7/files", params={"page": "2"}).respond(200, json=[])
    with pytest.raises(PullRequestError, match=r"doesn't change a pixi\.lock or uv\.lock"):
        client().lockfile_change(parse_pull_url("https://github.com/kestrel-weather/orbit/pull/7"))


@pytest.mark.integration
@respx.mock
def test_what_cant_be_reviewed_says_why() -> None:
    """A missing pull request, an added lockfile, odd API values and a used-up rate limit each raise."""
    ref = parse_pull_url("https://github.com/kestrel-weather/orbit/pull/7")
    respx.get(f"{API}/pulls/7").respond(404)
    with pytest.raises(PullRequestNotFoundError, match=r"no public pull request kestrel-weather/orbit#7"):
        client().lockfile_change(ref)
    respx.reset()
    serve([{"filename": "uv.lock", "status": "added"}])
    with pytest.raises(PullRequestError, match=r"uv\.lock is added by this pull request"):
        client().lockfile_change(ref)
    respx.get(f"{API}/pulls/7").respond(200, json={**pull(), "head": {"sha": "../x", "repo": None}})
    with pytest.raises(PullRequestError, match="unexpected commit"):
        client().lockfile_change(ref)
    respx.get(f"{API}/pulls/7").respond(200, json=pull(head_repo="bad name/../x"))
    with pytest.raises(PullRequestError, match="unexpected repository name"):
        client().lockfile_change(ref)
    respx.get(f"{API}/pulls/7").respond(403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1"})
    with pytest.raises(RateLimitedError):
        client().lockfile_change(ref)
