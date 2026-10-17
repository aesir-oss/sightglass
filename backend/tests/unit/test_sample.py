"""Tests for the routine-release sample: choosing pairs, recording outcomes and the report."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from sightglass import sample
from sightglass.ecosystems.http import NotFoundError
from sightglass.ecosystems.pypi import PypiClient, PypiFile, PypiProject, PypiRelease
from sightglass.worker.pipeline import PairResult, PipelineError, Services

CUTOFF = datetime(2026, 9, 1, tzinfo=UTC)


def release(version: str, day: str, *, yanked: bool = False) -> PypiRelease:
    """One sdist release published on ``day``."""
    uploaded = datetime.fromisoformat(f"{day}T00:00:00+00:00")
    f = PypiFile(f"p-{version}.tar.gz", "https://x/p.tar.gz", "0" * 64, 1, uploaded, "sdist", yanked, None, None)
    return PypiRelease(version, (f,))


def project(*releases: PypiRelease) -> PypiProject:
    """A project with these releases."""
    return PypiProject("P", "p", {}, None, None, releases)


def test_routine_pair_skips_new_yanked_and_prereleases_and_follows_the_release_line() -> None:
    """The newest stable release before the cutoff, paired with the highest stable version below it."""
    p = project(
        release("1.0", "2026-01-01"),
        release("2.0", "2026-03-01"),
        release("1.1", "2026-04-01"),  # a backport, published after 2.0
        release("2.1", "2026-05-01", yanked=True),
        release("2.2rc1", "2026-06-01"),
        release("2.2", "2026-07-01"),
        release("2.3", "2026-09-20"),  # too new
        release("not a version", "2026-07-02"),
    )
    pair = sample.routine_pair(p, 3, CUTOFF)
    assert pair == sample.SamplePair("p", 3, "2.0", "2.2", "2026-07-01")


def test_routine_pair_needs_two_releases() -> None:
    """A project with one qualifying release has no pair."""
    assert sample.routine_pair(project(release("1.0", "2026-01-01")), 1, CUTOFF) is None


def test_select_keeps_count_and_skips_missing_packages() -> None:
    """Packages without a pair or missing from the index are skipped; selection stops at the count."""
    projects = {
        "a": project(release("1.0", "2026-01-01"), release("1.1", "2026-02-01")),
        "b": project(release("1.0", "2026-01-01")),
        "d": project(release("3.0", "2026-01-01"), release("3.1", "2026-02-01")),
        "e": project(release("5.0", "2026-01-01"), release("5.1", "2026-02-01")),
    }

    def lookup(name: str) -> PypiProject:
        if name not in projects:
            raise NotFoundError(f"no {name}")
        return projects[name]

    pairs = sample.select(lookup, ["a", "b", "c", "d", "e"], 2, CUTOFF)
    assert [(p.rank, p.to_version) for p in pairs] == [(1, "1.1"), (4, "3.1")]
    held_out = sample.select(lookup, ["a", "b", "c", "d", "e"], 5, CUTOFF, first_rank=4)
    assert [p.rank for p in held_out] == [4, 5]


PAIR = sample.SamplePair("orbit-client", 1, "2.4.1", "2.5.0", "2026-09-01")
SIGNAL = {"rule_id": "behavior.network", "level": "high", "message": "New network call", "evidence": {}}


def test_analyze_pair_records_signals_and_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each artifact's signals are kept without evidence; a pipeline error becomes the record's error."""
    results = [
        PairResult(1, "sdist", "a.tar.gz", "b.tar.gz", "failed", False, "ArtifactTooLargeError: big"),
        PairResult(2, "wheel", "a.whl", "b.whl", "done", False, None, (SIGNAL,)),
    ]
    monkeypatch.setattr(sample, "analyze_release_pair", lambda *a, **k: results)
    record = sample.analyze_pair(None, None, PAIR)  # type: ignore[arg-type]
    assert record["error"] is None
    assert record["artifacts"][1]["signals"] == [{k: SIGNAL[k] for k in ("rule_id", "level", "message")}]

    def fail(*a: Any, **k: Any) -> list[PairResult]:
        raise PipelineError("release_not_found", "gone")

    monkeypatch.setattr(sample, "analyze_release_pair", fail)
    assert sample.analyze_pair(None, None, PAIR)["error"] == "release_not_found: gone"  # type: ignore[arg-type]


