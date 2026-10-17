"""Tests for the API's shared dependencies."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sightglass.api import deps


def test_index_is_shared_and_session_is_per_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """One set of index clients serves the process; each request gets its own session."""
    assert deps.get_index() is deps.get_index()
    engine = create_engine("postgresql+psycopg://sightglass@127.0.0.1:1/sightglass")
    monkeypatch.setattr(deps, "_engine", lambda: engine)
    sessions = [next(deps.get_session()) for _ in range(2)]
    assert all(isinstance(s, Session) and s.get_bind() is engine for s in sessions)
    assert sessions[0] is not sessions[1]
    engine.dispose()


def test_enqueue_opens_the_queue_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Queued analyses go through one procrastinate app per process, opened on first use."""
    opened: list[object] = []
    queued: list[tuple[object, ...]] = []

    class FakeApp:
        def open(self) -> None:
            opened.append(self)

    monkeypatch.setattr(deps, "make_app", FakeApp)
    monkeypatch.setattr(deps, "enqueue_analysis", lambda app, *args: queued.append((app, *args)) or 3)
    deps._queue.cache_clear()
    enqueue = deps.get_enqueue()
    assert enqueue("pypi", "orbit-client", "1.0", "1.1", None) == 3
    assert enqueue("pypi", "orbit-client", "1.1", "1.2", "x.whl") == 3
    assert len(opened) == 1 and [q[1:] for q in queued] == [
        ("pypi", "orbit-client", "1.0", "1.1", None),
        ("pypi", "orbit-client", "1.1", "1.2", "x.whl"),
    ]
    deps._queue.cache_clear()


def test_blobs_use_the_shared_cache_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    """The API reads the blob store the workers write, under SIGHTGLASS_CACHE_DIR."""
    monkeypatch.setenv("SIGHTGLASS_CACHE_DIR", str(tmp_path))
    deps._blobs.cache_clear()
    store = deps.get_blobs()
    assert store is deps.get_blobs()
    assert str(store.root) == f"{tmp_path}/blobs"  # type: ignore[attr-defined]
    deps._blobs.cache_clear()
