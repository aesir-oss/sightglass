"""Tests for sightglass.db.names."""

import pytest

from sightglass.db.names import normalize_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Orbit_Client", "orbit-client"),
        ("orbit.client", "orbit-client"),
        ("orbit--__..client", "orbit-client"),
        ("  Tidepool  ", "tidepool"),
        ("zstd-shim", "zstd-shim"),
    ],
)
def test_pypi_names_follow_pep503(raw: str, expected: str) -> None:
    """Separator runs collapse to one hyphen and letters are lowercased."""
    assert normalize_name("pypi", raw) == expected


def test_other_ecosystems_are_only_lowercased() -> None:
    """Separators are significant outside PyPI."""
    assert normalize_name("conda", "Rapid_CSV.x") == "rapid_csv.x"


@pytest.mark.parametrize("raw", ["", "   "])
def test_empty_names_are_rejected(raw: str) -> None:
    """An empty name is a caller error, not a package."""
    with pytest.raises(ValueError, match="empty"):
        normalize_name("pypi", raw)
