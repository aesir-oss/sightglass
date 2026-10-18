"""Tests for reading pull request URLs and choosing the lockfile to review, with no network."""

import pytest

from sightglass.lockfiles.pulls import TOKEN_ENV, PullRequestError, choose_lockfile, default_fetcher, parse_pull_url


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/kestrel-weather/orbit/pull/7",
        "https://github.com/kestrel-weather/orbit/pull/7/",
        "https://github.com/kestrel-weather/orbit/pull/7/files",
        "https://github.com/kestrel-weather/orbit/pull/7/changes#diff-abc",
        "  https://github.com/kestrel-weather/orbit/pull/7?w=1  ",
    ],
)
def test_pull_urls_name_the_repository_and_number(url: str) -> None:
    """Any tab of a pull request, with a query or fragment, reads the same."""
    ref = parse_pull_url(url)
    assert (ref.repository.slug, ref.number) == ("kestrel-weather/orbit", 7)


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/kestrel-weather/orbit/pull/7",
        "https://gitlab.com/kestrel-weather/orbit/pull/7",
        "https://github.com/kestrel-weather/orbit/issues/7",
        "https://github.com/kestrel-weather/orbit/pull/0",
        "https://github.com/kestrel-weather/../pull/7",
        "https://github.com.evil.example/kestrel-weather/orbit/pull/7",
        "kestrel-weather/orbit#7",
    ],
)
def test_anything_else_is_refused(url: str) -> None:
    """Other hosts, schemes, issue URLs and path tricks aren't pull requests."""
    with pytest.raises(PullRequestError):
        parse_pull_url(url)


def test_the_shallowest_lockfile_wins_and_pixi_before_uv() -> None:
    """The root lockfile is the project's; at one depth pixi.lock comes first."""
    files = [
        {"filename": "services/api/pixi.lock"},
        {"filename": "uv.lock"},
        {"filename": "README.md"},
        {"filename": "pixi.lock"},
    ]
    assert choose_lockfile(files) == {"filename": "pixi.lock"}
    assert choose_lockfile([{"filename": "a/uv.lock"}, {"filename": "b/c/pixi.lock"}]) == {"filename": "a/uv.lock"}
    assert choose_lockfile([{"filename": "poetry.lock"}, {"filename": "not-pixi.lock"}]) is None


def test_the_token_is_sent_only_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unauthenticated by default; the token raises the rate limit."""
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    assert "Authorization" not in default_fetcher().client.headers
    monkeypatch.setenv(TOKEN_ENV, "test-token")
    assert default_fetcher().client.headers["Authorization"] == "Bearer test-token"
