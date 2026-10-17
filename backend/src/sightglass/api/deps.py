"""Dependencies the routes share: a database session and the index clients. Tests override them."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import cache

import procrastinate
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from sightglass.db.engine import make_engine
from sightglass.ecosystems.http import Fetcher, MemoryCache, default_client
from sightglass.ecosystems.provenance import IntegrityClient
from sightglass.ecosystems.pypi import PYPI_HOSTS, PypiClient
from sightglass.storage.blobs import BlobStore, LocalBlobStore
from sightglass.worker.jobs import enqueue_analysis, make_app
from sightglass.worker.pipeline import default_cache_dir

# Queue an analysis: (ecosystem, package, from, to, wheel or None) -> job id, or None if already queued.
Enqueue = Callable[[str, str, str, str, str | None], int | None]


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


@cache
def _queue() -> procrastinate.App:
    app = make_app()
    app.open()
    return app


def get_enqueue() -> Enqueue:
    """Queue analyses on the procrastinate app, opened once per process."""

    def enqueue(ecosystem: str, package: str, from_version: str, to_version: str, wheel: str | None) -> int | None:
        return enqueue_analysis(_queue(), ecosystem, package, from_version, to_version, wheel)

    return enqueue


@cache
def _blobs() -> BlobStore:
    return LocalBlobStore(default_cache_dir() / "blobs")


def get_blobs() -> BlobStore:
    """The blob store the workers write file contents to."""
    return _blobs()
