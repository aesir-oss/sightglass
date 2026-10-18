"""HTTP fetching shared by the index and source host clients: allowed hosts, conditional requests, retries."""

import random
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from sightglass import __version__
from sightglass.log import get_logger

log = get_logger(__name__)

USER_AGENT = f"sightglass/{__version__} (+https://github.com/aesir-oss/sightglass)"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class HttpError(Exception):
    """A request couldn't be completed."""


class NotFoundError(HttpError):
    """The server answered 404 or 410."""


class UnavailableError(HttpError):
    """The server kept failing or rate limiting after every retry."""


class DisallowedUrlError(HttpError):
    """A URL isn't HTTPS or points at a host the client isn't allowed to contact."""


class ResponseTooLargeError(HttpError):
    """A response body exceeded the caller's size limit."""


@dataclass(frozen=True)
class CachedResponse:
    """A response body with the validators needed to revalidate it."""

    body: bytes
    etag: str | None
    last_modified: str | None


class ResponseCache(Protocol):
    """Storage for conditional requests, keyed by URL."""

    def get(self, url: str) -> CachedResponse | None:
        """Return the cached response for ``url``, if any."""
        ...

    def put(self, url: str, response: CachedResponse) -> None:
        """Remember a response for ``url``."""
        ...


class MemoryCache:
    """A response cache in a dict, for one process."""

    def __init__(self) -> None:
        """Start empty."""
        self._entries: dict[str, CachedResponse] = {}

    def get(self, url: str) -> CachedResponse | None:
        """Return the cached response for ``url``, if any."""
        return self._entries.get(url)

    def put(self, url: str, response: CachedResponse) -> None:
        """Remember a response for ``url``."""
        self._entries[url] = response


def retry_delay(attempt: int, retry_after: str | None, backoff: float, max_backoff: float) -> float:
    """Seconds to wait before retry number ``attempt`` (1 for the first retry).

    A numeric ``Retry-After`` header wins, capped at ``max_backoff``. Otherwise the delay doubles each attempt from
    ``backoff``, with up to 10% jitter so concurrent workers don't retry in lockstep.

    Args:
        attempt: Which retry this is, starting at 1.
        retry_after: The ``Retry-After`` header value, if the server sent one.
        backoff: Base delay in seconds.
        max_backoff: Upper bound in seconds.

    Returns:
        The delay in seconds.
    """
    if retry_after is not None and retry_after.strip().isdigit():
        return min(float(retry_after.strip()), max_backoff)
    base = min(backoff * 2.0 ** (attempt - 1), max_backoff)
    return base + random.uniform(0, base * 0.1)


