"""Refreshing the top-packages list against an intercepted ClickHouse endpoint."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from sightglass.ecosystems.http import Fetcher, default_client
from sightglass.rules import top_packages


def rows(n: int) -> bytes:
    """``n`` invented TSV rows."""
    return b"".join(f"kestrel-pkg-{i}\t{n - i}\n".encode() for i in range(n))


@pytest.mark.integration
@respx.mock
def test_fetch_queries_clickhouse() -> None:
    """The query goes to the public endpoint as the demo user and asks for the configured count and window."""
    route = respx.get(url__startswith=top_packages.CLICKHOUSE_URL).respond(200, content=rows(3))
    with default_client() as http:
        names = top_packages.fetch(Fetcher(http, top_packages.CLICKHOUSE_HOSTS), count=3, window_days=7)
    assert names == ["kestrel-pkg-0", "kestrel-pkg-1", "kestrel-pkg-2"]
    params = route.calls.last.request.url.params
    assert params["user"] == "demo" and "LIMIT 3" in params["query"] and "today() - 7" in params["query"]


@pytest.mark.integration
def test_write_round_trips(tmp_path: Path) -> None:
    """The written file has its source, date and names."""
    path = tmp_path / "top.json"
    top_packages.write(["orbit-client", "tidepool"], path, datetime(2026, 10, 1, tzinfo=UTC))
    data = json.loads(path.read_text())
    assert (data["queried_at"], data["packages"], data["window_days"]) == (
        "2026-10-01",
        ["orbit-client", "tidepool"],
        30,
    )
    assert "ClickHouse" in data["source"]


@pytest.mark.integration
@respx.mock
def test_main_refreshes_or_refuses_a_short_list(tmp_path: Path) -> None:
    """The task writes a full list and refuses to replace it with a truncated answer."""
    path = tmp_path / "top.json"
    respx.get(url__startswith=top_packages.CLICKHOUSE_URL).mock(
        side_effect=[httpx.Response(200, content=rows(top_packages.COUNT)), httpx.Response(200, content=rows(10))]
    )
    assert top_packages.main([str(path)]) == 0
    assert len(json.loads(path.read_text())["packages"]) == top_packages.COUNT
    path.write_text("kept")
    assert top_packages.main([str(path)]) == 1
    assert path.read_text() == "kept"
