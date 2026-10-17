"""Tests for sightglass._core archive types that need no disk."""

import pytest

from sightglass import _core


def test_limits_defaults_and_overrides() -> None:
    """Unset limits take the defaults; set ones override them."""
    default = _core.Limits()
    assert (default.max_files, default.max_ratio) == (100_000, 100)
    custom = _core.Limits(max_files=5)
    assert custom.max_files == 5
    assert custom.max_total_size == default.max_total_size
    assert custom != default
    assert _core.Limits(max_files=5) == custom


def test_limits_are_keyword_only_and_frozen() -> None:
    """Limits can't be passed positionally or changed after creation."""
    with pytest.raises(TypeError):
        _core.Limits(5)  # type: ignore[misc]
    with pytest.raises(AttributeError):
        _core.Limits().max_files = 1  # type: ignore[misc]


def test_error_hierarchy() -> None:
    """Refusals and format errors share a base class that isn't OSError."""
    assert issubclass(_core.UnsafeArchiveError, _core.ArchiveError)
    assert issubclass(_core.ArchiveFormatError, _core.ArchiveError)
    assert not issubclass(_core.ArchiveError, OSError)
