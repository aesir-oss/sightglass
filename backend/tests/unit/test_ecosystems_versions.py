"""Tests for choosing a release's predecessor and a project's latest release by version."""

from datetime import UTC, datetime

from sightglass.ecosystems.pypi import PypiFile, PypiProject, PypiRelease
from sightglass.ecosystems.versions import is_downgrade, latest, predecessor, stable


def release(version: str, month: int | None, *, yanked: bool = False) -> PypiRelease:
    """A release with one file, published in ``month`` of 2026 (no files when None)."""
    if month is None:
        return PypiRelease(version, ())
    uploaded = datetime(2026, month, 1, tzinfo=UTC)
    f = PypiFile(f"p-{version}.tar.gz", "https://x", "0" * 64, 1, uploaded, "sdist", yanked, None, None)
    return PypiRelease(version, (f,))


def project(*releases: PypiRelease) -> PypiProject:
    """A project with these releases, in publish order."""
    return PypiProject("orbit-client", "orbit-client", {}, None, None, releases)


# 2.4.2 backports a fix to the 2.4 line after 2.5.0 came out.
ORBIT = project(
    release("2.4.0", 1),
    release("2.4.1", 2),
    release("2.5.0rc1", 3),
    release("2.5.0", 4),
    release("2.4.2", 5),
    release("2.5.1", 6, yanked=True),
    release("2.6.0a1", 7),
)


def test_a_backport_is_compared_with_the_version_before_it() -> None:
    """The predecessor is the highest stable, unyanked version below, not the release published before it."""
    assert {v: getattr(predecessor(ORBIT, v), "version", None) for v in ("2.4.2", "2.5.0", "2.4.0")} == {
        "2.4.2": "2.4.1",
        # 2.4.2 came out after 2.5.0, so when 2.5.0 was released its predecessor was 2.4.1.
        "2.5.0": "2.4.1",
        "2.4.0": None,
    }


def test_prereleases_and_yanked_releases_are_skipped_when_something_else_is_below() -> None:
    """A pre-release compares with the stable release below it; with nothing stable below, any lower version."""
    assert getattr(predecessor(ORBIT, "2.6.0a1"), "version", None) == "2.5.0"
    only_pre = project(release("1.0a1", 1), release("1.0", 2))
    assert getattr(predecessor(only_pre, "1.0"), "version", None) == "1.0a1"


def test_published_later_is_not_a_predecessor_when_something_earlier_qualifies() -> None:
    """A lower version published after this one (a later backport) isn't its default predecessor."""
    late = project(release("1.0", 1), release("2.0", 2), release("1.1", 3))
    assert getattr(predecessor(late, "2.0"), "version", None) == "1.0"


def test_versions_that_dont_parse_fall_back_to_publish_order() -> None:
    """An invalid version's predecessor is the release published just before it; unknown versions have none."""
    odd = project(release("1.0", 1), release("banana", 2))
    assert getattr(predecessor(odd, "banana"), "version", None) == "1.0"
    assert predecessor(project(release("banana", 1)), "banana") is None
    assert predecessor(ORBIT, "9.9") is None


def test_latest_is_the_highest_stable_version() -> None:
    """The latest release is the highest stable, unyanked version, else the highest, else the last published."""
    assert getattr(latest(ORBIT), "version", None) == "2.5.0"
    assert getattr(latest(project(release("1.0a1", 1))), "version", None) == "1.0a1"
    assert getattr(latest(project(release("banana", 1))), "version", None) == "banana"
    assert latest(project()) is None
    assert stable("2.5.0") is not None and stable("2.5.0rc1") is None and stable("banana") is None
    assert getattr(predecessor(project(release("1.0", None), release("2.0", 1)), "2.0"), "version", None) == "1.0"


def test_downgrades_by_ecosystem() -> None:
    """A move to an older version is a downgrade, by PEP 440 for PyPI and conda's rules for conda."""
    assert is_downgrade("pypi", "2.1.5", "2.0.55")
    assert not is_downgrade("pypi", "2.0.55", "2.1.5")
    assert not is_downgrade("pypi", "banana", "2.0")
    assert is_downgrade("conda", "1.26.4", "1.26.4a1")
    assert not is_downgrade("conda", "3.14.0", "3.14.1")
    assert not is_downgrade("conda", "", "1.0")
