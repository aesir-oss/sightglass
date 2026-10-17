"""Integration tests for the PyPI client against recorded responses, intercepted with respx."""

import hashlib
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from sightglass.ecosystems.http import (
    DisallowedUrlError,
    Fetcher,
    HttpError,
    MemoryCache,
    NotFoundError,
    ResponseTooLargeError,
    UnavailableError,
    default_client,
)
from sightglass.ecosystems.pypi import (
    PYPI_HOSTS,
    ArtifactIntegrityError,
    ArtifactTooLargeError,
    PypiClient,
    PypiFile,
)

PROJECT_URL = "https://pypi.org/pypi/orbit-client/json"
WHEEL = b"PK\x03\x04 pretend this is a wheel"
WHEEL_URL = "https://files.pythonhosted.org/packages/cc/dd/orbit_client-2.5.0-py3-none-any.whl"


@pytest.fixture
def delays() -> list[float]:
    """Delays the fetcher asked to sleep for."""
    return []


@pytest.fixture
def client(delays: list[float]) -> Iterator[PypiClient]:
    """A PyPI client whose retries sleep into ``delays`` instead of waiting."""
    with default_client() as http:
        yield PypiClient(Fetcher(http, PYPI_HOSTS, cache=MemoryCache(), max_attempts=3, sleep=delays.append))


def wheel_file(**overrides: object) -> PypiFile:
    """The invented orbit-client wheel, as the index would describe it."""
    fields: dict[str, object] = {
        "filename": "orbit_client-2.5.0-py3-none-any.whl",
        "url": WHEEL_URL,
        "sha256": hashlib.sha256(WHEEL).hexdigest(),
        "size": len(WHEEL),
        "uploaded_at": datetime(2026, 9, 30, tzinfo=UTC),
        "kind": "wheel",
        "yanked": False,
        "yanked_reason": None,
        "requires_python": None,
    }
    fields.update(overrides)
    return PypiFile(**fields)  # type: ignore[arg-type]


@pytest.mark.integration
@respx.mock
def test_project_history(client: PypiClient, fixture_bytes: Callable[[str], bytes]) -> None:
    """A recorded JSON API response becomes the release history, oldest first."""
    route = respx.get(PROJECT_URL).respond(200, content=fixture_bytes("pypi/orbit-client.json"))
    project = client.project("Orbit_Client")

    assert route.calls.last.request.headers["User-Agent"].startswith("sightglass/")
    assert [r.version for r in project.releases] == ["2.4.1", "2.5.0", "2.6.0rc1", "0.0.1"]
    old, current, rc, empty = project.releases
    assert [(f.kind, f.filename) for f in old.files] == [
        ("wheel", "orbit_client-2.4.1-py3-none-any.whl"),
        ("other", "orbit_client-2.4.1-py3.9.egg"),
    ]
    assert current.published_at == datetime(2026, 9, 30, 10, 0, tzinfo=UTC)
    assert rc.yanked and rc.files[0].yanked_reason == "broken build"
    assert empty.files == ()
    assert project.ownership is not None
    assert project.ownership.roles == (("kestrel-dev", "Owner"), ("relay-ops", "Maintainer"))
    assert project.project_urls["Source"] == "https://github.com/kestrel-weather/orbit-client"


@pytest.mark.integration
@respx.mock
def test_conditional_request_reuses_cached_body(client: PypiClient, fixture_bytes: Callable[[str], bytes]) -> None:
    """The second fetch sends the ETag and Last-Modified back, and a 304 reuses the cached body."""
    body = fixture_bytes("pypi/orbit-client.json")
    route = respx.get(PROJECT_URL)
    route.side_effect = [
        httpx.Response(200, content=body, headers={"ETag": '"v1"', "Last-Modified": "Tue, 30 Sep 2026 10:00:00 GMT"}),
        httpx.Response(304),
    ]
    first = client.project("orbit-client")
    second = client.project("orbit-client")

    revalidation = route.calls[1].request.headers
    assert (revalidation["If-None-Match"], revalidation["If-Modified-Since"]) == (
        '"v1"',
        "Tue, 30 Sep 2026 10:00:00 GMT",
    )
    assert second == first


@pytest.mark.integration
@respx.mock
def test_unknown_project(client: PypiClient) -> None:
    """A 404 is NotFoundError, without retries."""
    route = respx.get("https://pypi.org/pypi/no-such-package/json").respond(404)
    with pytest.raises(NotFoundError):
        client.project("No_Such.Package")
    assert route.call_count == 1


