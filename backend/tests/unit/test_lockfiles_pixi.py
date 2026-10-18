"""Unit tests for the pixi.lock parser's helpers."""

from sightglass.lockfiles.model import Dependency
from sightglass.lockfiles.pixi import _conda_dependencies, _provides, _pypi_dependencies


def test_conda_specs_to_names() -> None:
    """The name is taken from each match spec; virtual packages and unparsable specs are dropped."""
    deps = _conda_dependencies(["Kestrel-Core >=1.2", "tidepool 0.9.*", "__glibc >=2.17", ">=oops"])
    assert deps == (Dependency("conda", "kestrel-core"), Dependency("conda", "tidepool"))


def test_unreadable_python_requirement_is_skipped() -> None:
    """A requirement packaging can't read is logged and skipped."""
    deps = _pypi_dependencies(["Orbit_Client>=2.4", "!!not a requirement"], "heron-sdk")
    assert deps == (Dependency("pypi", "orbit-client"),)


def test_provides_from_pypi_purls() -> None:
    """PyPI purls name the projects a conda package installs; other purls are ignored."""
    record = '{"purls": ["pkg:pypi/Orbit_Client?source=hash-mapping", "pkg:npm/orbit", "pkg:pypi/orbit-client"]}'
    assert _provides(record) == (("pypi", "orbit-client"),)
    assert _provides("{}") == ()
