"""The most-downloaded PyPI projects, for the lookalike-name rule, and the task that refreshes the list.

The list comes from ClickHouse's public, read-only PyPI downloads dataset and is committed as
``rules/data/top_packages.json``. Refresh it with ``pixi run refresh-top-packages``.
"""

import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlencode

from packaging.utils import canonicalize_name

from sightglass.ecosystems.http import Fetcher, default_client
from sightglass.log import configure_logging, get_logger

log = get_logger(__name__)

CLICKHOUSE_URL = "https://sql-clickhouse.clickhouse.com/"
CLICKHOUSE_HOSTS = frozenset({"sql-clickhouse.clickhouse.com"})
COUNT = 5000
WINDOW_DAYS = 30
MAX_RESPONSE = 16 * 1024 * 1024
DATA_FILE = Path(__file__).parent / "data" / "top_packages.json"
QUERY = (
    "SELECT project, sum(count) AS downloads FROM pypi.pypi_downloads_per_day "
    "WHERE date >= today() - {window} GROUP BY project ORDER BY downloads DESC LIMIT {count} FORMAT TSV"
)
_NAME_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$")


@dataclass(frozen=True)
class TopPackages:
    """Normalized names, most downloaded first, and when the list was queried."""

    queried_at: str
    names: tuple[str, ...]

    @property
    def rank(self) -> dict[str, int]:
        """1-based download rank by normalized name."""
        return {name: i for i, name in enumerate(self.names, 1)}


@cache
def load() -> TopPackages:
    """The committed list."""
    data = json.loads(files("sightglass.rules").joinpath("data/top_packages.json").read_text())
    return TopPackages(data["queried_at"], tuple(data["packages"]))


def parse_tsv(body: bytes) -> list[str]:
    """Normalized project names from ClickHouse's ``project<TAB>downloads`` rows, skipping malformed rows."""
    names: list[str] = []
    for row in body.decode("utf-8", "replace").splitlines():
        project, _, downloads = row.partition("\t")
        if not _NAME_RE.match(project) or not downloads.isdigit():
            log.warning("top_packages_row_skipped", row=row[:200])
            continue
        name = canonicalize_name(project)
        if name not in names:
            names.append(name)
    return names


def fetch(fetcher: Fetcher, count: int = COUNT, window_days: int = WINDOW_DAYS) -> list[str]:
    """Query the dataset for the ``count`` most-downloaded projects over the last ``window_days`` days."""
    params = {"user": "demo", "query": QUERY.format(window=window_days, count=count)}
    return parse_tsv(fetcher.get_bytes(f"{CLICKHOUSE_URL}?{urlencode(params)}", MAX_RESPONSE))


def write(names: list[str], path: Path = DATA_FILE, now: datetime | None = None) -> None:
    """Write the list with its source and date."""
    data = {
        "source": "ClickHouse public PyPI dataset (pypi.pypi_downloads_per_day), via sql-clickhouse.clickhouse.com",
        "queried_at": (now or datetime.now(UTC)).date().isoformat(),
        "window_days": WINDOW_DAYS,
        "packages": names,
    }
    path.write_text(json.dumps(data, indent=0) + "\n")


def main(argv: list[str] | None = None) -> int:
    """Refresh the committed list; returns a process exit code."""
    configure_logging()
    path = Path(argv[0]) if argv else DATA_FILE
    with default_client() as http:
        names = fetch(Fetcher(http, CLICKHOUSE_HOSTS))
    if len(names) < COUNT // 2:
        log.error("top_packages_too_few", count=len(names))
        return 1
    write(names, path)
    log.info("top_packages_refreshed", count=len(names), path=str(path))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
