"""Tests for GitHub ref advertisement parsing and repository names, with no network."""

import pytest

from sightglass.ecosystems.github import RefsFormatError, Repository, parse_ref_advertisement

C1 = "1" * 40
C2 = "2" * 40
TAG_OBJECT = "3" * 40


def pkt(line: str) -> bytes:
    """Encode one pkt-line."""
    data = line.encode()
    return f"{len(data) + 4:04x}".encode() + data


def advertisement(*lines: str) -> bytes:
    """A smart-HTTP upload-pack advertisement with the service header and a flush."""
    return pkt("# service=git-upload-pack\n") + b"0000" + b"".join(pkt(line) for line in lines) + b"0000"


def test_tags_with_lightweight_and_annotated_resolution() -> None:
    """Lightweight tags map to their commit; annotated tags map to the peeled commit, not the tag object."""
    body = advertisement(
        f"{C1} HEAD\0multi_ack symref=HEAD:refs/heads/main\n",
        f"{C1} refs/heads/main\n",
        f"{C2} refs/pull/7/head\n",
        f"{C1} refs/tags/v2.4.1\n",
        f"{TAG_OBJECT} refs/tags/v2.5.0\n",
        f"{C2} refs/tags/v2.5.0^{{}}\n",
    )
    assert parse_ref_advertisement(body) == {"v2.4.1": C1, "v2.5.0": C2}


def test_lines_with_invalid_shas_are_skipped() -> None:
    """Anything that isn't a full hex SHA is ignored rather than trusted."""
    assert parse_ref_advertisement(advertisement("nothex refs/tags/v1\n")) == {}


@pytest.mark.parametrize("body", [b"zzzz", b"0010short", b"0003"])
def test_malformed_pkt_lines_raise(body: bytes) -> None:
    """Bad lengths or truncated lines are a RefsFormatError."""
    with pytest.raises(RefsFormatError):
        parse_ref_advertisement(body)


def test_repository_slug() -> None:
    """A repository renders as owner/name."""
    assert Repository("kestrel-weather", "orbit-client").slug == "kestrel-weather/orbit-client"


@pytest.mark.parametrize(("owner", "name"), [("..", "x"), ("a", "b/c"), ("a", "b?x=1"), ("", "x"), ("a", "%2e%2e")])
def test_repository_rejects_names_that_change_urls(owner: str, name: str) -> None:
    """Names are restricted so a project URL can't make the client request another path."""
    with pytest.raises(ValueError, match="invalid GitHub name"):
        Repository(owner, name)
