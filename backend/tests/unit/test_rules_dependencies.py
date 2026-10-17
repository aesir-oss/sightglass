"""Tests for the dependency rules."""

import pytest

from sightglass.rules.base import PairAnalysis, ReleaseFacts
from sightglass.rules.dependencies import added, changed, environment_specific, read_requirements
from sightglass.rules.ruleset import RULES

HEADER = "Metadata-Version: 2.4\nName: orbit-client\nVersion: {version}\n"


def metadata(version: str, *requires: str) -> str:
    """A METADATA file with the given Requires-Dist lines."""
    return HEADER.format(version=version) + "".join(f"Requires-Dist: {r}\n" for r in requires) + "\nOrbit client.\n"


OLD = metadata("2.4.1", "requests>=2.31", "tidepool<4,>=3.1", "PyYAML>=6")


def pair(new: str, old: str = OLD, path: str = "*.dist-info/METADATA") -> PairAnalysis:
    """A pair whose metadata changed from ``old`` to ``new``."""
    return PairAnalysis(
        "pypi",
        "orbit-client",
        ReleaseFacts("2.4.1"),
        ReleaseFacts("2.5.0"),
        old_text={path: old},
        new_text={path: new},
    )


def test_registered() -> None:
    """The dependency rules are in the full rule set."""
    ids = {r.id for r in RULES}
    assert {"dependencies.added", "dependencies.environment_specific", "dependencies.changed"} <= ids


def test_new_dependency_is_check_with_its_line() -> None:
    """A new unconditional dependency is check, pointing at its Requires-Dist line."""
    new = metadata("2.5.0", "requests>=2.31", "tidepool<4,>=3.1", "PyYAML>=6", "kestrel-telemetry>=0.3")
    [signal] = added(pair(new))
    assert (signal.level, signal.message) == ("check", "2.5.0 adds a dependency on `kestrel-telemetry>=0.3`")
    assert signal.evidence[0].to_json() == {
        "file": "*.dist-info/METADATA",
        "line_start": 7,
        "line_end": 7,
        "side": "new",
        "after": "kestrel-telemetry>=0.3",
    }
    assert environment_specific(pair(new)) == []


def test_extras_are_named() -> None:
    """Dependencies of optional extras say which extras."""
    new = metadata("2.5.0", "requests>=2.31", "tidepool<4,>=3.1", "PyYAML>=6", 'pysocks; extra == "socks"')
    [signal] = added(pair(new))
    assert signal.message == '2.5.0 adds a dependency on `pysocks; extra == "socks"` for the `socks` extra'
    two = metadata(
        "2.5.0", "requests>=2.31", "tidepool<4,>=3.1", "PyYAML>=6", 'rich; extra == "cli"', 'rich; extra == "all"'
    )
    assert added(pair(two))[0].message.endswith("for the `all`, `cli` extras")


def test_environment_specific_dependency() -> None:
    """A new dependency limited by platform markers is its own check signal, not a plain new dependency."""
    new = metadata(
        "2.5.0", "requests>=2.31", "tidepool<4,>=3.1", "PyYAML>=6", 'kestrel-win-helper>=1; sys_platform == "win32"'
    )
    [signal] = environment_specific(pair(new))
    assert signal.level == "check"
    assert signal.message == '2.5.0 adds a dependency on `kestrel-win-helper` only when sys_platform == "win32"'
    assert added(pair(new)) == []


def test_constraint_changes_and_removals_are_notes() -> None:
    """Changed specifiers and dropped dependencies are notes; formatting differences aren't changes."""
    new = metadata("2.5.0", "requests >= 2.32", "tidepool>=3.1,<4")
    signals = changed(pair(new))
    assert [(s.level, s.message) for s in signals] == [
        ("note", "2.5.0 no longer depends on `pyyaml` (PyYAML>=6 in 2.4.1)"),
        ("note", "The `requests` requirement changed from `requests>=2.31` to `requests>=2.32`"),
    ]
    assert signals[1].evidence[0].before == "requests>=2.31"


def test_names_are_normalized() -> None:
    """Respelling a name or reordering specifiers isn't an addition, removal or change."""
    new = metadata("2.5.0", "Requests>=2.31", "Tidepool>=3.1,<4", "pyyaml>=6")
    assert added(pair(new)) == environment_specific(pair(new)) == changed(pair(new)) == []


def test_direct_reference_change() -> None:
    """Switching a dependency to a direct URL is a change."""
    new = metadata("2.5.0", "requests @ https://example.net/requests.whl", "tidepool<4,>=3.1", "PyYAML>=6")
    [signal] = changed(pair(new))
    assert signal.message == (
        "The `requests` requirement changed from `requests>=2.31` to `requests @ https://example.net/requests.whl`"
    )


def test_sdist_pkg_info_and_unknown_metadata() -> None:
    """PKG-INFO is read for sdists; without metadata on both sides nothing fires; bad lines are skipped."""
    new = metadata("2.5.0", "requests>=2.31", "tidepool<4,>=3.1", "PyYAML>=6", "kestrel-telemetry")
    assert len(added(pair(new, path="PKG-INFO"))) == 1
    unknown = pair(new)
    unknown.old_text.clear()
    assert added(unknown) == environment_specific(unknown) == changed(unknown) == []
    reqs = read_requirements({"PKG-INFO": metadata("1.0", "not a requirement !!", "tidepool")})
    assert reqs is not None and list(reqs.by_name) == ["tidepool"]


@pytest.mark.parametrize(
    "header",
    [
        "Metadata-Version: 2.1\n",
        "Metadata-Version: 2.4\nDynamic: Requires-Dist\n",
        "Metadata-Version: two\n",
    ],
)
def test_sdist_requirements_that_are_not_authoritative_are_unknown(header: str) -> None:
    """Before Metadata 2.2, or with Requires-Dist marked Dynamic, an sdist's PKG-INFO says nothing about dependencies."""
    old = header + "Name: orbit-client\nVersion: 2.4.1\n"
    new = metadata("2.5.0", "requests>=2.31", "kestrel-telemetry")
    analysis = pair(new, old=old, path="PKG-INFO")
    assert read_requirements({"PKG-INFO": old}) is None
    assert added(analysis) == changed(analysis) == []
