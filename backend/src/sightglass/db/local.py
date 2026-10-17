"""A Postgres cluster in a local directory, for tests and the local analyze command.

It uses the ``initdb`` and ``pg_ctl`` from the pixi environment and listens on 127.0.0.1 only. Unix sockets are off,
because temporary paths on macOS are longer than the socket path limit.
"""

import socket
import subprocess
from pathlib import Path

from sqlalchemy import create_engine, text

from sightglass.log import get_logger

log = get_logger(__name__)

USER = "sightglass"


class LocalPostgres:
    """A cluster whose data lives in ``data_dir``, reachable over TCP on a free localhost port."""

    def __init__(self, data_dir: Path) -> None:
        """Pick a free port; nothing starts until :meth:`start`."""
        self.data_dir = data_dir
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port: int = sock.getsockname()[1]

    def start(self, *, durable: bool = False) -> None:
        """Initialize the cluster if its data directory is new, then start it.

        Args:
            durable: Keep fsync on, for data that should survive a crash; tests turn it off for speed.
        """
        if not (self.data_dir / "PG_VERSION").is_file():
            self.data_dir.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["initdb", "-D", str(self.data_dir), "-U", USER, "--auth=trust", "-E", "UTF8"],
                check=True,
                capture_output=True,
            )
            log.info("postgres_initialized", data_dir=str(self.data_dir))
        options = f"-p {self.port} -c listen_addresses=127.0.0.1 -c unix_socket_directories=''"
        if not durable:
            options += " -c fsync=off"
        subprocess.run(
            ["pg_ctl", "-D", str(self.data_dir), "-o", options, "-l", str(self.data_dir / "server.log"), "-w", "start"],
            check=True,
            capture_output=True,
        )

    def stop(self, *, fast: bool = False) -> None:
        """Stop the cluster: ``immediate`` mode for throwaway data, ``fast`` (a clean shutdown) otherwise."""
        mode = "fast" if fast else "immediate"
        subprocess.run(["pg_ctl", "-D", str(self.data_dir), "-m", mode, "stop"], check=True, capture_output=True)

    def url(self, database: str) -> str:
        """A SQLAlchemy URL for one database on this cluster."""
        return f"postgresql+psycopg://{USER}@127.0.0.1:{self.port}/{database}"

    def create_database(self, name: str, *, exist_ok: bool = False) -> str:
        """Create a database (unless it exists and ``exist_ok``) and return its URL."""
        engine = create_engine(self.url("postgres"), isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}).first()
            if not (exists and exist_ok):
                conn.execute(text(f'CREATE DATABASE "{name}"'))
        engine.dispose()
        return self.url(name)
