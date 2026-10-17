"""Tests for the source match rules."""

import pytest

from sightglass import _core
from sightglass.ecosystems.sources import CouldNotCompare
from sightglass.rules.base import PairAnalysis, ReleaseFacts
from sightglass.rules.pairing import SourceCheck, SourceComparison
from sightglass.rules.ruleset import RULES
from sightglass.rules.source import differs_from_tag, not_in_sdist, not_in_tag

MATCHES = SourceCheck("orbit/__init__.py", "matches", "src/orbit/__init__.py")
TELEMETRY = SourceCheck("orbit/telemetry.py", "missing", None)
SPEEDUPS = SourceCheck("orbit/_speedups.so", "missing", None, text=False)
CLIENT = SourceCheck("orbit/client.py", "differs", "src/orbit/client.py")


def analysis(
    source: SourceComparison | CouldNotCompare | None = None,
    sdist: SourceComparison | None = None,
    source_diffs: dict[str, _core.FileDiff] | None = None,
    label: str | None = "tag v2.5.0",
) -> PairAnalysis:
    """An orbit-client pair with the given source comparisons."""
    return PairAnalysis(
        "pypi",
        "orbit-client",
        ReleaseFacts("2.4.1"),
        ReleaseFacts("2.5.0"),
        source=source,
        source_label=label,
        source_diffs=source_diffs or {},
        sdist=sdist,
    )


def comparison(*checks: SourceCheck) -> SourceComparison:
    """A source comparison with the given checks."""
    return SourceComparison("src/", checks, ())


def test_registered() -> None:
    """The source rules are in the full rule set."""
    assert {"source.not_in_tag", "source.differs_from_tag", "source.not_in_sdist"} <= {r.id for r in RULES}


def test_file_not_in_tag() -> None:
    """A text file missing from the tag is high; compiled files are left to the binaries rules."""
    [signal] = not_in_tag(analysis(comparison(MATCHES, TELEMETRY, SPEEDUPS)))
    assert (signal.level, signal.message) == ("high", "orbit/telemetry.py isn't in tag v2.5.0")
    assert [e.to_json() for e in signal.evidence] == [{"file": "orbit/telemetry.py", "side": "new"}]


def test_many_files_are_one_signal_naming_the_first_five() -> None:
    """Many missing files are one signal with an evidence item each."""
    missing = [SourceCheck(f"orbit/m{i}.py", "missing", None) for i in range(7)]
    [signal] = not_in_tag(analysis(comparison(*missing), label=None))
    assert signal.message == (
        "7 package files aren't in the source: orbit/m0.py, orbit/m1.py, orbit/m2.py, orbit/m3.py, orbit/m4.py, "
        "and 2 more"
    )
    assert len(signal.evidence) == 7


def test_differs_with_diff_hunks_as_evidence() -> None:
    """A differing file names the source path and points at the package lines that differ."""
    tag = b"".join(f"line {i}\n".encode() for i in range(1, 21))
    wheel = (
        tag.replace(b"line 3\n", b"import socket\nimport ssl\n").replace(b"line 18\n", b"").replace(b"line 9\n", b"x\n")
    )
    diff = _core.diff_lines(tag, wheel)
    [signal] = differs_from_tag(analysis(comparison(CLIENT, MATCHES), source_diffs={"orbit/client.py": diff}))

    assert signal.message == "orbit/client.py differs from src/orbit/client.py in tag v2.5.0"
    # Runs of added lines become ranges; the removal of line 18 has no package lines to point at.
    assert [e.to_json() for e in signal.evidence] == [
        {"file": "orbit/client.py", "line_start": 3, "line_end": 4, "side": "new"},
        {"file": "orbit/client.py", "line_start": 10, "line_end": 10, "side": "new"},
    ]


def test_differs_without_a_diff_or_with_only_removals() -> None:
    """With no diff (binary-safe fallback) or a removal-only diff, the file itself is the evidence."""
    removal = _core.diff_lines(b"a\nb\n", b"a\n")
    other = SourceCheck("orbit/other.py", "differs", "src/orbit/other.py")
    [signal] = differs_from_tag(analysis(comparison(CLIENT, other), source_diffs={"orbit/other.py": removal}))
    assert signal.message == "2 package files differ from tag v2.5.0: orbit/client.py, orbit/other.py"
    assert [e.to_json() for e in signal.evidence] == [
        {"file": "orbit/client.py", "side": "new"},
        {"file": "orbit/other.py", "side": "new"},
    ]


def test_not_in_sdist() -> None:
    """A wheel file the sdist doesn't have is high."""
    [signal] = not_in_sdist(analysis(sdist=comparison(MATCHES, TELEMETRY, SPEEDUPS)))
    assert signal.message == "orbit/telemetry.py is in the wheel but not in the sdist"
    two = not_in_sdist(analysis(sdist=comparison(TELEMETRY, SourceCheck("orbit/extra.py", "missing", None))))
    assert two[0].message == "2 files are in the wheel but not in the sdist: orbit/telemetry.py, orbit/extra.py"


@pytest.mark.parametrize(
    "source",
    [
        None,
        CouldNotCompare("no_matching_tag", "no tag matched"),
        CouldNotCompare("repository_unreachable", "503"),
        comparison(MATCHES, SPEEDUPS),
    ],
)
def test_no_signal_without_a_comparison_or_differences(source: SourceComparison | CouldNotCompare | None) -> None:
    """Unknown or uncomparable sources, and sources that match, report nothing."""
    a = analysis(source, sdist=None if source is None else comparison(MATCHES, SPEEDUPS))
    assert not_in_tag(a) == differs_from_tag(a) == not_in_sdist(a) == []
