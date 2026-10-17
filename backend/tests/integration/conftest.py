"""Fixtures for integration tests: a throwaway Postgres server and per-test transactions."""

import shutil
from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.orm import Session

from sightglass.db.local import LocalPostgres
from sightglass.db.migrate import alembic_config


@pytest.fixture(scope="session")
def postgres(tmp_path_factory: pytest.TempPathFactory) -> Iterator[LocalPostgres]:
    """Start one Postgres server for the whole test session."""
    if shutil.which("initdb") is None:
        pytest.fail("initdb not found; run the tests through pixi so postgresql is on PATH")
    server = LocalPostgres(tmp_path_factory.mktemp("pg") / "data")
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="session")
def migrated_engine(postgres: LocalPostgres) -> Iterator[Engine]:
    """An engine for a database migrated to the latest revision, shared by the session."""
    url = postgres.create_database("sightglass_test")
    command.upgrade(alembic_config(url), "head")
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_connection(migrated_engine: Engine) -> Iterator[Connection]:
    """A connection inside a transaction that is rolled back after the test."""
    with migrated_engine.connect() as conn:
        transaction = conn.begin()
        yield conn
        transaction.rollback()


@pytest.fixture
def db_session(db_connection: Connection) -> Iterator[Session]:
    """An ORM session whose commits become savepoints in the rolled-back test transaction."""
    session = Session(bind=db_connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
