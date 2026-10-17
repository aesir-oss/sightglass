"""Tests that the installed package matches its metadata."""

from importlib.metadata import version

import pytest

import sightglass


@pytest.mark.integration
def test_version_matches_installed_metadata() -> None:
    """The package's version comes from the installed distribution's metadata."""
    assert sightglass.__version__ == version("sightglass")
