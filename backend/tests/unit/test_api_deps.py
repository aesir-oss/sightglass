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
