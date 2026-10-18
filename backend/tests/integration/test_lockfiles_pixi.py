"""Tests for the pixi.lock parser against an invented lockfile."""

from pathlib import Path

import pytest

from sightglass.lockfiles import pixi
from sightglass.lockfiles.model import Dependency
from sightglass.lockfiles.pixi import LockfileError, parse_pixi_lock

FIXTURE = Path(__file__).parents[1] / "fixtures" / "lockfiles" / "pixi.lock"


@pytest.mark.integration
def test_conda_and_pypi_packages_per_platform() -> None:
    """Each environment and platform gets its packages, conda and PyPI, with normalized names and versions."""
    lock = parse_pixi_lock(FIXTURE.read_bytes())
    assert lock.format == "pixi.lock"
    assert [(r.environment, r.platform) for r in lock.resolutions] == [
        ("default", "linux-64"),
        ("default", "osx-arm64"),
    ]
    linux = lock.resolution("default", "linux-64")
    mac = lock.resolution("default", "osx-arm64")
    assert linux is not None and mac is not None
    assert {(p.ecosystem, p.name, p.version) for p in linux.packages} == {
        ("conda", "orbit-client", "2.5.0"),
        ("conda", "kestrel-core", "1.4.0"),
        ("conda", "tidepool", "0.9.1"),
        ("conda", "python", "3.14.0"),
        ("pypi", "heron-sdk", "3.1.0"),
    }
    assert mac.find("conda", "tidepool") is None


@pytest.mark.integration
def test_dependencies_and_edges() -> None:
    """Match specs and requirements become dependencies; virtual packages are dropped; purls connect ecosystems."""
    linux = parse_pixi_lock(FIXTURE.read_bytes()).resolution("default", "linux-64")
    assert linux is not None
    orbit = linux.find("conda", "orbit-client")
    heron = linux.find("pypi", "heron-sdk")
    assert orbit is not None and heron is not None
    assert [d.name for d in orbit.dependencies] == ["kestrel-core", "python", "tidepool"]
    assert orbit.provides == (("pypi", "orbit-client"),)
    assert heron.dependencies == (
        Dependency("pypi", "orbit-client"),
        Dependency("pypi", "kestrel-core", 'extra == "fast"'),
        Dependency("pypi", "pyobjc", 'sys_platform == "darwin"'),
    )
    edges = {(a.name, b.name) for a, b, _ in linux.edges()}
    assert edges == {
        ("orbit-client", "kestrel-core"),
        ("orbit-client", "python"),
        ("orbit-client", "tidepool"),
        ("kestrel-core", "python"),
        ("heron-sdk", "orbit-client"),
        ("heron-sdk", "kestrel-core"),
    }


@pytest.mark.integration
def test_unreadable_or_oversized_lockfiles(monkeypatch: pytest.MonkeyPatch) -> None:
    """Content py-rattler can't parse, or more than the size limit, is a LockfileError."""
    with pytest.raises(LockfileError, match="couldn't be read"):
        parse_pixi_lock(b"version: 6\npackages: [1, 2]\n")
    monkeypatch.setattr(pixi, "MAX_LOCKFILE_SIZE", 10)
    with pytest.raises(LockfileError, match="over the 10 limit"):
        parse_pixi_lock(FIXTURE.read_bytes())


@pytest.mark.integration
def test_malformed_requirement_makes_the_lockfile_unreadable() -> None:
    """py-rattler checks requirements itself, so a malformed one fails the whole lockfile with a clear reason."""
    text = FIXTURE.read_text().replace("  - pyobjc ; sys_platform == 'darwin'\n", "  - '!!not a requirement'\n")
    with pytest.raises(LockfileError, match="requirement parsing failed"):
        parse_pixi_lock(text.encode())
