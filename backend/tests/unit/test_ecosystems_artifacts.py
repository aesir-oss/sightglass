"""Tests for choosing which files of two releases to compare."""

from datetime import UTC, datetime

import pytest

from sightglass.ecosystems.artifacts import ArtifactPair, platform_key, select_artifacts
from sightglass.ecosystems.pypi import ArtifactKind, PypiFile, PypiRelease

LINUX = "manylinux_2_17_x86_64.manylinux2014_x86_64"


def file(filename: str) -> PypiFile:
    """A file of a release; the kind follows the extension, like the index's packagetype."""
    kind: ArtifactKind = (
        "wheel" if filename.endswith(".whl") else "sdist" if filename.endswith((".tar.gz", ".zip")) else "other"
    )
    return PypiFile(
        filename=filename,
        url=f"https://files.pythonhosted.org/packages/{filename}",
        sha256="0" * 64,
        size=1,
        uploaded_at=datetime(2026, 10, 1, tzinfo=UTC),
        kind=kind,
        yanked=False,
        yanked_reason=None,
        requires_python=None,
    )


def release(version: str, *filenames: str) -> PypiRelease:
    """A release with the named files."""
    return PypiRelease(version, tuple(file(name) for name in filenames))


def names(pairs: tuple[ArtifactPair, ...]) -> list[tuple[str, str]]:
    """The (old, new) file names of some pairs."""
    return [(p.old.filename, p.new.filename) for p in pairs]


def test_pure_wheel_and_sdist() -> None:
    """A pure-Python project compares its sdists and its py3-none-any wheels."""
    old = release("2.4.1", "orbit_client-2.4.1.tar.gz", "orbit_client-2.4.1-py3-none-any.whl")
    new = release("2.5.0", "orbit_client-2.5.0.tar.gz", "orbit_client-2.5.0-py3-none-any.whl")
    selection = select_artifacts(old, new)

    assert names(selection.chosen) == [
        ("orbit_client-2.4.1.tar.gz", "orbit_client-2.5.0.tar.gz"),
        ("orbit_client-2.4.1-py3-none-any.whl", "orbit_client-2.5.0-py3-none-any.whl"),
    ]
    assert selection.sdist is not None and selection.sdist.kind == "sdist"
    assert selection.wheel is not None and selection.wheel.match == "same_tag"
    assert selection.unpaired_old == selection.unpaired_new == ()


def test_platform_wheels_prefer_linux_x86_64_and_keep_alternatives() -> None:
    """With only platform wheels the default is manylinux x86_64; every same-tag pair is offered, best first."""
    tags = [f"cp313-cp313-{LINUX}", "cp313-cp313-macosx_11_0_arm64", "cp313-cp313-win_amd64", "cp312-cp312-win32"]
    old = release("1.0", *(f"tidepool-1.0-{t}.whl" for t in tags))
    new = release("1.1", *(f"tidepool-1.1-{t}.whl" for t in reversed(tags)))
    selection = select_artifacts(old, new)

    assert names(selection.wheels) == [(f"tidepool-1.0-{t}.whl", f"tidepool-1.1-{t}.whl") for t in tags]
    assert selection.sdist is None
    assert selection.chosen == (selection.wheels[0],)


def test_pure_wheel_wins_over_platform_wheels() -> None:
    """A py3-none-any wheel is preferred to platform wheels, and py2.py3 wheels include it."""
    old = release("1.0", f"tidepool-1.0-cp313-cp313-{LINUX}.whl", "tidepool-1.0-py2.py3-none-any.whl")
    new = release("1.1", f"tidepool-1.1-cp313-cp313-{LINUX}.whl", "tidepool-1.1-py2.py3-none-any.whl")
    wheel = select_artifacts(old, new).wheel
    assert wheel is not None and wheel.new.filename == "tidepool-1.1-py2.py3-none-any.whl"


def test_abi3_then_newest_cpython_break_ties() -> None:
    """On the same platform an abi3 wheel comes first, then the newest CPython."""
    tags = [f"cp312-cp312-{LINUX}", f"cp314-cp314-{LINUX}", f"cp310-abi3-{LINUX}"]
    old = release("1.0", *(f"tidepool-1.0-{t}.whl" for t in tags))
    new = release("1.1", *(f"tidepool-1.1-{t}.whl" for t in tags))
    assert [p.new.filename for p in select_artifacts(old, new).wheels] == [
        f"tidepool-1.1-{t}.whl" for t in (tags[2], tags[1], tags[0])
    ]


def test_platform_tag_change_pairs_same_os_and_arch() -> None:
    """A move to a newer manylinux or CPython still pairs wheels for the same OS and architecture, marked as such."""
    old = release(
        "1.0",
        "tidepool-1.0-cp312-cp312-manylinux2014_x86_64.whl",
        "tidepool-1.0-cp312-cp312-macosx_10_9_x86_64.whl",
        "tidepool-1.0.tar.gz",
    )
    new = release(
        "1.1",
        "tidepool-1.1-cp313-cp313-manylinux_2_28_x86_64.whl",
        "tidepool-1.1-cp313-cp313-macosx_11_0_arm64.whl",
        "tidepool-1.1.tar.gz",
    )
    selection = select_artifacts(old, new)

    assert names(selection.wheels) == [
        ("tidepool-1.0-cp312-cp312-manylinux2014_x86_64.whl", "tidepool-1.1-cp313-cp313-manylinux_2_28_x86_64.whl")
    ]
    assert selection.wheels[0].match == "platform_changed"
    assert [f.filename for f in selection.unpaired_old] == ["tidepool-1.0-cp312-cp312-macosx_10_9_x86_64.whl"]
    assert [f.filename for f in selection.unpaired_new] == ["tidepool-1.1-cp313-cp313-macosx_11_0_arm64.whl"]


