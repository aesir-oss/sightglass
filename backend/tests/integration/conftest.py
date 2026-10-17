"""Fixtures for integration tests: a throwaway Postgres server and per-test transactions."""

import shutil
import socket
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.orm import Session

BACKEND_DIR = Path(__file__).resolve().parents[2]


class PostgresServer:
    """A Postgres cluster in a temporary directory, reachable over TCP on localhost only."""

    def __init__(self, data_dir: Path) -> None:
        """Create the cluster's data directory and pick a free port."""
        self.data_dir = data_dir
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port: int = sock.getsockname()[1]

    def start(self) -> None:
        """Initialize and start the cluster; Unix sockets are off because temp paths exceed their length limit."""
        subprocess.run(
            ["initdb", "-D", str(self.data_dir), "-U", "sightglass", "--auth=trust", "-E", "UTF8"],
            check=True,
            capture_output=True,
        )
        options = f"-p {self.port} -c listen_addresses=127.0.0.1 -c unix_socket_directories='' -c fsync=off"
        subprocess.run(
            ["pg_ctl", "-D", str(self.data_dir), "-o", options, "-l", str(self.data_dir / "server.log"), "-w", "start"],
            check=True,
            capture_output=True,
        )

    def stop(self) -> None:
        """Stop the cluster immediately."""
        subprocess.run(["pg_ctl", "-D", str(self.data_dir), "-m", "immediate", "stop"], check=True, capture_output=True)

    def url(self, database: str) -> str:
        """Return a SQLAlchemy URL for one database on this server."""
        return f"postgresql+psycopg://sightglass@127.0.0.1:{self.port}/{database}"

    def create_database(self, name: str) -> str:
        """Create an empty database and return its URL."""
        engine = create_engine(self.url("postgres"), isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        engine.dispose()
        return self.url(name)


def alembic_config(url: str) -> Config:
    """Return an Alembic config for the backend's migrations, pointed at ``url``."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture(scope="session")
def postgres(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PostgresServer]:
    """Start one Postgres server for the whole test session."""
    if shutil.which("initdb") is None:
        pytest.fail("initdb not found; run the tests through pixi so postgresql is on PATH")
    server = PostgresServer(tmp_path_factory.mktemp("pg") / "data")
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="session")
def migrated_engine(postgres: PostgresServer) -> Iterator[Engine]:
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
