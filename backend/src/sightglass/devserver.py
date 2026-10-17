"""``pixi run dev``: the API, a worker and Vite's dev server together, stopped together.

The database is ``SIGHTGLASS_DATABASE_URL``, or the same local Postgres the analyze command uses. Vite proxies
``/api`` to the API on ``API_PORT``.
"""

import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from sightglass.analyze import database
from sightglass.db.engine import DATABASE_URL_ENV
from sightglass.log import configure_logging, get_logger
from sightglass.worker.pipeline import default_cache_dir

log = get_logger("sightglass.devserver")

API_PORT = 8000
FRONTEND = Path(__file__).resolve().parents[3] / "frontend"


def commands() -> list[tuple[str, list[str], Path | None]]:
    """The processes to run: name, command line, working directory."""
    python = sys.executable
    return [
        (
            "api",
            [
                python,
                "-m",
                "uvicorn",
                "sightglass.api.app:create_app",
                "--factory",
                "--reload",
                "--port",
                str(API_PORT),
            ],
            None,
        ),
        ("worker", [python, "-m", "sightglass.worker"], None),
        ("web", ["pnpm", "run", "dev"], FRONTEND),
    ]


def run(
    procs: Sequence[tuple[str, list[str], Path | None]],
    env: dict[str, str],
    poll: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Start every process, wait until one exits or Ctrl-C, then stop the rest; returns the first exit code."""
    started = [(name, subprocess.Popen(cmd, cwd=cwd, env=env)) for name, cmd, cwd in procs]
    code = 0
    try:
        while True:
            exited = [(name, p.returncode) for name, p in started if p.poll() is not None]
            if exited:
                name, code = exited[0]
                log.info("dev_process_exited", process=name, code=code)
                return code
            sleep(poll)
    except KeyboardInterrupt:
        log.info("dev_stopping")
        return 0
    finally:
        for _, p in started:
            if p.poll() is None:
                p.terminate()
        for _, p in started:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


def main() -> int:
    """Run the development servers until interrupted."""
    configure_logging()
    with database(default_cache_dir()) as url:
        env = {**os.environ, DATABASE_URL_ENV: url}
        log.info("dev_starting", api=f"http://127.0.0.1:{API_PORT}", web="http://localhost:5173")
        return run(commands(), env)


if __name__ == "__main__":
    sys.exit(main())
