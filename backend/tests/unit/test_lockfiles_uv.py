"""Tests for the uv.lock parser, expanded per platform, against an invented workspace."""

from pathlib import Path

import pytest

from sightglass.lockfiles import uv
from sightglass.lockfiles.pixi import LockfileError
from sightglass.lockfiles.uv import parse_uv_lock

FIXTURE = (Path(__file__).parents[1] / "fixtures" / "lockfiles" / "uv.lock").read_bytes()


def packages(platform: str, content: bytes = FIXTURE) -> dict[str, tuple[str, str]]:
    """Name to (version, file name) of what one platform installs."""
    res = parse_uv_lock(content).resolution("default", platform)
    assert res is not None
    return {p.name: (p.version, p.location.rsplit("/", 1)[-1]) for p in res.packages}


def test_one_resolution_per_platform() -> None:
    """Each platform gets the packages its markers reach, as the pixi parser's model."""
    lock = parse_uv_lock(FIXTURE)
    assert lock.format == "uv.lock"
    assert [(r.environment, r.platform) for r in lock.resolutions] == [
        ("default", "linux-64"),
        ("default", "osx-arm64"),
        ("default", "win-64"),
    ]
    assert "tinted" in packages("win-64") and "tinted" not in packages("linux-64")


def test_members_extras_groups_and_forks() -> None:
    """The walk starts at the workspace members, follows requested extras and dev groups, and picks forks by edge."""
    linux = packages("linux-64")
    assert {"orbit-platform", "orbit-cli", "orbit-core"} <= linux.keys()
    assert linux["quickhash"][0] == "0.3.0" and "neverused" not in linux
    assert linux["probe"][0] == "8.0.0"
    assert linux["heron"][0] == "1.9.0"
    newer = FIXTURE.replace(b'requires-python = ">=3.12"', b'requires-python = ">=3.13"')
    assert packages("linux-64", newer)["heron"][0] == "2.0.0"


def test_each_platform_records_the_artifact_it_installs() -> None:
    """A universal wheel, else a fitting wheel for this Python, abi3 or any, else the sdist, else the source path."""
    assert packages("linux-64")["kestrel"][1].endswith("manylinux2014_x86_64.whl")
    assert packages("osx-arm64")["kestrel"][1].endswith("macosx_11_0_arm64.whl")
    assert packages("win-64")["kestrel"][1].endswith("win_amd64.whl")
    assert packages("linux-64")["orbit-core"][1] == "core"
    abi3 = FIXTURE.replace(b"cp312-cp312-manylinux", b"cp39-abi3-manylinux")
    assert "abi3" in packages("linux-64", abi3)["kestrel"][1]
    no_wheels = FIXTURE.replace(b"manylinux_2_17_x86_64.manylinux2014_x86_64", b"musllinux_1_2_aarch64")
    assert packages("linux-64", no_wheels)["kestrel"][1] == "kestrel-1.4.0.tar.gz"


def test_dependencies_keep_their_markers() -> None:
    """A package's dependencies are those that apply on the platform, with markers kept for the review."""
    win = parse_uv_lock(FIXTURE).resolution("default", "win-64")
    assert win is not None
    core = win.find("pypi", "orbit-core")
    assert core is not None
    assert [(d.name, d.marker) for d in core.dependencies] == [
        ("heron", "python_full_version < '3.13'"),
        ("tinted", "sys_platform == 'win32'"),
    ]
    assert ("orbit-cli", "kestrel") in {(a.name, b.name) for a, b, _ in win.edges()}


@pytest.mark.parametrize(
    ("requires", "expected"),
    [(">=3.11", "3.11"), (">=3.10, <4", "3.10"), ("~=3.13.1", "3.13"), ("<4", "3.14"), (None, "3.14")],
)
def test_python_floor(requires: str | None, expected: str) -> None:
    """The lowest Python the project allows, or 3.14 when it names none."""
    assert uv._python_floor(requires) == expected


def test_unreadable_marker_is_treated_as_holding() -> None:
    """A marker packaging can't read doesn't hide a dependency."""
    bad = FIXTURE.replace(b"marker = \"sys_platform == 'win32'\"", b'marker = "sys_platform =="')
    assert "tinted" in packages("linux-64", bad)


@pytest.mark.parametrize("content", [b"not toml = [", b"version = 1\n", b"\xff\xfe", b'version = "1"\n[[package]]\n'])
def test_unreadable_lockfiles(content: bytes) -> None:
    """Content that isn't a uv lockfile is a LockfileError."""
    with pytest.raises(LockfileError):
        parse_uv_lock(content)


def test_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """A lockfile over the size limit isn't parsed."""
    monkeypatch.setattr(uv, "MAX_LOCKFILE_SIZE", 10)
    with pytest.raises(LockfileError, match="over the 10 limit"):
        parse_uv_lock(FIXTURE)
