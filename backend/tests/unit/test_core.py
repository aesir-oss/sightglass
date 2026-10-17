"""Tests for the Rust extension module sightglass._core."""

from sightglass import __version__, _core


def test_core_version_matches_package_version() -> None:
    """The Rust core and the Python package are versioned together."""
    assert _core.version() == __version__
