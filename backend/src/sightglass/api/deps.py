"""Dependencies the routes share: a database session and the index clients. Tests override them."""

from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from sightglass.db.engine import make_engine
from sightglass.ecosystems.http import Fetcher, MemoryCache, default_client
from sightglass.ecosystems.provenance import IntegrityClient
from sightglass.ecosystems.pypi import PYPI_HOSTS, PypiClient


@dataclass(frozen=True)
class Index:
    """Clients for one package index."""

    pypi: PypiClient
    integrity: IntegrityClient


@cache
def _engine() -> Engine:
    return make_engine()


@cache
def _index() -> Index:
    # One response cache per process: repeat requests revalidate with ETags instead of downloading again.
    fetcher = Fetcher(default_client(), PYPI_HOSTS, cache=MemoryCache())
    return Index(PypiClient(fetcher), IntegrityClient(fetcher))


def get_session() -> Iterator[Session]:
    """A session on ``SIGHTGLASS_DATABASE_URL`` for one request."""
    with Session(_engine()) as session:
        yield session


def get_index() -> Index:
    """The process's PyPI clients."""
    return _index()
