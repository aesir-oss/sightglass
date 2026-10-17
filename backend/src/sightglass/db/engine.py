"""Database connection settings."""

import os

from sqlalchemy import Engine, create_engine

DATABASE_URL_ENV = "SIGHTGLASS_DATABASE_URL"


def database_url() -> str:
    """Read the database URL from the environment.

    Returns:
        A SQLAlchemy URL, for example ``postgresql+psycopg://user@host/sightglass``.

    Raises:
        RuntimeError: If ``SIGHTGLASS_DATABASE_URL`` isn't set.
    """
    url = os.environ.get(DATABASE_URL_ENV)
    if not url:
        raise RuntimeError(f"{DATABASE_URL_ENV} is not set")
    return url


def make_engine(url: str | None = None) -> Engine:
    """Create an engine for the given URL, or for ``SIGHTGLASS_DATABASE_URL``.

    Args:
        url: A SQLAlchemy URL. Defaults to the environment setting.

    Returns:
        A SQLAlchemy engine that checks connections before use.
    """
    return create_engine(url or database_url(), pool_pre_ping=True)
