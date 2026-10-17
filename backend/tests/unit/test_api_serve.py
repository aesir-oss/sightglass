"""Tests for serving the API: structured logging and the uvicorn runner."""

import io
import json
import logging
from typing import Any

import pytest

from sightglass.api import __main__ as runner
from sightglass.api import app as app_module


def test_serve_configures_logging_before_building_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """The served app logs JSON at the configured level, including records from libraries like uvicorn."""
    calls: list[str] = []
    monkeypatch.setenv("SIGHTGLASS_LOG_LEVEL", "warning")
    monkeypatch.setattr(app_module, "configure_logging", lambda level: calls.append(level))
    app = app_module.serve()
    assert calls == ["warning"]
    assert any(getattr(r, "path", None) == "/api/health" for r in app.routes)


def test_uvicorn_records_render_as_json() -> None:
    """With uvicorn's own logging config off, its loggers reach the structured handler."""
    stream = io.StringIO()
    app_module.configure_logging(stream=stream)
    logging.getLogger("uvicorn.error").info("Application startup complete.")
    record = json.loads(stream.getvalue())
    assert (record["event"], record["logger"]) == ("Application startup complete.", "uvicorn.error")


def test_runner_starts_uvicorn_with_the_factory_and_no_log_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """``python -m sightglass.api`` runs the factory with uvicorn's logging setup disabled."""
    seen: dict[str, Any] = {}

    def fake_run(target: str, **kwargs: Any) -> None:
        seen.update(target=target, **kwargs)

    monkeypatch.setattr(runner.uvicorn, "run", fake_run)
    assert runner.main(["--reload", "--port", "9000"]) == 0
    assert seen == {
        "target": "sightglass.api.app:serve",
        "factory": True,
        "host": "127.0.0.1",
        "port": 9000,
        "reload": True,
        "log_config": None,
    }
