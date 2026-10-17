"""Tests for sightglass.db.engine."""

import pytest

from sightglass.db.engine import DATABASE_URL_ENV, database_url, make_engine


def test_database_url_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The URL comes from SIGHTGLASS_DATABASE_URL."""
    monkeypatch.setenv(DATABASE_URL_ENV, "postgresql+psycopg://u@db.example.net/sightglass")
    assert database_url() == "postgresql+psycopg://u@db.example.net/sightglass"


@pytest.mark.parametrize("value", [None, ""])
def test_database_url_missing_raises(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    """A missing or empty setting fails loudly instead of connecting somewhere unexpected."""
    if value is None:
        monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    else:
        monkeypatch.setenv(DATABASE_URL_ENV, value)
    with pytest.raises(RuntimeError, match=DATABASE_URL_ENV):
        database_url()


def test_make_engine_prefers_explicit_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit URL wins over the environment; creating an engine doesn't connect."""
    monkeypatch.setenv(DATABASE_URL_ENV, "postgresql+psycopg://env@db.example.net/a")
    engine = make_engine("postgresql+psycopg://explicit@db.example.net/b")
    assert engine.url.username == "explicit"
    assert engine.url.database == "b"
