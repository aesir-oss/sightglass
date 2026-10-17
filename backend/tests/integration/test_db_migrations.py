"""Integration tests for the Alembic migrations."""

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from sightglass.db.models import Base

from .conftest import PostgresServer, alembic_config


@pytest.mark.integration
def test_upgrade_matches_models(postgres: PostgresServer) -> None:
    """After upgrading to head, autogenerate finds nothing left to migrate."""
    url = postgres.create_database("migrations_match")
    command.upgrade(alembic_config(url), "head")

    engine = create_engine(url)
    with engine.connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn, opts={"compare_server_default": True}), Base.metadata)
    engine.dispose()
    assert diffs == []


@pytest.mark.integration
def test_downgrade_to_base_removes_everything(postgres: PostgresServer) -> None:
    """Every revision can be reverted, leaving only Alembic's own table."""
    url = postgres.create_database("migrations_roundtrip")
    config = alembic_config(url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = create_engine(url)
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    engine.dispose()
