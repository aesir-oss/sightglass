"""Integration tests for the Alembic migrations."""

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from sightglass.db.local import LocalPostgres
from sightglass.db.migrate import alembic_config
from sightglass.db.migrations import include_object
from sightglass.db.models import Base


@pytest.mark.integration
def test_upgrade_matches_models(postgres: LocalPostgres) -> None:
    """After upgrading to head, autogenerate finds nothing left to migrate."""
    url = postgres.create_database("migrations_match")
    command.upgrade(alembic_config(url), "head")

    engine = create_engine(url)
    with engine.connect() as conn:
        opts = {"compare_server_default": True, "include_object": include_object}
        diffs = compare_metadata(MigrationContext.configure(conn, opts=opts), Base.metadata)
    engine.dispose()
    assert diffs == []


@pytest.mark.integration
def test_downgrade_to_base_removes_everything(postgres: LocalPostgres) -> None:
    """Every revision can be reverted, leaving only Alembic's own table."""
    url = postgres.create_database("migrations_roundtrip")
    config = alembic_config(url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = create_engine(url)
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    engine.dispose()


@pytest.mark.integration
def test_job_queue_schema_round_trips(postgres: LocalPostgres) -> None:
    """Revision 0003 creates procrastinate's tables and types, and reverting it removes them all."""
    url = postgres.create_database("migrations_queue")
    config = alembic_config(url)
    command.upgrade(config, "0003")
    engine = create_engine(url)
    assert {"procrastinate_jobs", "procrastinate_workers"} <= set(inspect(engine).get_table_names())
    command.downgrade(config, "0002")
    with engine.connect() as conn:
        leftovers = conn.exec_driver_sql(
            "SELECT proname FROM pg_proc WHERE proname LIKE 'procrastinate%%' "
            "UNION ALL SELECT typname FROM pg_type WHERE typname LIKE 'procrastinate%%'"
        ).all()
    assert leftovers == []
    assert not any(t.startswith("procrastinate") for t in inspect(engine).get_table_names())
    engine.dispose()
