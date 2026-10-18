"""Tests for diffing two lockfiles and finding why a package is there."""

from sightglass.lockfiles.diff import diff_lockfiles, shortest_path
from sightglass.lockfiles.model import Dependency, LockedPackage, Lockfile, Resolution


def pkg(name: str, version: str, *deps: str, first_party: bool = False) -> LockedPackage:
    """A PyPI package depending on ``deps``."""
    return LockedPackage(
        "pypi",
        name,
        version,
        "." if first_party else f"https://files.example/{name}-{version}.whl",
        tuple(Dependency("pypi", d) for d in deps),
        first_party=first_party,
    )


def lock(*resolutions: tuple[str, str, list[LockedPackage]]) -> Lockfile:
    """A lockfile from (environment, platform, packages)."""
    return Lockfile("pixi.lock", tuple(Resolution(e, p, tuple(ps)) for e, p, ps in resolutions))


BASE = lock(
    ("default", "linux-64", [pkg("orbit-client", "2.4.1", "kestrel"), pkg("kestrel", "1.4.0"), pkg("old", "1.0")]),
    ("default", "osx-arm64", [pkg("orbit-client", "2.4.1", "kestrel"), pkg("kestrel", "1.4.0"), pkg("old", "1.0")]),
)
HEAD = lock(
    (
        "default",
        "linux-64",
        [pkg("orbit-client", "2.5.0", "kestrel"), pkg("kestrel", "1.5.0", "telemetry"), pkg("telemetry", "0.1")],
    ),
    ("default", "osx-arm64", [pkg("orbit-client", "2.5.0", "kestrel"), pkg("kestrel", "1.5.0")]),
    ("test", "linux-64", [pkg("probe", "8.0")]),
)


def test_changes_are_merged_across_platforms_and_environments() -> None:
    """One entry per change, with where it happens and whether some of an environment's platforms lack it."""
    changes = diff_lockfiles(BASE, HEAD, lambda env: {("pypi", "orbit-client")} if env == "default" else set())
    summary = [(c.kind, c.name, c.from_version, c.to_version, c.environments, c.platforms) for c in changes]
    assert summary == [
        ("added", "probe", None, "8.0", ("test",), ("linux-64",)),
        ("added", "telemetry", None, "0.1", ("default",), ("linux-64",)),
        ("changed", "kestrel", "1.4.0", "1.5.0", ("default",), ("linux-64", "osx-arm64")),
        ("changed", "orbit-client", "2.4.1", "2.5.0", ("default",), ("linux-64", "osx-arm64")),
        ("removed", "old", "1.0", None, ("default",), ("linux-64", "osx-arm64")),
    ]
    by_name = {c.name: c for c in changes}
    assert by_name["telemetry"].only_some_platforms and not by_name["kestrel"].only_some_platforms
    assert by_name["telemetry"].path == ("orbit-client", "kestrel", "telemetry")
    assert by_name["orbit-client"].path == ("orbit-client",)
    # A package the declared dependencies don't reach has no path; with none declared (the test environment),
    # packages nothing depends on are the roots.
    assert by_name["old"].path == ()
    assert by_name["probe"].path == ("probe",)


def test_first_party_members_start_paths_and_are_not_changes() -> None:
    """A workspace member's own dependencies are where paths start, and the member's version bump isn't listed."""
    member = pkg("orbit-platform", "2.0", "orbit-client", first_party=True)
    base = lock(("default", "linux-64", [member, pkg("orbit-client", "2.4.1")]))
    bumped = pkg("orbit-platform", "2.1", "orbit-client", first_party=True)
    head = lock(("default", "linux-64", [bumped, pkg("orbit-client", "2.5.0", "kestrel"), pkg("kestrel", "1.0")]))
    changes = diff_lockfiles(base, head, lambda env: ())
    assert [(c.name, c.path) for c in changes] == [
        ("kestrel", ("orbit-client", "kestrel")),
        ("orbit-client", ("orbit-client",)),
    ]


def test_unreachable_package_has_no_path() -> None:
    """A package no root reaches has an empty path rather than a guess."""
    a, b = pkg("a", "1", "b"), pkg("b", "1", "a")
    cycle = Resolution("default", "linux-64", (a, b))
    assert shortest_path(cycle, b, ()) == ()
    assert shortest_path(cycle, b, [("pypi", "a")]) == ("a", "b")
