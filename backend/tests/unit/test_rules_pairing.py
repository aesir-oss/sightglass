"""Tests for file pairing and the source check, on invented packages."""

import hashlib

import pytest

from sightglass.rules.pairing import (
    IndexedFile,
    check_source,
    normalize_path,
    pair_files,
    strip_top_level,
)


def f(path: str, content: str = "", *, text: bool = True, link: str | None = None) -> IndexedFile:
    """An indexed file whose hash is derived from ``content``; links have no hash."""
    sha = None if link else hashlib.sha256(content.encode()).hexdigest()
    return IndexedFile(path, sha, text, link)


WHEEL_OLD = [
    f("orbit/__init__.py", "VERSION = '2.4.1'"),
    f("orbit/client.py", "def get(): ..."),
    f("orbit/_speedups.so", "ELF-1", text=False),
    f("orbit/legacy.py", "old"),
    f("orbit_client-2.4.1.dist-info/METADATA", "Version: 2.4.1"),
    f("orbit_client-2.4.1.dist-info/RECORD", "..."),
]
WHEEL_NEW = [
    f("orbit/__init__.py", "VERSION = '2.5.0'"),
    f("orbit/client.py", "def get(): ..."),
    f("orbit/_speedups.so", "ELF-2", text=False),
    f("orbit/telemetry.py", "import socket"),
    f("orbit_client-2.5.0.dist-info/METADATA", "Version: 2.5.0"),
    f("orbit_client-2.5.0.dist-info/RECORD", "..."),
]


def test_pair_files_classifies_each_path() -> None:
    """Paths pair across versions, dist-info included, and each pair is added, removed, changed or same."""
    pairs = {p.path: p for p in pair_files(WHEEL_OLD, WHEEL_NEW)}

    assert {path: p.status for path, p in pairs.items()} == {
        "*.dist-info/METADATA": "changed",
        "*.dist-info/RECORD": "same",
        "orbit/__init__.py": "changed",
        "orbit/_speedups.so": "changed",
        "orbit/client.py": "same",
        "orbit/legacy.py": "removed",
        "orbit/telemetry.py": "added",
    }
    assert list(pairs) == sorted(pairs)
    assert pairs["orbit/__init__.py"].text and not pairs["orbit/_speedups.so"].text
    assert pairs["orbit/telemetry.py"].text and pairs["orbit/telemetry.py"].old is None


def test_text_needs_both_sides_text() -> None:
    """A file that turned from text into binary isn't line-diffed."""
    [pair] = pair_files([f("orbit/data.bin", "a")], [f("orbit/data.bin", "b", text=False)])
    assert (pair.status, pair.text) == ("changed", False)


def test_links_compare_by_target() -> None:
    """Links with no content hash are the same only when they point at the same place."""
    old = [f("docs", link="../docs"), f("README", link="README.md")]
    new = [f("docs", link="../docs"), f("README", link="/etc/passwd")]
    assert [(p.path, p.status) for p in pair_files(old, new)] == [("README", "changed"), ("docs", "same")]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("orbit_client-2.5.0.dist-info/METADATA", "*.dist-info/METADATA"),
        ("orbit_client-2.5.0.data/scripts/orbit", "*.data/scripts/orbit"),
        ("orbit/vendor/six-1.0.dist-info/METADATA", "orbit/vendor/six-1.0.dist-info/METADATA"),
        ("orbit/__init__.py", "orbit/__init__.py"),
    ],
)
def test_normalize_path(path: str, expected: str) -> None:
    """Only the wheel's own top-level dist-info and data directories are renamed."""
    assert normalize_path(path) == expected


def test_strip_top_level() -> None:
    """The sdist's name-version directory is removed; files at the top level keep their paths."""
    sdist = [f("orbit_client-2.5.0/PKG-INFO"), f("orbit_client-2.5.0/src/orbit/__init__.py")]
    assert [x.path for x in strip_top_level(sdist)] == ["PKG-INFO", "src/orbit/__init__.py"]
    flat = [f("setup.py"), f("orbit/__init__.py")]
    assert strip_top_level(flat) == flat


TAG = [
    f("src/orbit/__init__.py", "VERSION = '2.5.0'"),
    f("src/orbit/client.py", "def get(): ... # edited after tagging"),
    f("tests/orbit/client.py", "def test(): ..."),
    f("pyproject.toml", "[project]"),
]


def test_source_check_against_a_src_layout_tag() -> None:
    """Package files are found under src/, compared by content, and build metadata is excluded."""
    result = check_source(WHEEL_NEW, TAG)

    assert result.root == "src/"
    assert [(c.path, c.status, c.source_path) for c in result.files] == [
        ("orbit/__init__.py", "matches", "src/orbit/__init__.py"),
        ("orbit/_speedups.so", "missing", None),
        ("orbit/client.py", "differs", "src/orbit/client.py"),
        ("orbit/telemetry.py", "missing", None),
    ]
    assert result.excluded == ("orbit_client-2.5.0.dist-info/METADATA", "orbit_client-2.5.0.dist-info/RECORD")


def test_files_outside_the_main_root_are_still_found() -> None:
    """A single module at the repository root is found even when the package lives under src/."""
    wheel = [f("orbit/__init__.py", "a"), f("orbit/client.py", "b"), f("orbit_compat.py", "c")]
    source = [f("src/orbit/__init__.py", "a"), f("src/orbit/client.py", "b"), f("orbit_compat.py", "c")]
    result = check_source(wheel, source)
    assert result.root == "src/"
    assert [c.source_path for c in result.files] == ["src/orbit/__init__.py", "src/orbit/client.py", "orbit_compat.py"]


def test_data_scripts_and_purelib() -> None:
    """Files under .data/purelib install like top-level files; scripts keep their directory."""
    wheel = [
        f("orbit_client-2.5.0.data/purelib/orbit_extra.py", "x"),
        f("orbit_client-2.5.0.data/scripts/orbit", "#!python"),
    ]
    source = [f("orbit_extra.py", "x"), f("scripts/orbit", "#!/usr/bin/env python")]
    assert [(c.status, c.source_path) for c in check_source(wheel, source).files] == [
        ("matches", "orbit_extra.py"),
        ("differs", "scripts/orbit"),
    ]


def test_wheel_against_sdist_excludes_sdist_metadata() -> None:
    """The same check compares an sdist with its tag; PKG-INFO and egg-info are build output."""
    sdist = strip_top_level(
        [
            f("orbit_client-2.5.0/PKG-INFO"),
            f("orbit_client-2.5.0/src/orbit_client.egg-info/SOURCES.txt"),
            f("orbit_client-2.5.0/src/orbit/__init__.py", "VERSION = '2.5.0'"),
            f("orbit_client-2.5.0/pyproject.toml", "[project]"),
        ]
    )
    result = check_source(sdist, TAG)
    assert result.root == ""
    assert [(c.path, c.status) for c in result.files] == [
        ("pyproject.toml", "matches"),
        ("src/orbit/__init__.py", "matches"),
    ]
    assert result.excluded == ("PKG-INFO", "src/orbit_client.egg-info/SOURCES.txt")


def test_nothing_found() -> None:
    """With no source files in common every package file is missing and there is no root."""
    result = check_source([f("orbit/__init__.py")], [f("README.md")])
    assert (result.root, [c.status for c in result.files]) == ("", ["missing"])
