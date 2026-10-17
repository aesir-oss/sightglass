"""Tests for line diffs from the Rust core, through the Python bindings."""

import pytest

from sightglass import _core

OLD = b"".join(f"line {i}\n".encode() for i in range(1, 11))


def test_hunks_lines_and_counts() -> None:
    """Hunks carry their ranges and lines with line numbers on each side."""
    new = OLD.replace(b"line 5\n", b"line five\nline 5.5\n")
    result = _core.diff_lines(OLD, new)

    assert (result.too_large, result.added, result.removed, result.approximate) == (False, 2, 1, False)
    [hunk] = result.hunks
    assert (hunk.old_start, hunk.old_len, hunk.new_start, hunk.new_len) == (2, 7, 2, 8)
    assert [(line.kind, line.old_line, line.new_line, line.text) for line in hunk.lines[2:6]] == [
        ("context", 4, 4, "line 4"),
        ("removed", 5, None, "line 5"),
        ("added", None, 5, "line five"),
        ("added", None, 6, "line 5.5"),
    ]
    assert result.added_lines() == [(5, "line five"), (6, "line 5.5")]
    assert repr(hunk) == "Hunk(-2,7 +2,8)"
    assert repr(hunk.lines[3]) == "DiffLine(kind='removed', old_line=5, new_line=None, text=\"line 5\")"
    assert repr(result) == "FileDiff(too_large=False, hunks=1, added=2, removed=1)"


def test_identical_and_missing_newline() -> None:
    """Identical inputs have no hunks; a dropped final newline is a change that says so."""
    assert _core.diff_lines(OLD, OLD).hunks == []
    lines = _core.diff_lines(b"a\nb", b"a\nb\n").hunks[0].lines
    assert [(line.kind, line.missing_newline) for line in lines] == [
        ("context", False),
        ("removed", True),
        ("added", False),
    ]


def test_limits() -> None:
    """Defaults are exposed; inputs over a limit are too large rather than diffed; context is honored."""
    defaults = _core.DiffLimits()
    assert (defaults.max_size, defaults.max_lines, defaults.timeout, defaults.context) == (
        4 * 1024 * 1024,
        100_000,
        2.0,
        3,
    )

    too_large = _core.diff_lines(OLD, b"", _core.DiffLimits(max_size=10))
    assert (too_large.too_large, too_large.hunks, too_large.added_lines()) == (True, [], [])
    assert repr(too_large).startswith("FileDiff(too_large=True")
    assert _core.diff_lines(OLD, b"", _core.DiffLimits(max_lines=5)).too_large

    narrow = _core.diff_lines(OLD, OLD.replace(b"line 5\n", b"x\n"), _core.DiffLimits(context=0))
    assert [line.kind for line in narrow.hunks[0].lines] == ["removed", "added"]
    assert _core.DiffLimits(timeout=0.5) == _core.DiffLimits(timeout=0.5)


@pytest.mark.parametrize("timeout", [-1.0, 1e9, float("nan")])
def test_bad_timeout(timeout: float) -> None:
    """Timeouts must be a sane number of seconds."""
    with pytest.raises(ValueError, match="timeout"):
        _core.DiffLimits(timeout=timeout)
