"""Tests for sightglass.ecosystems.http that need no network."""

import pytest

from sightglass.ecosystems.http import CachedResponse, DisallowedUrlError, MemoryCache, check_url, retry_delay

HOSTS = frozenset({"pypi.org", "files.pythonhosted.org"})


@pytest.mark.parametrize(("attempt", "low", "high"), [(1, 0.5, 0.55), (2, 1.0, 1.1), (3, 2.0, 2.2), (10, 30.0, 33.0)])
def test_backoff_doubles_with_jitter_and_cap(attempt: int, low: float, high: float) -> None:
    """Without Retry-After, delays double from the base, with at most 10% jitter, up to the cap."""
    assert low <= retry_delay(attempt, None, backoff=0.5, max_backoff=30.0) <= high


def test_retry_after_seconds_win_but_are_capped() -> None:
    """A numeric Retry-After is honored, but never beyond the cap."""
    assert retry_delay(1, "7", backoff=0.5, max_backoff=30.0) == 7.0
    assert retry_delay(1, "3600", backoff=0.5, max_backoff=30.0) == 30.0


def test_retry_after_date_falls_back_to_backoff() -> None:
    """An HTTP-date Retry-After isn't parsed; the normal backoff applies."""
    assert 0.5 <= retry_delay(1, "Wed, 21 Oct 2026 07:28:00 GMT", backoff=0.5, max_backoff=30.0) <= 0.55


@pytest.mark.parametrize("url", ["https://pypi.org/pypi/x/json", "https://FILES.pythonhosted.org/packages/a.whl"])
def test_allowed_urls(url: str) -> None:
    """HTTPS URLs on allowed hosts pass, whatever the host's case."""
    check_url(url, HOSTS)


@pytest.mark.parametrize(
    "url",
    [
        "http://pypi.org/pypi/x/json",
        "https://evil.example.net/a.whl",
        "https://pypi.org.evil.example.net/a.whl",
        "https://user:pw@pypi.org/x",
        "file:///etc/passwd",
        "https://169.254.169.254/latest/meta-data/",
    ],
)
def test_disallowed_urls(url: str) -> None:
    """Anything an index response could use to redirect requests elsewhere is refused."""
    with pytest.raises(DisallowedUrlError):
        check_url(url, HOSTS)


def test_memory_cache() -> None:
    """The in-process cache stores by URL."""
    cache = MemoryCache()
    assert cache.get("u") is None
    cache.put("u", CachedResponse(b"x", '"e"', None))
    assert cache.get("u") == CachedResponse(b"x", '"e"', None)
