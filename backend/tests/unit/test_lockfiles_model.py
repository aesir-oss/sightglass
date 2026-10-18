"""Tests for the lockfile model shared by the parsers."""

from sightglass.lockfiles.model import Dependency, LockedPackage, Lockfile, Resolution

ORBIT = LockedPackage(
    "conda",
    "orbit-client",
    "2.5.0",
    "https://conda.example/orbit-client-2.5.0.conda",
    (Dependency("conda", "kestrel-core"), Dependency("conda", "missing-dep"), Dependency("conda", "orbit-client")),
    (("pypi", "orbit-client"),),
)
KESTREL = LockedPackage("conda", "kestrel-core", "1.4.0", "https://conda.example/kestrel-core-1.4.0.conda")
HERON = LockedPackage(
    "pypi",
    "heron-sdk",
    "3.1.0",
    "https://files.example/heron_sdk-3.1.0-py3-none-any.whl",
    (Dependency("pypi", "orbit-client"), Dependency("pypi", "kestrel-core", "extra == 'fast'")),
)
RES = Resolution("default", "linux-64", (ORBIT, KESTREL, HERON))


def test_find_by_name_or_by_what_a_package_provides() -> None:
    """A PyPI name is found as itself or as the conda package that provides it."""
    assert RES.find("conda", "kestrel-core") is KESTREL
    assert RES.find("pypi", "orbit-client") is ORBIT
    assert RES.find("pypi", "kestrel-core") is None
    assert ORBIT.key == ("conda", "orbit-client")


def test_edges_resolve_within_the_resolution() -> None:
    """Edges point at packages in the same resolution; missing targets and self-references are left out."""
    edges = {(a.name, b.name, d.marker) for a, b, d in RES.edges()}
    assert edges == {("orbit-client", "kestrel-core", None), ("heron-sdk", "orbit-client", None)}


def test_lockfile_resolution_lookup() -> None:
    """A resolution is found by environment and platform."""
    lock = Lockfile("pixi.lock", (RES,))
    assert lock.resolution("default", "linux-64") is RES
    assert lock.resolution("default", "osx-arm64") is None
