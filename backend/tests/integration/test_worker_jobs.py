"""The job queue against a real Postgres migrated to head, in a database of its own."""

from typing import Any

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from sightglass.worker import jobs
from sightglass.worker.pipeline import PairResult

from .conftest import PostgresServer, alembic_config


@pytest.mark.integration
def test_queue_deduplicates_and_runs(postgres: PostgresServer, monkeypatch: pytest.MonkeyPatch) -> None:
    """The queueing lock is enforced by the database, and a worker runs the job to success."""
    url = postgres.create_database("job_queue")
    command.upgrade(alembic_config(url), "head")
    calls: list[tuple[Any, ...]] = []

    def fake(session: object, services: object, *args: Any, **kwargs: Any) -> list[PairResult]:
        calls.append(args)
        return []

    monkeypatch.setattr(jobs, "analyze_release_pair", fake)
    monkeypatch.setattr(jobs, "_services", lambda: None)
    monkeypatch.setenv("SIGHTGLASS_DATABASE_URL", url)
    jobs._engine.cache_clear()
    app = jobs.make_app(url)
    with app.open():
        first = jobs.enqueue_analysis(app, "pypi", "orbit-client", "2.4.1", "2.5.0")
        second = jobs.enqueue_analysis(app, "pypi", "ORBIT.client", "2.4.1", "2.5.0")
    assert first is not None and second is None

    app.run_worker(wait=False)
    jobs._engine.cache_clear()

    engine = create_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT status, lock, queueing_lock FROM procrastinate_jobs")).all()
    engine.dispose()
    assert [tuple(r) for r in rows] == [
        ("succeeded", "pypi:orbit-client:2.4.1...2.5.0", "pypi:orbit-client:2.4.1...2.5.0")
    ]
    assert calls == [("orbit-client", "2.4.1", "2.5.0")]