@pytest.mark.integration
@respx.mock
def test_rate_limit_is_retried_honoring_retry_after(
    client: PypiClient, delays: list[float], fixture_bytes: Callable[[str], bytes]
) -> None:
    """429 and 503 are retried; Retry-After sets the wait."""
    respx.get(PROJECT_URL).side_effect = [
        httpx.Response(429, headers={"Retry-After": "2"}),
        httpx.Response(503),
        httpx.Response(200, content=fixture_bytes("pypi/orbit-client.json")),
    ]
    assert client.project("orbit-client").name == "Orbit_Client"
    assert delays[0] == 2.0
    assert 1.0 <= delays[1] <= 1.1


@pytest.mark.integration
@respx.mock
def test_transport_errors_are_retried_then_give_up(client: PypiClient, delays: list[float]) -> None:
    """Connection failures are retried; after the last attempt the error says why."""
    respx.get(PROJECT_URL).side_effect = httpx.ConnectError("connection refused")
    with pytest.raises(UnavailableError, match=r"after 3 attempts.*ConnectError"):
        client.project("orbit-client")
    assert len(delays) == 2


@pytest.mark.integration
@respx.mock
def test_unexpected_status_is_not_retried(client: PypiClient) -> None:
    """A status that retrying won't fix fails at once."""
    route = respx.get(PROJECT_URL).respond(403)
    with pytest.raises(HttpError, match="unexpected status 403"):
        client.project("orbit-client")
    assert route.call_count == 1


@pytest.mark.integration
@respx.mock
def test_oversized_metadata_is_refused(delays: list[float]) -> None:
    """Metadata over the size limit is refused, whether declared up front or only sent."""
    with default_client() as http:
        fetcher = Fetcher(http, PYPI_HOSTS, sleep=delays.append)
        respx.get("https://pypi.org/a").respond(200, content=b"x" * 11)
        with pytest.raises(ResponseTooLargeError, match="declares"):
            fetcher.get_bytes("https://pypi.org/a", max_size=10)
        respx.get("https://pypi.org/b").respond(200, stream=httpx.ByteStream(b"x" * 11))
        with pytest.raises(ResponseTooLargeError, match="sent more"):
            fetcher.get_bytes("https://pypi.org/b", max_size=10)


@pytest.mark.integration
@respx.mock
def test_download_verifies_and_renames(client: PypiClient, tmp_path: Path) -> None:
    """A matching download lands under its own name with nothing else left behind."""
    respx.get(WHEEL_URL).respond(200, content=WHEEL)
    path = client.download(wheel_file(), tmp_path)

    assert path == tmp_path / "orbit_client-2.5.0-py3-none-any.whl"
    assert path.read_bytes() == WHEEL
    assert [p.name for p in tmp_path.iterdir()] == [path.name]


@pytest.mark.integration
@respx.mock
@pytest.mark.parametrize(
    ("served", "match"),
    [(WHEEL[:-1] + b"?", "sha256"), (WHEEL[:-1], "received"), (WHEEL + b"!", "more than")],
)
def test_download_mismatch_leaves_nothing(client: PypiClient, tmp_path: Path, served: bytes, match: str) -> None:
    """Wrong content, a short body or extra bytes fail verification, and no file is kept."""
    respx.get(WHEEL_URL).respond(200, content=served)
    with pytest.raises(ArtifactIntegrityError, match=match):
        client.download(wheel_file(), tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.integration
@respx.mock
def test_download_too_large_is_refused_before_requesting(client: PypiClient, tmp_path: Path) -> None:
    """An artifact the index lists as too large isn't downloaded at all."""
    route = respx.get(WHEEL_URL).respond(200, content=WHEEL)
    with pytest.raises(ArtifactTooLargeError):
        client.download(wheel_file(), tmp_path, max_size=len(WHEEL) - 1)
    assert route.call_count == 0


@pytest.mark.integration
@respx.mock
def test_download_from_other_host_is_refused(client: PypiClient, tmp_path: Path) -> None:
    """An index response can't send the client to an arbitrary host."""
    with pytest.raises(DisallowedUrlError):
        client.download(wheel_file(url="https://evil.example.net/orbit.whl"), tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.integration
def test_default_client_targets_pypi() -> None:
    """The default client is set up for pypi.org with a response cache."""
    client = PypiClient.default()
    assert client.base_url == "https://pypi.org"
    assert client.fetcher.allowed_hosts == PYPI_HOSTS
    assert client.fetcher.cache is not None
    client.fetcher.client.close()
