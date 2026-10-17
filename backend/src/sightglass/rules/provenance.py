"""Provenance and publisher rules: attestations that disappear, and publishers that change.

A publisher's identity is its kind, repository and workflow; the deployment environment is left to other rules.
Repositories compare case-insensitively, as GitHub and GitLab treat them. Provenance that is unknown (``None``) never
fires a rule; only an index answer of "absent" does.
"""

from dataclasses import dataclass

from sightglass.ecosystems.provenance import Provenance, Publisher
from sightglass.rules.base import RULES, Evidence, PairAnalysis, ReleaseFacts, Signal

# Recent releases that must agree on one publisher before a different one is reported.
RECENT = 3
MIN_RECENT = 2


@dataclass(frozen=True)
class Identity:
    """Who published a release, for comparison."""

    kind: str
    repository: str | None
    workflow: str | None

    @classmethod
    def of(cls, publisher: Publisher) -> Identity:
        """The identity of an attestation's publisher."""
        repo = publisher.repository.lower() if publisher.repository else None
        return cls(publisher.kind, repo, publisher.workflow)

    def describe(self) -> str:
        """``release.yml`` in ``owner/repo`` (GitHub), or as much of that as is known."""
        if self.workflow and self.repository:
            return f"`{self.workflow}` in `{self.repository}` ({self.kind})"
        return self.repository or self.kind


def identities(provenance: Provenance) -> frozenset[Identity]:
    """Every publisher identity that attested an artifact."""
    return frozenset(Identity.of(a.publisher) for a in provenance.attestations)


def _describe(ids: frozenset[Identity]) -> str:
    return ", ".join(sorted(i.describe() for i in ids))


@RULES.rule("provenance.attestation_dropped", 1, "Attestation present in the previous release, missing in this one")
def attestation_dropped(analysis: PairAnalysis) -> list[Signal]:
    """Fire when the old artifact was attested and the index says the new one isn't."""
    old, new = analysis.old.provenance, analysis.new.provenance
    if old is None or new is None or old.status != "present" or new.status != "absent":
        return []
    return [
        Signal(
            "provenance.attestation_dropped",
            "high",
            f"{analysis.new.version} has no attestation; {analysis.old.version} was attested by "
            f"{_describe(identities(old))}",
            (Evidence(attestation_field="attestation", before="present", after="absent"),),
        )
    ]


@RULES.rule("provenance.publisher_changed", 1, "Attestation publisher identity changed: repository or workflow")
def publisher_changed(analysis: PairAnalysis) -> list[Signal]:
    """Fire when both artifacts are attested and no publisher identity is shared."""
    old, new = analysis.old.provenance, analysis.new.provenance
    if old is None or new is None:
        return []
    before, after = identities(old), identities(new)
    if not before or not after or before & after:
        return []
    evidence = []
    for name in ("kind", "repository", "workflow"):
        was = {str(getattr(i, name)) for i in before}
        now = {str(getattr(i, name)) for i in after}
        if was != now:
            evidence.append(
                Evidence(
                    attestation_field=f"publisher.{name}", before=", ".join(sorted(was)), after=", ".join(sorted(now))
                )
            )
    return [
        Signal(
            "provenance.publisher_changed",
            "high",
            f"{analysis.new.version} was attested by {_describe(after)}; {analysis.old.version} was attested by "
            f"{_describe(before)}",
            tuple(evidence),
        )
    ]


def _established(history: tuple[ReleaseFacts, ...]) -> tuple[Identity, list[str]] | None:
    known = [r for r in history if r.provenance is not None][-RECENT:]
    if len(known) < MIN_RECENT:
        return None
    shared = frozenset.intersection(*(identities(r.provenance) for r in known if r.provenance is not None))
    if len(shared) != 1:
        return None
    return next(iter(shared)), [r.version for r in known]


@RULES.rule("publisher.not_recent_publisher", 1, "Not published through the trusted publisher of recent releases")
def not_recent_publisher(analysis: PairAnalysis) -> list[Signal]:
    """Fire when recent releases agree on a publisher that neither release of the pair was attested by.

    When the previous release has the established publisher, the pair rules above already describe any change.
    """
    old, new = analysis.old.provenance, analysis.new.provenance
    established = _established(analysis.history)
    if established is None or old is None or new is None:
        return []
    publisher, versions = established
    if publisher in identities(old) or publisher in identities(new):
        return []
    attested = f"attested by {_describe(identities(new))}" if new.status == "present" else "not attested"
    return [
        Signal(
            "publisher.not_recent_publisher",
            "high",
            f"{analysis.new.version} is {attested}; {', '.join(versions)} were all attested by {publisher.describe()}",
            (
                Evidence(
                    attestation_field="publisher",
                    before=publisher.describe(),
                    after=_describe(identities(new)) or "none",
                ),
            ),
        )
    ]
