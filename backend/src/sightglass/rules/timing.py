"""Timing rules: very recent releases, and releases after a long silence."""

from datetime import datetime, timedelta
from itertools import pairwise
from statistics import median

from sightglass.rules.base import RULES, Evidence, PairAnalysis, Signal

RECENT = timedelta(days=7)
LONG_GAP = timedelta(days=365)
# With at least this many earlier gaps, a long gap must also be this many times their median.
CADENCE_GAPS = 3
CADENCE_FACTOR = 3


def _day(t: datetime) -> str:
    return t.date().isoformat()


@RULES.rule("timing.recent", 1, "Published in the last 7 days")
def recent(analysis: PairAnalysis) -> list[Signal]:
    """Report a release published less than 7 days before the analysis ran."""
    published, now = analysis.new.published_at, analysis.analyzed_at
    if published is None or now is None or not timedelta(0) <= now - published < RECENT:
        return []
    days = (now - published).days
    age = "less than a day" if days == 0 else f"{days} day{'s' if days > 1 else ''}"
    return [
        Signal(
            "timing.recent",
            "check",
            f"{analysis.new.version} was published on {_day(published)}, {age} before this analysis ({_day(now)})",
            (Evidence(after=published.isoformat()),),
        )
    ]


@RULES.rule("timing.long_gap", 1, "First release after a long gap")
def long_gap(analysis: PairAnalysis) -> list[Signal]:
    """Report a release that comes a year or more after the previous one, and well outside the project's cadence."""
    before, after = analysis.old.published_at, analysis.new.published_at
    if before is None or after is None or after - before < LONG_GAP:
        return []
    times = [r.published_at for r in analysis.history if r.published_at is not None] + [before]
    gaps = [(b - a).total_seconds() for a, b in pairwise(times)]
    if len(gaps) >= CADENCE_GAPS and (after - before).total_seconds() < CADENCE_FACTOR * median(gaps):
        return []
    return [
        Signal(
            "timing.long_gap",
            "note",
            f"{analysis.new.version} came {(after - before).days} days after {analysis.old.version} "
            f"({_day(before)} to {_day(after)})",
            (Evidence(before=before.isoformat(), after=after.isoformat()),),
        )
    ]
