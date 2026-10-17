"""Tests for the provenance and publisher rules, including unknown inputs that must not fire."""

import pytest

from sightglass.ecosystems.provenance import ABSENT, Attestation, CertificateClaims, Provenance, Publisher
from sightglass.rules.base import PairAnalysis, ReleaseFacts, Signal
from sightglass.rules.provenance import Identity, attestation_dropped, not_recent_publisher, publisher_changed
from sightglass.rules.ruleset import RULES

REPO = "kestrel-weather/orbit-client"


def attested(repository: str = REPO, workflow: str = "release.yml", kind: str = "GitHub") -> Provenance:
    """Provenance with one attestation from the given publisher."""
    publisher = Publisher(kind, repository, workflow)
    return Provenance("present", (Attestation(publisher, CertificateClaims(), None, ()),))


def pair(old: Provenance | None, new: Provenance | None, history: tuple[Provenance | None, ...] = ()) -> PairAnalysis:
    """A pair of orbit-client releases with the given provenance; history versions are 2.1.0, 2.2.0, ..."""
    earlier = tuple(ReleaseFacts(f"2.{i + 1}.0", provenance=p) for i, p in enumerate(history))
    return PairAnalysis(
        "pypi",
        "orbit-client",
        ReleaseFacts("2.4.1", provenance=old),
        ReleaseFacts("2.5.0", provenance=new),
        history=earlier,
    )


def messages(signals: list[Signal]) -> list[str]:
    """The messages of some signals."""
    return [s.message for s in signals]


def test_rules_are_registered() -> None:
    """The full rule set includes the provenance rules."""
    ids = {r.id for r in RULES}
    assert {"provenance.attestation_dropped", "provenance.publisher_changed", "publisher.not_recent_publisher"} <= ids


def test_attestation_dropped() -> None:
    """An attested release followed by an unattested one is high, naming the earlier publisher."""
    [signal] = attestation_dropped(pair(attested(), ABSENT))
    assert signal.level == "high"
    assert signal.message == (
        "2.5.0 has no attestation; 2.4.1 was attested by `release.yml` in `kestrel-weather/orbit-client` (GitHub)"
    )
    assert signal.evidence[0].to_json() == {"attestation_field": "attestation", "before": "present", "after": "absent"}


@pytest.mark.parametrize(
    ("old", "new"),
    [(None, ABSENT), (attested(), None), (ABSENT, ABSENT), (attested(), attested()), (ABSENT, attested())],
)
def test_attestation_dropped_does_not_fire(old: Provenance | None, new: Provenance | None) -> None:
    """Unknown provenance, never-attested projects and newly attested releases don't fire."""
    assert attestation_dropped(pair(old, new)) == []


def test_workflow_change() -> None:
    """A different workflow in the same repository is a publisher change, with the field as evidence."""
    [signal] = publisher_changed(pair(attested(), attested(workflow="publish.yml")))
    assert signal.level == "high"
    assert [e.to_json() for e in signal.evidence] == [
        {"attestation_field": "publisher.workflow", "before": "release.yml", "after": "publish.yml"}
    ]


def test_repository_and_kind_change() -> None:
    """Moving to another repository and forge reports each changed field."""
    [signal] = publisher_changed(pair(attested(), attested("kestrel/orbit", kind="GitLab")))
    assert [e.attestation_field for e in signal.evidence] == ["publisher.kind", "publisher.repository"]
    assert "`release.yml` in `kestrel/orbit` (GitLab)" in signal.message


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (attested(), attested(REPO.upper())),
        (None, attested("kestrel/fork")),
        (attested(), None),
        (ABSENT, attested("kestrel/fork")),
        (attested(), ABSENT),
    ],
)
def test_publisher_changed_does_not_fire(old: Provenance | None, new: Provenance | None) -> None:
    """Case-only repository differences, unknown provenance and missing attestations aren't publisher changes."""
    assert publisher_changed(pair(old, new)) == []


def test_shared_publisher_among_several_is_no_change() -> None:
    """When the new artifact keeps one of the old publishers, nothing changed for this rule."""
    both = Provenance("present", attested().attestations + attested(workflow="publish.yml").attestations)
    assert publisher_changed(pair(both, attested())) == []


def test_not_recent_publisher_when_both_releases_differ() -> None:
    """Three releases by one workflow, then two by another: the pair rules see no change, this rule does."""
    fork = attested("kestrel/orbit-fork")
    signals = not_recent_publisher(pair(fork, fork, (attested(), attested(), attested())))
    assert messages(signals) == [
        "2.5.0 is attested by `release.yml` in `kestrel/orbit-fork` (GitHub); 2.1.0, 2.2.0, 2.3.0 were all attested "
        "by `release.yml` in `kestrel-weather/orbit-client` (GitHub)"
    ]


def test_not_recent_publisher_after_an_unattested_release() -> None:
    """Attested history, then two unattested releases: reported as not attested."""
    [signal] = not_recent_publisher(pair(ABSENT, ABSENT, (attested(), attested())))
    assert signal.message.startswith("2.5.0 is not attested; 2.1.0, 2.2.0 were all attested by")
    assert signal.evidence[0].after == "none"


@pytest.mark.parametrize(
    ("old", "new", "history"),
    [
        (attested(), ABSENT, (attested(), attested())),
        (ABSENT, attested(), (attested(), attested())),
        (ABSENT, ABSENT, (attested(),)),
        (ABSENT, ABSENT, (attested(), ABSENT, attested())),
        (ABSENT, ABSENT, (attested(), attested(workflow="publish.yml"))),
        (ABSENT, ABSENT, (None, attested(), None)),
        (None, ABSENT, (attested(), attested())),
        (ABSENT, None, (attested(), attested())),
        (ABSENT, ABSENT, ()),
    ],
)
def test_not_recent_publisher_does_not_fire(
    old: Provenance | None, new: Provenance | None, history: tuple[Provenance | None, ...]
) -> None:
    """No signal when a pair rule covers it, history has no consistent publisher, or provenance is unknown."""
    assert not_recent_publisher(pair(old, new, history)) == []


def test_only_the_last_three_known_releases_count() -> None:
    """An old publisher from before the recent releases doesn't define the pattern."""
    history = (attested("kestrel/old-home"), attested(), attested(), attested())
    assert not_recent_publisher(pair(ABSENT, attested("kestrel/old-home"), history)) != []
    assert not_recent_publisher(pair(ABSENT, attested(), history)) == []


def test_ruleset_run_combines_rules() -> None:
    """Running the full set on a dropped attestation reports it once."""
    signals = [s for s in RULES.run(pair(attested(), ABSENT, (attested(), attested()))) if s.level != "clean"]
    assert [s.rule_id for s in signals] == ["provenance.attestation_dropped"]


def test_publisher_without_workflow_is_described_by_what_is_known() -> None:
    """Publishers with no workflow (such as Google service accounts) fall back to repository, then kind."""
    google = Provenance("present", (Attestation(Publisher("Google", None, None), CertificateClaims(), None, ()),))
    [signal] = publisher_changed(pair(attested(), google))
    assert signal.message.startswith("2.5.0 was attested by Google; ")
    assert Identity.of(Publisher("GitLab", "Kestrel/Orbit", None)).describe() == "kestrel/orbit"