def test_summarize_counts_levels_and_lists_high_check_and_failures() -> None:
    """The report counts signals by level and rule and lists every high and check signal and every failure."""
    ok = {
        **PAIR.__dict__,
        "error": None,
        "artifacts": [
            {"kind": "wheel", "status": "done", "error": None, "signals": [SIGNAL]},
            {"kind": "sdist", "status": "failed", "error": "ArtifactTooLargeError: big", "signals": []},
        ],
    }
    gone = {**PAIR.__dict__, "package": "tidepool", "error": "tidepool has no release", "artifacts": []}
    report = sample.summarize([ok, gone], "rs-1")
    assert "- Signals by level: high 1, check 0, note 0" in report
    assert "| high | `behavior.network` | 1 |" in report
    assert "- orbit-client 2.4.1 → 2.5.0 (wheel): `behavior.network` New network call" in report
    assert "## Check signals\n\nNone." in report
    assert "- orbit-client 2.4.1 → 2.5.0: sdist: ArtifactTooLargeError: big" in report
    assert "- tidepool 2.4.1 → 2.5.0: tidepool has no release" in report


def test_main_select_and_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Select writes the sample; run writes results and report and exits 1 while a high signal remains."""
    monkeypatch.setattr(sample, "RESEARCH", tmp_path)
    monkeypatch.setattr(sample, "select", lambda *a: [PAIR])
    monkeypatch.setattr(PypiClient, "default", classmethod(lambda cls: type("C", (), {"project": None})()))
    assert sample.main(["select", "--today", "2026-10-17"]) == 0
    doc = json.loads((tmp_path / "routine-sample.json").read_text())
    assert doc["sampled_on"] == "2026-10-17" and doc["pairs"][0]["package"] == "orbit-client"

    record = {**PAIR.__dict__, "error": None, "artifacts": [{"kind": "wheel", "status": "done", "error": None}]}
    seen: list[list[sample.SamplePair]] = []

    def fake_run(url: str, cache: Path, pairs: list[sample.SamplePair], jobs: int) -> list[dict[str, Any]]:
        seen.append(list(pairs))
        return [{**record, "artifacts": [{**record["artifacts"][0], "signals": signals}]} for _ in pairs]

    class _Db:
        def __init__(self, cache: Path) -> None: ...
        def __enter__(self) -> str:
            return "postgresql://x"

        def __exit__(self, *exc: object) -> None: ...

    monkeypatch.setattr(sample, "database", _Db)
    monkeypatch.setattr(sample, "run", fake_run)
    monkeypatch.setenv("SIGHTGLASS_CACHE_DIR", str(tmp_path))
    signals: list[dict[str, Any]] = [SIGNAL]
    assert sample.main(["run"]) == 1
    assert "behavior.network" in (tmp_path / "routine-sample-results.md").read_text()
    signals = []
    assert sample.main(["run", "--only", "nothing"]) == 0
    assert seen[-1] == []
    (tmp_path / "routine-holdout.json").write_text((tmp_path / "routine-sample.json").read_text())
    signals = []
    assert sample.main(["run", "--name", "routine-holdout"]) == 0
    assert (tmp_path / "routine-holdout-results.md").read_text().startswith("# routine-holdout: results")


def test_run_keeps_sample_order_and_disposes_the_engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Pairs run in parallel but come back in sample order, and the engine is disposed afterwards."""
    disposed: list[bool] = []
    engine = type("E", (), {"dispose": lambda self: disposed.append(True)})()
    monkeypatch.setattr(sample, "make_engine", lambda url: engine)
    monkeypatch.setattr(Services, "default", classmethod(lambda cls, cache: None))
    signal = {"rule_id": "names.lookalike", "level": "check", "message": "m"}
    monkeypatch.setattr(
        sample,
        "analyze_pair",
        lambda s, svc, p: {"package": p.package, "error": None, "artifacts": [{"kind": "wheel", "signals": [signal]}]},
    )
    pairs = [sample.SamplePair(f"p{i}", i, "1", "2", "2026-01-01") for i in range(5)]
    records = sample.run("postgresql://x", tmp_path, pairs, 3)
    assert [r["package"] for r in records] == [p.package for p in pairs] and disposed == [True]


def test_run_records_a_crash_and_carries_on(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An unexpected exception on one pair is recorded as that pair's error."""
    engine = type("E", (), {"dispose": lambda self: None})()
    monkeypatch.setattr(sample, "make_engine", lambda url: engine)
    monkeypatch.setattr(Services, "default", classmethod(lambda cls, cache: None))

    def boom(*a: Any) -> dict[str, Any]:
        raise UnicodeEncodeError("utf-8", "x", 0, 1, "surrogates not allowed")

    monkeypatch.setattr(sample, "analyze_pair", boom)
    [record] = sample.run("postgresql://x", tmp_path, [PAIR], 1)
    assert record["error"].startswith("crashed: UnicodeEncodeError") and record["artifacts"] == []
