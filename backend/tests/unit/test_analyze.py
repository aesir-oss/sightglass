"""Tests for the local analyze command, with the database and pipeline replaced."""

import io
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from sightglass import analyze
from sightglass.worker.pipeline import PairResult, PipelineError, TransientError

SIGNAL = {"rule_id": "behavior.network", "level": "high", "message": "Added network calls", "evidence": {"items": []}}
DONE = PairResult(7, "wheel", "a-1.0-py3-none-any.whl", "a-1.1-py3-none-any.whl", "done", False, None, (SIGNAL,))
FAILED = PairResult(8, "sdist", "a-1.0.tar.gz", "a-1.1.tar.gz", "failed", False, "ArtifactIntegrityError: sha256")


@pytest.fixture
def pipeline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[Any]:
    """Replace the database and pipeline; the returned list holds what the pipeline should return or raise."""
    outcome: list[Any] = [[DONE]]

    @contextmanager
    def database(cache: Path) -> Iterator[str]:
        yield "postgresql+psycopg://sightglass@127.0.0.1:1/sightglass"

    def run(session: object, services: object, package: str, from_version: str, to_version: str) -> list[PairResult]:
        if isinstance(outcome[0], Exception):
            raise outcome[0]
        result: list[PairResult] = outcome[0]
        return result

    monkeypatch.setenv("SIGHTGLASS_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(analyze, "database", database)
    monkeypatch.setattr(analyze, "analyze_release_pair", run)
    monkeypatch.setattr(analyze.Services, "default", classmethod(lambda cls, cache: None))
    return outcome


def test_json_output(pipeline: list[Any]) -> None:
    """--format json writes every pair with its signals to stdout."""
    out = io.StringIO()
    assert analyze.main(["pypi", "orbit-client", "1.0", "1.1", "--format", "json"], out=out) == 0
    [pair] = json.loads(out.getvalue())
    assert (pair["kind"], pair["status"], pair["signals"]) == ("wheel", "done", [SIGNAL])


def test_log_output_and_failed_pairs(pipeline: list[Any], capsys: pytest.CaptureFixture[str]) -> None:
    """The default format logs each pair and signal; a failed pair makes the exit code 1."""
    pipeline[0] = [FAILED, DONE]
    out = io.StringIO()
    assert analyze.main(["pypi", "orbit-client", "1.0", "1.1"], out=out) == 1
    events = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [e["event"] for e in events] == ["pair", "pair_failed", "pair", "signal"]
    assert events[3]["rule_id"] == "behavior.network" and out.getvalue() == ""


@pytest.mark.parametrize("error", [PipelineError("release_not_found", "no 9.9"), TransientError("pypi.org is down")])
def test_errors_exit_1(pipeline: list[Any], error: Exception, capsys: pytest.CaptureFixture[str]) -> None:
    """A pair that can't be analyzed is logged and exits 1."""
    pipeline[0] = error
    assert analyze.main(["pypi", "orbit-client", "1.0", "9.9"]) == 1
    assert "analysis_failed" in capsys.readouterr().err


def test_bad_arguments_exit_2() -> None:
    """Unknown ecosystems are rejected by the argument parser."""
    with pytest.raises(SystemExit) as exc:
        analyze.parse_args(["npm", "orbit", "1", "2"])
    assert exc.value.code == 2
