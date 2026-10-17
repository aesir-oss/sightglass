"""Tests for the lookalike-name rule, against an invented top-packages list."""

import pytest

from sightglass.rules import names
from sightglass.rules.base import PairAnalysis, ReleaseFacts, Rule, RuleSet
from sightglass.rules.names import edit_distance, lookalike, lookalike_name
from sightglass.rules.ruleset import RULES
from sightglass.rules.top_packages import TopPackages, load, parse_tsv

TOP = ("orbit-client", "kestrel-weather-sdk", "tidepool", "gale", "harbor-lights")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("orbit-clinet", ("orbit-client", 1)),
        ("Orbit_Clientt", ("orbit-client", 1)),
        ("orbitclient", ("orbit-client", 0)),
        ("orbit.client", None),
        ("kestrel-weathr-sdkk", ("kestrel-weather-sdk", 2)),
        ("tidepol", ("tidepool", 1)),
        ("tidpeool", ("tidepool", 1)),
        ("tidepl", None),
        ("gael", None),
        ("harborlights", ("harbor-lights", 0)),
        ("lantern", None),
    ],
)
def test_lookalike(name: str, expected: tuple[str, int] | None) -> None:
    """Separators, one edit (two for long names) and adjacent swaps match; short names and the package itself don't."""
    assert lookalike(name, TOP) == expected


def test_closest_and_most_popular_wins() -> None:
    """The smallest distance wins, then the higher-ranked name."""
    assert lookalike("tidepoal", ("tidepools", "tidepool")) == ("tidepool", 1)
    assert lookalike("tidepoo1", ("tidepoo2", "tidepoo3")) == ("tidepoo2", 1)


def test_known_forks_are_excluded(monkeypatch: pytest.MonkeyPatch) -> None:
    """A listed pair of related projects isn't a lookalike."""
    monkeypatch.setattr(names, "KNOWN_FORKS", frozenset({frozenset({"tidepools", "tidepool"})}))
    assert lookalike("tidepools", TOP) is None


@pytest.mark.parametrize(
    ("a", "b", "limit", "expected"), [("abc", "abc", 1, 0), ("abc", "acb", 1, 1), ("ab", "abcd", 1, 2)]
)
def test_edit_distance(a: str, b: str, limit: int, expected: int) -> None:
    """Distances stop counting once over the limit."""
    assert edit_distance(a, b, limit) == expected
    assert edit_distance("aaaaaa", "bbbbbb", 2) == 3


def analysis(package: str, ecosystem: str = "pypi") -> PairAnalysis:
    """A pair for ``package``."""
    return PairAnalysis(ecosystem, package, ReleaseFacts("1.0"), ReleaseFacts("1.1"))


def test_rule_message_and_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """The signal is check, naming the popular package, its rank and the list date."""
    monkeypatch.setattr(names, "_TOP", TopPackages("2026-10-01", TOP))
    [signal] = lookalike_name(analysis("Orbit_Clinet"))
    assert (signal.level, signal.message) == (
        "check",
        "`orbit-clinet` is 1 edit from `orbit-client`, number 1 by PyPI downloads (list from 2026-10-01)",
    )
    assert signal.evidence[0].to_json() == {"before": "orbit-client", "after": "orbit-clinet"}
    two = lookalike_name(analysis("kestrel-weathr-sdkk"))
    assert "is 2 edits from `kestrel-weather-sdk`, number 2" in two[0].message
    seps = lookalike_name(analysis("harborlights"))
    assert "differs only in separators from `harbor-lights`" in seps[0].message
    assert lookalike_name(analysis("orbit-client")) == lookalike_name(analysis("orbit-clinet", "conda-forge")) == []


def test_committed_list_and_rule_set_version() -> None:
    """The committed list loads, and its date is part of the rule's manifest and so of the rule-set version."""
    top = load()
    assert len(top.names) >= 2500 and len(set(top.names)) == len(top.names)
    rule = next(r for r in RULES if r.id == "name.lookalike")
    assert rule.manifest == f"name.lookalike@1+top-{top.queried_at}"
    assert RuleSet([rule]).version != RuleSet([Rule(rule.id, rule.version, rule.summary, rule.check)]).version


def test_parse_tsv() -> None:
    """Rows are normalized and deduplicated; malformed rows are skipped."""
    body = b"Orbit_Client\t900\norbit-client\t5\nbad name\t3\ntidepool\tmany\n\nkestrel.weather\t1\n"
    assert parse_tsv(body) == ["orbit-client", "kestrel-weather"]
