"""Run the rule set over a sample of routine releases of popular packages, to find rules that fire on ordinary updates.

``pixi run sample select`` picks the sample from the committed top-packages list: for each package, the newest stable
release at least ``--min-age-days`` old that isn't yanked, and the highest stable release below it. ``pixi run sample
run`` analyzes every pair with the full pipeline and writes the signals by level as JSON and Markdown.
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version
from sqlalchemy.orm import Session

from sightglass.analyze import database
from sightglass.db.engine import make_engine
from sightglass.ecosystems.http import HttpError
from sightglass.ecosystems.pypi import PypiClient, PypiProject
from sightglass.log import configure_logging, get_logger
from sightglass.rules import top_packages
from sightglass.rules.base import LEVELS
from sightglass.rules.ruleset import RULES
from sightglass.worker.pipeline import (
    PairResult,
    PipelineError,
    Services,
    TransientError,
    analyze_release_pair,
    default_cache_dir,
)

log = get_logger("sightglass.sample")

RESEARCH = Path(__file__).resolve().parents[3] / "docs" / "research"
# The tuning sample; a held-out one is selected and run under another name, with no rule changes after it.
DEFAULT_NAME = "routine-sample"


def files(name: str) -> tuple[Path, Path, Path]:
    """The sample list, the per-pair results and the Markdown report for a named sample."""
    return RESEARCH / f"{name}.json", RESEARCH / f"{name}-results.json", RESEARCH / f"{name}-results.md"


@dataclass(frozen=True)
class SamplePair:
    """One routine release and the one before it."""

    package: str
    rank: int
    from_version: str
    to_version: str
    published: str


def _stable(version: str) -> Version | None:
    try:
        v = Version(version)
    except InvalidVersion:
        return None
    return None if v.is_prerelease or v.is_devrelease else v


def routine_pair(project: PypiProject, rank: int, cutoff: datetime) -> SamplePair | None:
    """The project's newest stable, unyanked release published before ``cutoff``, and the highest stable one below it.

    Args:
        project: The project and its releases.
        rank: The project's download rank.
        cutoff: Releases published after this are too new to count as routine.

    Returns:
        The pair, or None when the project has no such two releases.
    """
    candidates = [
        (v, r)
        for r in project.releases
        if (v := _stable(r.version)) is not None and not r.yanked and r.published_at and r.published_at <= cutoff
    ]
    if len(candidates) < 2:
        return None
    candidates.sort(key=lambda c: c[0])
    (_, old), (_, new) = candidates[-2], candidates[-1]
    assert new.published_at is not None  # filtered above
    return SamplePair(project.normalized_name, rank, old.version, new.version, new.published_at.date().isoformat())


def select(
    project: Callable[[str], PypiProject], names: Iterable[str], count: int, cutoff: datetime, first_rank: int = 1
) -> list[SamplePair]:
    """Walk ``names`` in download order from ``first_rank`` and keep the first ``count`` that have a routine pair."""
    pairs: list[SamplePair] = []
    for rank, name in enumerate(names, 1):
        if rank < first_rank:
            continue
        if len(pairs) == count:
            break
        try:
            pair = routine_pair(project(name), rank, cutoff)
        except HttpError as exc:
            log.warning("sample_package_skipped", package=name, error=str(exc))
            continue
        if pair is None:
            log.info("sample_package_without_pair", package=name)
            continue
        pairs.append(pair)
    return pairs


def analyze_pair(session: Session, services: Services, pair: SamplePair) -> dict[str, Any]:
    """Analyze one pair and return its record for the results file; failures are recorded, not raised."""
    try:
        results: list[PairResult] = analyze_release_pair(
            session, services, pair.package, pair.from_version, pair.to_version
        )
    except (PipelineError, TransientError) as exc:
        return {**asdict(pair), "error": str(exc), "artifacts": []}
    artifacts = [
        {
            "kind": r.kind,
            "new_filename": r.new_filename,
            "status": r.status,
            "error": r.error,
            "signals": [{k: s[k] for k in ("rule_id", "level", "message")} for s in r.signals],
        }
        for r in results
    ]
    return {**asdict(pair), "error": None, "artifacts": artifacts}


def summarize(records: Sequence[dict[str, Any]], ruleset_version: str, name: str = DEFAULT_NAME) -> str:
    """The Markdown report: counts by level and rule, then every signal at high or check, by package."""
    signals = [(rec, a, s) for rec in records for a in rec["artifacts"] for s in a["signals"]]
    by_level = Counter(s["level"] for _, _, s in signals)
    by_rule = Counter((s["level"], s["rule_id"]) for _, _, s in signals)
    failed = [rec for rec in records if rec["error"] or any(a["status"] == "failed" for a in rec["artifacts"])]
    lines = [
        f"# {name}: results",
        "",
        f"Generated by `pixi run sample run --name {name}` with rule set `{ruleset_version}`. The method is in"
        " [routine-sample.md](routine-sample.md).",
        "",
        f"- Pairs: {len(records)}; pairs that couldn't be fully analyzed: {len(failed)}",
        "- Signals by level: " + ", ".join(f"{lvl} {by_level.get(lvl, 0)}" for lvl in LEVELS if lvl != "clean"),
        "",
        "## Signals by rule",
        "",
        "| Level | Rule | Signals |",
        "|---|---|---|",
        *(
            f"| {lvl} | `{rule}` | {n} |"
            for (lvl, rule), n in sorted(by_rule.items(), key=lambda i: (LEVELS.index(i[0][0]), i[0][1]))
        ),
    ]
    for level in ("high", "check"):
        lines += ["", f"## {level.capitalize()} signals", ""]
        rows = [(rec, a, s) for rec, a, s in signals if s["level"] == level]
        lines += [
            f"- {rec['package']} {rec['from_version']} → {rec['to_version']} ({a['kind']}): `{s['rule_id']}` {s['message']}"
            for rec, a, s in rows
        ] or ["None."]
    lines += ["", "## Pairs not fully analyzed", ""]
    lines += [
        f"- {rec['package']} {rec['from_version']} → {rec['to_version']}: "
        + (rec["error"] or "; ".join(f"{a['kind']}: {a['error']}" for a in rec["artifacts"] if a["error"]))
        for rec in failed
    ] or ["None."]
    return "\n".join(lines) + "\n"


def run(url: str, cache: Path, pairs: Sequence[SamplePair], jobs: int) -> list[dict[str, Any]]:
    """Analyze the pairs ``jobs`` at a time, each worker with its own session and clients, in sample order."""
    engine = make_engine(url)

    def one(pair: SamplePair) -> dict[str, Any]:
        try:
            with Session(engine) as session:
                record = analyze_pair(session, Services.default(cache), pair)
        except Exception as exc:  # A crash on one pair is a finding to report, not a reason to stop the run.
            log.exception("sample_pair_crashed", package=pair.package, to=pair.to_version)
            record = {**asdict(pair), "error": f"crashed: {type(exc).__name__}: {exc}", "artifacts": []}
        for a in record["artifacts"]:
            for s in a["signals"]:
                if s["level"] in ("high", "check"):
                    log.info(
                        "sample_signal",
                        package=pair.package,
                        kind=a["kind"],
                        rule_id=s["rule_id"],
                        signal_level=s["level"],
                        message=s["message"],
                    )
        log.info("sample_pair_done", package=pair.package, to=pair.to_version, error=record["error"])
        return record

    try:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            return list(pool.map(one, pairs))
    finally:
        engine.dispose()


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(prog="sample", description="Run the rules over routine releases.")
    sub = parser.add_subparsers(dest="command", required=True)
    pick = sub.add_parser("select", help="pick the sample from the top-packages list")
    pick.add_argument("--name", default=DEFAULT_NAME, help="sample name, for its files in docs/research")
    pick.add_argument("--count", type=int, default=200)
    pick.add_argument("--first-rank", type=int, default=1, help="download rank to start from")
    pick.add_argument("--min-age-days", type=int, default=30)
    pick.add_argument("--today", type=date.fromisoformat, default=None, help="sampling date, default today")
    go = sub.add_parser("run", help="analyze the sample and write the results")
    go.add_argument("--name", default=DEFAULT_NAME, help="sample name, for its files in docs/research")
    go.add_argument("--jobs", type=int, default=4)
    go.add_argument("--only", nargs="*", default=None, help="analyze only these packages")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command; returns the process exit code (1 when a high signal remains)."""
    args = parse_args(argv)
    configure_logging()
    sample_file, results_file, report_file = files(args.name)
    if args.command == "select":
        today = args.today or datetime.now(UTC).date()
        cutoff = datetime.combine(today, datetime.min.time(), UTC) - timedelta(days=args.min_age_days)
        client = PypiClient.default()
        pairs = select(client.project, top_packages.load().names, args.count, cutoff, args.first_rank)
        doc = {"sampled_on": today.isoformat(), "min_age_days": args.min_age_days, "pairs": [asdict(p) for p in pairs]}
        sample_file.write_text(json.dumps(doc, indent=1) + "\n")
        log.info("sample_selected", pairs=len(pairs), file=str(sample_file))
        return 0
    sample = [SamplePair(**p) for p in json.loads(sample_file.read_text())["pairs"]]
    if args.only:
        sample = [p for p in sample if p.package in set(args.only)]
    cache = default_cache_dir()
    with database(cache) as url:
        records = run(url, cache, sample, args.jobs)
    if not args.only:
        results_file.write_text(json.dumps({"ruleset_version": RULES.version, "pairs": records}, indent=1) + "\n")
        report_file.write_text(summarize(records, RULES.version, args.name))
    high = sum(s["level"] == "high" for rec in records for a in rec["artifacts"] for s in a["signals"])
    log.info("sample_done", pairs=len(records), high=high)
    return 1 if high else 0


if __name__ == "__main__":
    sys.exit(main())
