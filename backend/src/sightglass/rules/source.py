"""Source match rules: package files that aren't in the source they were built from, or differ from it.

Only text files are reported here. Compiled files are never in the source, and the binaries rules report them. When
the source couldn't be fetched the result is "couldn't compare" on the page, never a signal.
"""

from collections.abc import Sequence

from sightglass import _core
from sightglass.rules import pyast
from sightglass.rules.base import RULES, Evidence, PairAnalysis, Signal
from sightglass.rules.pairing import SourceCheck, SourceComparison

# Files named in a message; the evidence lists every one.
NAMED = 5
# Line ranges given as evidence for one differing file.
MAX_RANGES = 20


def _names(checks: Sequence[SourceCheck]) -> str:
    named = ", ".join(c.path for c in checks[:NAMED])
    return named + (f", and {len(checks) - NAMED} more" if len(checks) > NAMED else "")


def _files(comparison: SourceComparison | None, status: str) -> list[SourceCheck]:
    if comparison is None:
        return []
    return [c for c in comparison.files if c.status == status and c.text]


def _added_ranges(diff: _core.FileDiff | None) -> list[tuple[int, int]]:
    return pyast.line_ranges(line for line, _ in diff.added_lines())[:MAX_RANGES] if diff else []


def _source(analysis: PairAnalysis) -> SourceComparison | None:
    return analysis.source if isinstance(analysis.source, SourceComparison) else None


@RULES.rule("source.not_in_tag", 2, "A package file in the wheel isn't in the git tag")
def not_in_tag(analysis: PairAnalysis) -> list[Signal]:
    """Report the package's text files that aren't anywhere in the source tree."""
    missing = _files(_source(analysis), "missing")
    if not missing:
        return []
    where = analysis.source_label or "the source"
    message = (
        f"{missing[0].path} isn't in {where}"
        if len(missing) == 1
        else f"{len(missing)} package files aren't in {where}: {_names(missing)}"
    )
    return [Signal("source.not_in_tag", "high", message, tuple(Evidence(c.path, side="new") for c in missing))]


@RULES.rule("source.differs_from_tag", 2, "A package file differs from the same path in the git tag")
def differs_from_tag(analysis: PairAnalysis) -> list[Signal]:
    """Report the package's text files whose content differs from the source, with the lines only the package has."""
    differs = _files(_source(analysis), "differs")
    if not differs:
        return []
    evidence: list[Evidence] = []
    for c in differs:
        ranges = _added_ranges(analysis.source_diffs.get(c.path))
        if not ranges:
            evidence.append(Evidence(c.path, side="new"))
        evidence += [Evidence(c.path, start, end, "new") for start, end in ranges]
    where = analysis.source_label or "the source"
    message = (
        f"{differs[0].path} differs from {differs[0].source_path} in {where}"
        if len(differs) == 1
        else f"{len(differs)} package files differ from {where}: {_names(differs)}"
    )
    return [Signal("source.differs_from_tag", "high", message, tuple(evidence))]


@RULES.rule("source.not_in_sdist", 1, "The wheel contains a file the sdist doesn't")
def not_in_sdist(analysis: PairAnalysis) -> list[Signal]:
    """Report the wheel's text files that aren't in the release's sdist."""
    missing = _files(analysis.sdist, "missing")
    if not missing:
        return []
    message = (
        f"{missing[0].path} is in the wheel but not in the sdist"
        if len(missing) == 1
        else f"{len(missing)} files are in the wheel but not in the sdist: {_names(missing)}"
    )
    return [Signal("source.not_in_sdist", "high", message, tuple(Evidence(c.path, side="new") for c in missing))]
