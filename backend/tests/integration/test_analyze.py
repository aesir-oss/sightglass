"""The analyze command's databases: the configured one, or a local cluster that persists between runs."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from sightglass import analyze
from sightglass.db.local import LocalPostgres


@pytest.mark.integration
def test_configured_database_is_migrated(
    postgres: LocalPostgres, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With SIGHTGLASS_DATABASE_URL set, that database is migrated and used."""
    url = postgres.create_database("analyze_configured")
    monkeypatch.setenv("SIGHTGLASS_DATABASE_URL", url)
    with analyze.database(tmp_path) as used:
        assert used == url
    engine = create_engine(url)
    assert "analysis" in inspect(engine).get_table_names()
    engine.dispose()


@pytest.mark.integration
def test_local_cluster_persists_between_runs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Without a URL, a cluster is initialized under the cache directory once and reused, then stopped."""
    monkeypatch.delenv("SIGHTGLASS_DATABASE_URL", raising=False)
    with analyze.database(tmp_path) as first:
        engine = create_engine(first)
        assert "procrastinate_jobs" in inspect(engine).get_table_names()
        engine.dispose()
    assert (tmp_path / "postgres" / "PG_VERSION").is_file()
    assert not (tmp_path / "postgres" / "postmaster.pid").exists()
    with analyze.database(tmp_path) as second:
        engine = create_engine(second)
        assert "analysis" in inspect(engine).get_table_names()
        engine.dispose()
