"""Tests for the Rust extension module sightglass._core."""

import pytest

from sightglass import __version__, _core


def test_core_version_matches_package_version() -> None:
    """The Rust core and the Python package are versioned together."""
    assert _core.version() == __version__


def test_head_size() -> None:
    """Callers know how many leading bytes classification looks at."""
    assert _core.HEAD_SIZE == 8192


@pytest.mark.parametrize(
    ("name", "head", "expected"),
    [
        ("orbit/__init__.py", b"import os\n", ("python", "python", "utf-8")),
        ("bin/orbit", b"#!/usr/bin/env python3\n", ("python", "python", "utf-8")),
        ("README.md", b"\xef\xbb\xbf# Orbit\n", ("text", "text", "utf-8-sig")),
        ("orbit/_speedups.so", b"\x7fELF\x02\x01", ("compiled", "elf", None)),
        ("orbit/_speedups.pyd", b"MZ\x90\x00", ("compiled", "pe", None)),
        ("vendor/payload.bin", b"\x1f\x8b\x08\x00", ("archive", "gzip", None)),
        ("data/blob", b"\x00\x01\x02", ("other", "binary", None)),
    ],
)
def test_classify(name: str, head: bytes, expected: tuple[str, str, str | None]) -> None:
    """Classification uses the leading bytes first and the name only to spot Python."""
    t = _core.classify(name, head)
    assert (t.category, t.format, t.encoding) == expected


def test_file_type_is_immutable_and_comparable() -> None:
    """FileType values compare by content and can't be modified."""
    a = _core.classify("a.py", b"x = 1\n")
    assert a == _core.classify("b.py", b"y = 2\n")
    assert repr(a) == "FileType(category='python', format='python', encoding='utf-8')"
    with pytest.raises(AttributeError):
        a.category = "text"  # type: ignore[misc]
