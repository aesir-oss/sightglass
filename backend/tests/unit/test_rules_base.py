"""Tests for the rule interface, the rule set and its version, and the signal model."""

import pytest

from sightglass.rules.base import (
    RULES,
    Evidence,
    PairAnalysis,
    ReleaseFacts,
    Rule,
    RuleSet,
    Signal,
)

ANALYSIS = PairAnalysis("pypi", "orbit-client", ReleaseFacts("2.4.1"), ReleaseFacts("2.5.0"))


def make_set() -> RuleSet:
    """A rule set with two invented rules."""
    rules = RuleSet()

    @rules.rule("timing.example", 1, "Fires once")
    def timing(analysis: PairAnalysis) -> list[Signal]:
        return [Signal("timing.example", "note", f"{analysis.new.version} has a version")]

    @rules.rule("files.example", 2, "Fires at high")
    def files(analysis: PairAnalysis) -> list[Signal]:
        return [Signal("files.example", "high", "orbit/telemetry.py isn't in tag v2.5.0", (Evidence("x.py", 1, 2),))]

    return rules


def test_run_orders_by_level() -> None:
    """Signals from every rule come back most severe first."""
    signals = make_set().run(ANALYSIS)
    assert [(s.rule_id, s.level) for s in signals] == [("files.example", "high"), ("timing.example", "note")]


def test_version_depends_on_ids_and_versions_only() -> None:
    """The version is stable across registration order and changes when a rule is added or bumped."""
    a, b = make_set(), make_set()
    assert a.version == b.version and a.version.startswith("rs-") and len(a.version) == 19
    b.add(Rule("timing.other", 1, "Another", lambda _: []))
    assert b.version != a.version
    bumped = RuleSet(
        Rule(r.id, r.version + 1 if r.id == "timing.example" else r.version, r.summary, r.check) for r in a
    )
    assert bumped.version != a.version
    assert [r.id for r in a] == ["files.example", "timing.example"] and len(a) == 2


@pytest.mark.parametrize(
    ("rule_id", "version", "match"),
    [("Timing.Example", 1, "lowercase"), ("timing", 1, "group.name"), ("timing.example", 0, "version")],
)
def test_bad_rules_are_refused(rule_id: str, version: int, match: str) -> None:
    """Ids are group.name in lowercase and versions start at 1."""
    with pytest.raises(ValueError, match=match):
        RuleSet([Rule(rule_id, version, "x", lambda _: [])])


def test_duplicate_ids_are_refused() -> None:
    """Two rules can't share an id."""
    rules = make_set()
    with pytest.raises(ValueError, match="duplicate"):
        rules.add(Rule("timing.example", 3, "again", lambda _: []))


def test_signal_must_name_its_rule() -> None:
    """A rule can't report a signal under another rule's id."""
    rule = Rule("timing.example", 1, "x", lambda _: [Signal("files.other", "note", "x")])
    with pytest.raises(ValueError, match=r"returned a signal for files\.other"):
        rule.run(ANALYSIS)


@pytest.mark.parametrize(
    "message",
    ["2.5.0 looks malicious", "Not SAFE to install", "suspicious file", "Possible backdoor in setup.py"],
)
def test_verdict_words_are_refused(message: str) -> None:
    """Messages describe what changed; verdict words are rejected."""
    with pytest.raises(ValueError, match="verdict"):
        Signal("files.example", "high", message)


def test_observations_are_accepted() -> None:
    """Words that only contain a verdict word, like safe_load, are fine."""
    assert Signal("files.example", "check", "New call to yaml.safe_load in orbit/config.py").level == "check"


def test_unknown_level_is_refused() -> None:
    """Only the four levels exist."""
    with pytest.raises(ValueError, match="level"):
        Signal("files.example", "critical", "x")  # type: ignore[arg-type]


def test_evidence_json_drops_unset_fields() -> None:
    """Evidence is stored without empty fields, as a list under ``items``."""
    signal = Signal(
        "provenance.example",
        "high",
        "The workflow changed from release.yml to publish.yml",
        (Evidence(attestation_field="publisher.workflow", before="release.yml", after="publish.yml"),),
    )
    assert signal.evidence_json() == {
        "items": [{"attestation_field": "publisher.workflow", "before": "release.yml", "after": "publish.yml"}]
    }
    assert Evidence("orbit/__init__.py", 3, side="new").to_json() == {
        "file": "orbit/__init__.py",
        "line_start": 3,
        "side": "new",
    }


@pytest.mark.parametrize(("file", "start", "end"), [(None, 1, 1), ("a.py", 0, 1), ("a.py", 5, 4)])
def test_bad_line_ranges(file: str | None, start: int, end: int) -> None:
    """Line ranges need a file and run forward from line 1."""
    with pytest.raises(ValueError, match="line range"):
        Evidence(file, start, end)


def test_shared_rule_set_exists() -> None:
    """Rules modules register on one shared set."""
    assert isinstance(RULES, RuleSet)
