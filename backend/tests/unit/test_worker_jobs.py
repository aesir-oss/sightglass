"""Tests for the job queue, with procrastinate's in-memory connector and the pipeline replaced."""

from collections.abc import Iterator
from typing import Any

import procrastinate
import pytest
from procrastinate.testing import InMemoryConnector

from sightglass.worker import jobs
from sightglass.worker.pipeline import PairResult, PipelineError, TransientError

URL = "postgresql+psycopg://sightglass:secret@db.example.net:5432/sightglass"


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[procrastinate.App, InMemoryConnector, list[dict[str, Any]]]]:
    """An app on an in-memory queue whose pipeline records its calls instead of running."""
    calls: list[dict[str, Any]] = []
    outcome: dict[str, BaseException | None] = {"raise": None}

    def fake(
        session: object, services: object, package: str, from_version: str, to_version: str, **kw: Any
    ) -> list[PairResult]:
        calls.append({"package": package, "from": from_version, "to": to_version, **kw})
        if (exc := outcome["raise"]) is not None:
            raise exc
        return [PairResult(1, "wheel", "a.whl", "b.whl", "done", False)]

    monkeypatch.setattr(jobs, "analyze_release_pair", fake)
    monkeypatch.setattr(jobs, "_services", lambda: None)
    monkeypatch.setattr(jobs, "_engine", lambda: None)
    monkeypatch.setattr(jobs, "Session", _NullSession)
    connector = InMemoryConnector()
    real = jobs.make_app(URL)
    with real.replace_connector(connector) as app:
        app.outcome = outcome  # type: ignore[attr-defined]
        yield app, connector, calls


class _NullSession:
    def __init__(self, engine: object) -> None:
        pass

    def __enter__(self) -> _NullSession:
        return self

    def __exit__(self, *exc: object) -> None:
        pass


def test_conninfo_and_pair_key() -> None:
    """URLs become libpq strings; pair keys normalize the package name."""
    assert jobs.conninfo(URL) == "postgresql://sightglass:secret@db.example.net:5432/sightglass"
    assert jobs.pair_key("pypi", "Orbit_Client", "2.4.1", "2.5.0") == "pypi:orbit-client:2.4.1...2.5.0"


def test_duplicate_requests_are_deduplicated(app: tuple[procrastinate.App, InMemoryConnector, list[Any]]) -> None:
    """A second request for a queued pair, in any spelling, isn't queued again."""
    application, connector, _ = app
    first = jobs.enqueue_analysis(application, "pypi", "orbit-client", "2.4.1", "2.5.0")
    second = jobs.enqueue_analysis(application, "pypi", "Orbit_Client", "2.4.1", "2.5.0")
    other = jobs.enqueue_analysis(application, "pypi", "orbit-client", "2.5.0", "2.6.0")
    assert first is not None and second is None and other is not None
    assert len(connector.jobs) == 2


def test_worker_runs_the_pipeline(app: tuple[procrastinate.App, InMemoryConnector, list[Any]]) -> None:
    """A queued job runs the pipeline with the job's arguments, not on its final attempt."""
    application, connector, calls = app
    jobs.enqueue_analysis(application, "pypi", "orbit-client", "2.4.1", "2.5.0")
    application.run_worker(wait=False)
    assert calls == [{"package": "orbit-client", "from": "2.4.1", "to": "2.5.0", "final_attempt": False}]
    assert [j["status"] for j in connector.jobs.values()] == ["succeeded"]


def test_transient_errors_are_retried(app: tuple[procrastinate.App, InMemoryConnector, list[Any]]) -> None:
    """A transient failure schedules a retry instead of failing the job."""
    application, connector, _ = app
    application.outcome["raise"] = TransientError("pypi.org returned 503")  # type: ignore[attr-defined]
    jobs.enqueue_analysis(application, "pypi", "orbit-client", "2.4.1", "2.5.0")
    application.run_worker(wait=False)
    [job] = connector.jobs.values()
    assert (job["status"], job["attempts"]) == ("todo", 1)
    assert job["scheduled_at"] is not None


def test_impossible_pairs_fail_without_retry(app: tuple[procrastinate.App, InMemoryConnector, list[Any]]) -> None:
    """A pipeline error, or an unsupported ecosystem, fails the job once."""
    application, connector, calls = app
    application.outcome["raise"] = PipelineError("release_not_found", "no 9.9.9")  # type: ignore[attr-defined]
    jobs.enqueue_analysis(application, "pypi", "orbit-client", "2.4.1", "9.9.9")
    jobs.enqueue_analysis(application, "npm", "orbit-client", "2.4.1", "2.5.0")
    application.run_worker(wait=False)
    assert sorted(j["status"] for j in connector.jobs.values()) == ["failed", "failed"]
    assert len(calls) == 1


def test_last_attempt_is_flagged(app: tuple[procrastinate.App, InMemoryConnector, list[Any]]) -> None:
    """On the last attempt the pipeline is told so, and accepts an unreachable source."""
    application, connector, calls = app
    jobs.enqueue_analysis(application, "pypi", "orbit-client", "2.4.1", "2.5.0")
    [job] = connector.jobs.values()
    job["attempts"] = jobs.MAX_ATTEMPTS
    application.run_worker(wait=False)
    assert calls[0]["final_attempt"] is True


def test_worker_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    """``python -m sightglass.worker`` configures logging and runs a worker on the configured database."""
    from sightglass.worker import __main__ as entry

    ran: list[str] = []

    class FakeApp:
        def run_worker(self) -> None:
            ran.append("worker")

    monkeypatch.setattr(entry, "make_app", FakeApp)
    monkeypatch.setattr(entry, "configure_logging", lambda: ran.append("logging"))
    entry.main()
    assert ran == ["logging", "worker"]