def test_same_tag_pairs_come_before_platform_changes() -> None:
    """A wheel with an exact match is never paired by platform, and exact pairs rank first."""
    old = release(
        "1.0", "tidepool-1.0-cp313-cp313-macosx_11_0_arm64.whl", "tidepool-1.0-cp312-cp312-manylinux2014_x86_64.whl"
    )
    new = release(
        "1.1", "tidepool-1.1-cp313-cp313-macosx_11_0_arm64.whl", "tidepool-1.1-cp313-cp313-manylinux_2_28_x86_64.whl"
    )
    assert [p.match for p in select_artifacts(old, new).wheels] == ["same_tag", "platform_changed"]


def test_wheel_only_in_one_release() -> None:
    """When only the new release has a wheel, the sdists are compared and the wheel is reported unpaired."""
    old = release("2.4.1", "orbit_client-2.4.1.tar.gz")
    new = release("2.5.0", "orbit_client-2.5.0.tar.gz", "orbit_client-2.5.0-py3-none-any.whl")
    selection = select_artifacts(old, new)

    assert selection.wheel is None
    assert names(selection.chosen) == [("orbit_client-2.4.1.tar.gz", "orbit_client-2.5.0.tar.gz")]
    assert [f.filename for f in selection.unpaired_new] == ["orbit_client-2.5.0-py3-none-any.whl"]


def test_sdist_only_in_one_release() -> None:
    """Without an sdist on both sides only wheels are compared."""
    old = release("2.4.1", "orbit_client-2.4.1-py3-none-any.whl")
    new = release("2.5.0", "orbit_client-2.5.0.tar.gz", "orbit_client-2.5.0-py3-none-any.whl")
    selection = select_artifacts(old, new)

    assert selection.sdist is None
    assert [f.filename for f in selection.unpaired_new] == ["orbit_client-2.5.0.tar.gz"]


def test_tar_gz_sdist_preferred_and_others_left_out() -> None:
    """Old releases with both .zip and .tar.gz sdists use the .tar.gz; eggs and bad wheel names are left out."""
    old = release("0.9", "tidepool-0.9.zip", "tidepool-0.9.tar.gz", "tidepool-0.9-py3.8.egg", "not-a-wheel.whl")
    new = release("1.0", "tidepool-1.0.tar.gz")
    selection = select_artifacts(old, new)

    assert names(selection.chosen) == [("tidepool-0.9.tar.gz", "tidepool-1.0.tar.gz")]
    assert [f.filename for f in selection.unpaired_old] == [
        "tidepool-0.9.zip",
        "tidepool-0.9-py3.8.egg",
        "not-a-wheel.whl",
    ]


def test_empty_releases() -> None:
    """Releases with no files have nothing to compare."""
    selection = select_artifacts(release("1.0"), release("1.1"))
    assert (selection.chosen, selection.wheels, selection.unpaired_old) == ((), (), ())


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("any", ("any", "any")),
        ("manylinux1_x86_64", ("manylinux", "x86_64")),
        ("manylinux_2_28_aarch64", ("manylinux", "aarch64")),
        ("musllinux_1_2_x86_64", ("musllinux", "x86_64")),
        ("linux_armv7l", ("linux", "armv7l")),
        ("macosx_10_9_universal2", ("macosx", "universal2")),
        ("win32", ("win", "x86")),
        ("win_arm64", ("win", "arm64")),
        ("ios_13_0_arm64_iphoneos", ("ios_13_0_arm64_iphoneos", "")),
    ],
)
def test_platform_key(platform: str, expected: tuple[str, str]) -> None:
    """Platform tags reduce to OS family and architecture."""
    assert platform_key(platform) == expected


def test_other_pure_wheels_rank_after_py3_but_before_platforms() -> None:
    """A pure wheel without the py3 tag still beats platform wheels."""
    tags = [f"cp313-cp313-{LINUX}", "py2-none-any", "py3-none-any"]
    old = release("1.0", *(f"tidepool-1.0-{t}.whl" for t in tags))
    new = release("1.1", *(f"tidepool-1.1-{t}.whl" for t in tags))
    assert [p.new.filename for p in select_artifacts(old, new).wheels] == [
        f"tidepool-1.1-{t}.whl" for t in (tags[2], tags[1], tags[0])
    ]


def test_each_new_wheel_gets_one_pair_with_its_closest_old_wheel() -> None:
    """A downgrade across Python versions pairs each new wheel once, with the same build flavor and nearest CPython."""
    old = release(
        "2.1",
        "tidepool-2.1-cp315-cp315-win_amd64.whl",
        "tidepool-2.1-cp315-cp315t-win_amd64.whl",
        "tidepool-2.1-cp313-cp313-win_amd64.whl",
    )
    new = release("2.0", "tidepool-2.0-cp310-cp310-win_amd64.whl", "tidepool-2.0-cp39-cp39-win_amd64.whl")
    wheels = select_artifacts(old, new).wheels
    assert len({p.new.filename for p in wheels}) == len(wheels) == 2
    assert {p.new.filename: p.old.filename for p in wheels} == {
        "tidepool-2.0-cp310-cp310-win_amd64.whl": "tidepool-2.1-cp313-cp313-win_amd64.whl",
        "tidepool-2.0-cp39-cp39-win_amd64.whl": "tidepool-2.1-cp313-cp313-win_amd64.whl",
    }
    threaded = release("2.0", "tidepool-2.0-cp314-cp314t-win_amd64.whl")
    [pair] = select_artifacts(old, threaded).wheels
    assert pair.old.filename == "tidepool-2.1-cp315-cp315t-win_amd64.whl"
