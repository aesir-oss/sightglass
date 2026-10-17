"""Source match rules: package files that aren't in the source they were built from, or differ from it.

Only text files are reported here. Compiled files are never in the source, and the binaries rules report them. When
the source couldn't be fetched the result is "couldn't compare" on the page, never a signal.

Code files this release added or changed are high. The rest are a note, with the reason in the message: a file the
build is known to produce (a submodule, a template's output, the same code with another version number), a file that
isn't code or isn't installed (see :mod:`sightglass.rules.scope`), one the previous release already had unchanged (a
pattern the project kept), one the previous release also shipped without a match in its own source, and generated
version files that only assign values.
"""

from collections.abc import Mapping, Sequence

from sightglass import _core
from sightglass.rules import pyast, scope
from sightglass.rules.base import RULES, Evidence, Level, PairAnalysis, Signal
from sightglass.rules.pairing import SourceCheck, SourceComparison, normalize_path

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


def _why_not_new(
    analysis: PairAnalysis, check: SourceCheck, statuses: Mapping[str, str], before: Mapping[str, SourceCheck]
) -> str | None:
    """Why a file isn't new installed code in this release, or None when it is."""
    path = normalize_path(check.path)
    if check.explained:
        return check.explained
    if (old := before.get(path)) is not None and old.status == check.status:
        return f"{'also not in' if check.status == 'missing' else 'also differed from'} the source of {analysis.old.version}"
    if scope.outside_package(analysis, path):
        return "not installed"
    if not scope.code_file(path):
        return "not code"
    if statuses.get(path) == "same":
        return f"unchanged since {analysis.old.version}"
    text = analysis.new_text.get(path)
    if path.endswith(".py") and text is not None:
        if scope.inert(text, path):
            return "only assigns values"
        if scope.versioneer(text, path):
            return "versioneer's generated version file"
    return None


def _by_level(
    analysis: PairAnalysis, checks: list[SourceCheck], previous: SourceComparison | None
) -> list[tuple[Level, list[SourceCheck], str]]:
    """Split the files into the high group and the note group, with the note's reasons for its message."""
    statuses = scope.statuses(analysis)
    before = {normalize_path(c.path): c for c in previous.files} if previous else {}
    high: list[SourceCheck] = []
    note: list[SourceCheck] = []
    reasons: dict[str, None] = {}
    for c in checks:
        if (why := _why_not_new(analysis, c, statuses, before)) is None:
            high.append(c)
        else:
            note.append(c)
            reasons[why] = None
    groups: list[tuple[Level, list[SourceCheck], str]] = []
    if high:
        groups.append(("high", high, ""))
    if note:
        groups.append(("note", note, f" ({', or '.join(reasons)})"))
    return groups


def _source(analysis: PairAnalysis) -> SourceComparison | None:
    return analysis.source if isinstance(analysis.source, SourceComparison) else None


@RULES.rule("source.not_in_tag", 5, "A package file in the wheel isn't in the git tag")
def not_in_tag(analysis: PairAnalysis) -> list[Signal]:
    """Report the package's text files that aren't anywhere in the source tree."""
    where = analysis.source_label or "the source"
    signals = []
    for level, missing, suffix in _by_level(analysis, _files(_source(analysis), "missing"), analysis.old_source):
        message = (
            f"{missing[0].path} isn't in {where}"
            if len(missing) == 1
            else f"{len(missing)} package files aren't in {where}: {_names(missing)}"
        )
        evidence = tuple(Evidence(c.path, side="new") for c in missing)
        signals.append(Signal("source.not_in_tag", level, message + suffix, evidence))
    return signals


@RULES.rule("source.differs_from_tag", 6, "A package file differs from the same path in the git tag")
def differs_from_tag(analysis: PairAnalysis) -> list[Signal]:
    """Report the package's text files whose content differs from the source, with the lines only the package has."""
    where = analysis.source_label or "the source"
    signals = []
    for level, differs, suffix in _by_level(analysis, _files(_source(analysis), "differs"), analysis.old_source):
        evidence: list[Evidence] = []
        for c in differs:
            ranges = _added_ranges(analysis.source_diffs.get(c.path))
            if not ranges:
                evidence.append(Evidence(c.path, side="new"))
            evidence += [Evidence(c.path, start, end, "new") for start, end in ranges]
        message = (
            f"{differs[0].path} differs from {differs[0].source_path} in {where}"
            if len(differs) == 1
            else f"{len(differs)} package files differ from {where}: {_names(differs)}"
        )
        signals.append(Signal("source.differs_from_tag", level, message + suffix, tuple(evidence)))
    return signals


@RULES.rule("source.not_in_sdist", 3, "The wheel contains a file the sdist doesn't")
def not_in_sdist(analysis: PairAnalysis) -> list[Signal]:
    """Report the wheel's text files that aren't in the release's sdist."""
    signals = []
    for level, missing, suffix in _by_level(analysis, _files(analysis.sdist, "missing"), analysis.old_sdist):
        message = (
            f"{missing[0].path} is in the wheel but not in the sdist"
            if len(missing) == 1
            else f"{len(missing)} files are in the wheel but not in the sdist: {_names(missing)}"
        )
        evidence = tuple(Evidence(c.path, side="new") for c in missing)
        signals.append(Signal("source.not_in_sdist", level, message + suffix, evidence))
    return signals
