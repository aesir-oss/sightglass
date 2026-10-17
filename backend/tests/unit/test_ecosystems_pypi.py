"""Tests for parsing PyPI responses, with inline payloads and no network."""

import json
from typing import Any

import pytest

from sightglass.ecosystems.pypi import IndexDataError, Ownership, parse_project, safe_filename

SHA_A = "a" * 64


def payload(releases: dict[str, list[dict[str, Any]]], **extra: Any) -> bytes:
    """A minimal JSON API response for the invented package tidepool."""
    return json.dumps({"info": {"name": "Tidepool", "project_urls": None}, "releases": releases, **extra}).encode()


def file(name: str, uploaded: str, **extra: Any) -> dict[str, Any]:
    """A JSON API file entry."""
    return {
        "filename": name,
        "url": f"https://files.pythonhosted.org/packages/{name}",
        "digests": {"sha256": SHA_A},
        "size": 10,
        "upload_time_iso_8601": uploaded,
        "packagetype": "bdist_wheel",
        **extra,
    }


def test_releases_sorted_by_publish_time_with_empty_last() -> None:
    """History is oldest first by first upload; releases without files go last."""
    project = parse_project(
        payload(
            {
                "1.10": [file("tidepool-1.10-py3-none-any.whl", "2026-03-01T00:00:00Z")],
                "1.9": [file("tidepool-1.9-py3-none-any.whl", "2026-01-01T00:00:00Z")],
                "0.1": [],
            }
        )
    )
    assert [r.version for r in project.releases] == ["1.9", "1.10", "0.1"]
    assert project.releases[-1].published_at is None
    assert project.releases[-1].yanked is False
    assert (project.name, project.normalized_name, project.project_urls) == ("Tidepool", "tidepool", {})
    assert project.ownership is None


def test_release_is_yanked_only_when_every_file_is() -> None:
    """One yanked file out of two doesn't yank the release."""
    project = parse_project(
        payload(
            {
                "2.0": [
                    file("tidepool-2.0-py3-none-any.whl", "2026-01-01T00:00:00Z", yanked=True),
                    file("tidepool-2.0.tar.gz", "2026-01-01T00:00:01Z", packagetype="sdist"),
                ]
            }
        )
    )
    release = project.releases[0]
    assert not release.yanked
    assert [(f.filename, f.kind, f.yanked) for f in release.files] == [
        ("tidepool-2.0-py3-none-any.whl", "wheel", True),
        ("tidepool-2.0.tar.gz", "sdist", False),
    ]


def test_files_without_sha256_are_dropped() -> None:
    """A file that can't be verified isn't offered for download."""
    project = parse_project(
        payload({"1.0": [file("tidepool-1.0.zip", "2026-01-01T00:00:00Z", digests={"md5": "x"}, packagetype="sdist")]})
    )
    assert project.releases[0].files == ()


def test_ownership_is_parsed() -> None:
    """Owner and maintainer accounts are kept as (user, role) pairs."""
    project = parse_project(
        payload({}, ownership={"organization": "kestrel", "roles": [{"role": "Owner", "user": "k"}]})
    )
    assert project.ownership == Ownership("kestrel", (("k", "Owner"),))


@pytest.mark.parametrize(
    "bad",
    [b"not json", b"[]", b'{"info": {}}', json.dumps({"info": {"name": "x"}, "releases": {"1": [{"size": "big"}]}})],
)
def test_malformed_responses_raise(bad: bytes | str) -> None:
    """Anything that isn't the JSON API's shape is an IndexDataError."""
    with pytest.raises(IndexDataError):
        parse_project(bad.encode() if isinstance(bad, str) else bad)


def test_unsafe_filename_in_response_raises() -> None:
    """A file name that could escape the download directory is refused while parsing."""
    with pytest.raises(IndexDataError, match="unsafe file name"):
        parse_project(payload({"1.0": [file("../../etc/cron.d/evil", "2026-01-01T00:00:00Z")]}))


@pytest.mark.parametrize("name", ["", ".", "..", ".hidden.whl", "a/b.whl", "a\\b.whl", "a\0b.whl"])
def test_safe_filename_rejects(name: str) -> None:
    """Empty, dot, hidden and path-like names are refused."""
    with pytest.raises(IndexDataError):
        safe_filename(name)


def test_safe_filename_accepts_normal_names() -> None:
    """Ordinary artifact names pass unchanged."""
    assert safe_filename("orbit_client-2.5.0-py3-none-any.whl") == "orbit_client-2.5.0-py3-none-any.whl"
