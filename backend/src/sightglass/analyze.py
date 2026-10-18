"""Analyze one release pair from the command line, without the web service or the queue.

``pixi run analyze pypi <package> <from> <to>`` runs the full pipeline and reports the signals. It uses the database in
``SIGHTGLASS_DATABASE_URL`` when that is set; otherwise it starts a local Postgres under the cache directory, which
keeps results and downloads between runs.
"""

import argparse
import json
import os
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import TextIO

from sqlalchemy.orm import Session

from sightglass.db.engine import DATABASE_URL_ENV, make_engine
from sightglass.db.local import LocalPostgres
from sightglass.db.migrate import upgrade
from sightglass.log import configure_logging, get_logger
from sightglass.worker.pipeline import (
    PairResult,
    PipelineError,
    Services,
    TransientError,
    analyze_release_pair,
    default_cache_dir,
)

log = get_logger("sightglass.analyze")

LOCAL_DATABASE = "sightglass"


@contextmanager
def database(cache: Path) -> Iterator[str]:
    """Yield a migrated database URL: the configured one, or the local cluster (started for the duration if needed)."""
    if url := os.environ.get(DATABASE_URL_ENV):
        upgrade(url)
        yield url
        return
    server = LocalPostgres(cache / "postgres")
    if (port := server.running_port()) is not None:
        # `pixi run dev` (or another command) has it running: use it, and leave it running.
        server.port = port
        url = server.create_database(LOCAL_DATABASE, exist_ok=True)
        upgrade(url)
        yield url
        return
    server.start(durable=True)
    try:
        url = server.create_database(LOCAL_DATABASE, exist_ok=True)
        upgrade(url)
        yield url
    finally:
        server.stop(fast=True)


def report(results: list[PairResult], fmt: str, out: TextIO) -> None:
    """Write the results as one JSON document, or log each signal as a structured event."""
    if fmt == "json":
        out.write(json.dumps([asdict(r) for r in results], indent=2) + "\n")
        return
    for r in results:
        log.info("pair", kind=r.kind, old=r.old_filename, new=r.new_filename, status=r.status, cached=r.cached)
        if r.error:
            log.warning("pair_failed", kind=r.kind, error=r.error)
        for s in r.signals:
            log.info("signal", kind=r.kind, rule_id=s["rule_id"], level=s["level"], message=s["message"])


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(prog="analyze", description="Analyze one release pair of a package.")
    parser.add_argument("ecosystem", choices=["pypi"], help="package ecosystem")
    parser.add_argument("package", help="package name, in any spelling")
    parser.add_argument("from_version", metavar="from", help="earlier release")
    parser.add_argument("to_version", metavar="to", help="later release")
    parser.add_argument("--format", choices=["log", "json"], default="log", help="signals as log events or JSON")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, out: TextIO | None = None) -> int:
    """Run the command; returns the process exit code (0 done, 1 the pair couldn't be analyzed)."""
    args = parse_args(argv)
    configure_logging()
    cache = default_cache_dir()
    try:
        with database(cache) as url:
            engine = make_engine(url)
            try:
                with Session(engine) as session:
                    results = analyze_release_pair(
                        session, Services.default(cache), args.package, args.from_version, args.to_version
                    )
            finally:
                engine.dispose()
    except (PipelineError, TransientError) as exc:
        log.error("analysis_failed", error=str(exc))
        return 1
    report(results, args.format, out or sys.stdout)
    return 0 if all(r.status == "done" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
