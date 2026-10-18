"""The job queue against a real Postgres migrated to head, in a database of its own."""

import asyncio
from typing import Any

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from sightglass.db.local import LocalPostgres
from sightglass.db.migrate import alembic_config
from sightglass.worker import jobs
from sightglass.worker.pipeline import PairResult


@pytest.mark.integration
def test_queue_deduplicates_and_runs(postgres: LocalPostgres, monkeypatch: pytest.MonkeyPatch) -> None:
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
        rows = conn.execute(
            text("SELECT status, lock, queueing_lock FROM procrastinate_jobs WHERE task_name = :task"),
            {"task": jobs.TASK},
        ).all()
    engine.dispose()
    assert [tuple(r) for r in rows] == [
        ("succeeded", "pypi:orbit-client:2.4.1...2.5.0", "pypi:orbit-client:2.4.1...2.5.0")
    ]
    assert calls == [("orbit-client", "2.4.1", "2.5.0")]


def _statuses(url: str) -> list[tuple[int, str]]:
    engine = create_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, status FROM procrastinate_jobs ORDER BY id")).all()
    engine.dispose()
    return [(int(r[0]), str(r[1])) for r in rows]


def _stall(url: str, job_id: int) -> None:
    """Leave a job in doing with no worker, as a worker killed mid-analysis does."""
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE procrastinate_jobs SET status = 'doing', worker_id = NULL WHERE id = :id"), {"id": job_id}
        )
    engine.dispose()


@pytest.mark.integration
def test_stalled_jobs_are_recovered(postgres: LocalPostgres) -> None:
    """A stalled job goes back to the queue; when its pair is already waiting, it's failed so the waiting job runs."""
    url = postgres.create_database("stalled_jobs")
    command.upgrade(alembic_config(url), "head")
    app = jobs.make_app(url)
    with app.open():
        alone = jobs.enqueue_analysis(app, "pypi", "orbit-client", "2.4.1", "2.5.0")
        assert alone is not None
    _stall(url, alone)
    with app.open():
        assert asyncio.run(_recover(app)) == [alone]
    assert _statuses(url) == [(alone, "todo")]

    # The same pair stalled while a later request for it waits: the stalled one is failed, the waiting one stays.
    _stall(url, alone)
    with app.open():
        waiting = jobs.enqueue_analysis(app, "pypi", "orbit-client", "2.4.1", "2.5.0")
        assert waiting is not None
    with app.open():
        assert asyncio.run(_recover(app)) == [alone]
    assert _statuses(url) == [(alone, "failed"), (waiting, "todo")]
    with app.open():
        assert asyncio.run(_recover(app)) == []


async def _recover(app: Any) -> list[int]:
    async with app.open_async():
        return await jobs.retry_stalled_jobs(app)