def check_url(url: str, allowed_hosts: frozenset[str]) -> None:
    """Refuse anything but HTTPS to an allowed host.

    Args:
        url: The URL about to be requested; it may come from an untrusted index response.
        allowed_hosts: Lowercase host names the client may contact.

    Raises:
        DisallowedUrlError: If the scheme isn't ``https``, or the host isn't allowed.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or host not in allowed_hosts or parts.username or parts.password:
        raise DisallowedUrlError(f"refusing to fetch {url!r}")


class Fetcher:
    """GETs with an allowed-host check, conditional requests, retries with backoff and a size cap."""

    def __init__(
        self,
        client: httpx.Client,
        allowed_hosts: frozenset[str],
        *,
        cache: ResponseCache | None = None,
        max_attempts: int = 5,
        backoff: float = 0.5,
        max_backoff: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Wrap an httpx client.

        Args:
            client: The HTTP client; redirects should be off, so every URL passes the host check.
            allowed_hosts: Lowercase host names that may be contacted.
            cache: Where to keep validators for conditional requests; none means no revalidation.
            max_attempts: Total tries for a request, including the first.
            backoff: Base delay in seconds between retries.
            max_backoff: Longest delay between retries.
            sleep: Function used to wait; tests pass a recorder.
        """
        self.client = client
        self.allowed_hosts = allowed_hosts
        self.cache = cache
        self.max_attempts = max_attempts
        self.backoff = backoff
        self.max_backoff = max_backoff
        self._sleep = sleep
        self._received = 0
        self._lock = threading.Lock()

    @property
    def received_bytes(self) -> int:
        """Bytes of response bodies read through this fetcher so far, across threads."""
        return self._received

    def get_bytes(self, url: str, max_size: int, accept: str | None = None) -> bytes:
        """Fetch a whole response body, revalidating a cached copy when possible.

        Args:
            url: HTTPS URL on an allowed host.
            max_size: Largest body accepted, in bytes.
            accept: Value for the ``Accept`` header.

        Returns:
            The body, either fresh or from the cache after a 304.

        Raises:
            DisallowedUrlError: If the URL isn't allowed.
            NotFoundError: On 404 or 410.
            UnavailableError: If retries run out.
            ResponseTooLargeError: If the body exceeds ``max_size``.
            HttpError: On any other unexpected status.
        """
        cached = self.cache.get(url) if self.cache else None
        headers = {"Accept": accept} if accept else {}
        if cached and cached.etag:
            headers["If-None-Match"] = cached.etag
        if cached and cached.last_modified:
            headers["If-Modified-Since"] = cached.last_modified
        with self.stream(url, headers=headers, allow_not_modified=cached is not None) as response:
            if response.status_code == 304 and cached is not None:
                log.debug("http_not_modified", url=url)
                return cached.body
            body = _read_capped(response, max_size, url)
        if self.cache:
            self.cache.put(
                url,
                CachedResponse(body, response.headers.get("ETag"), response.headers.get("Last-Modified")),
            )
        return body

    @contextmanager
    def stream(
        self, url: str, headers: dict[str, str] | None = None, *, allow_not_modified: bool = False
    ) -> Iterator[httpx.Response]:
        """Open a streaming GET, retrying failures that happen before the body is read.

        Args:
            url: HTTPS URL on an allowed host.
            headers: Extra request headers.
            allow_not_modified: Whether a 304 is an acceptable answer.

        Yields:
            A response with status 200 (or 304 when allowed) whose body hasn't been read yet.

        Raises:
            DisallowedUrlError: If the URL isn't allowed.
            NotFoundError: On 404 or 410.
            UnavailableError: If retries run out.
            HttpError: On any other unexpected status.
        """
        check_url(url, self.allowed_hosts)
        for attempt in range(1, self.max_attempts + 1):
            retry_after: str | None = None
            with ExitStack() as stack:
                try:
                    response = stack.enter_context(self.client.stream("GET", url, headers=headers))
                except httpx.TransportError as exc:
                    reason = f"{type(exc).__name__}: {exc}"
                else:
                    status = response.status_code
                    if status == 200 or (status == 304 and allow_not_modified):
                        # Errors raised while the caller reads the body propagate; only opening is retried.
                        try:
                            yield response
                        finally:
                            with self._lock:
                                self._received += response.num_bytes_downloaded
                        return
                    if status in (404, 410):
                        raise NotFoundError(f"{url} returned {status}")
                    if status not in RETRY_STATUSES:
                        raise HttpError(f"{url} returned unexpected status {status}")
                    retry_after = response.headers.get("Retry-After")
                    reason = f"status {status}"
            if attempt == self.max_attempts:
                raise UnavailableError(f"{url} failed after {attempt} attempts ({reason})")
            delay = retry_delay(attempt, retry_after, self.backoff, self.max_backoff)
            log.warning("http_retry", url=url, attempt=attempt, reason=reason, delay=round(delay, 2))
            self._sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover


def _read_capped(response: httpx.Response, max_size: int, url: str) -> bytes:
    declared = response.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > max_size:
        raise ResponseTooLargeError(f"{url} declares {declared} bytes, over the {max_size} limit")
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > max_size:
            raise ResponseTooLargeError(f"{url} sent more than {max_size} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def default_client(timeout: float = 30.0) -> httpx.Client:
    """Create an httpx client with Sightglass's user agent, a timeout and redirects off."""
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=False)
