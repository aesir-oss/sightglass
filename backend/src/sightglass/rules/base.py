"""The rule interface: pure functions from a pair analysis to signals, and the versioned set they belong to.

A rule's ``version`` is bumped whenever what it reports changes. The rule-set version is derived from every rule's id
and version, and analyses are stored under it, so changing, adding or removing a rule makes stored analyses stale.
Message wording follows docs/rules.md: observations, never verdicts.
"""

import hashlib
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

from sightglass import _core
from sightglass.ecosystems.provenance import Provenance
from sightglass.ecosystems.sources import CouldNotCompare
from sightglass.rules.pairing import FilePair, SourceComparison

Level = Literal["high", "check", "note", "clean"]
LEVELS: tuple[Level, ...] = ("high", "check", "note", "clean")

_RULE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
_VERDICT_WORDS = re.compile(
    r"\b(malicious|malware|safe|unsafe|suspicious|dangerous|compromised|backdoor|attack|attacker|evil|trojan)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Evidence:
    """What a signal points at: a file and line range, an attestation field, or a before-and-after value."""

    file: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    side: Literal["old", "new"] | None = None
    attestation_field: str | None = None
    before: str | None = None
    after: str | None = None

    def __post_init__(self) -> None:
        """Line ranges need a file, and run forward from 1."""
        if self.line_start is not None:
            if self.file is None or self.line_start < 1 or (self.line_end or self.line_start) < self.line_start:
                raise ValueError(f"invalid line range {self.line_start}-{self.line_end} for {self.file!r}")

    def to_json(self) -> dict[str, Any]:
        """The evidence without unset fields, for storage."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(frozen=True)
class Signal:
    """One fact a rule reports, with its evidence."""

    rule_id: str
    level: Level
    message: str
    evidence: tuple[Evidence, ...] = ()

    def __post_init__(self) -> None:
        """Refuse unknown levels and messages that judge instead of describe."""
        if self.level not in LEVELS:
            raise ValueError(f"unknown level {self.level!r}")
        if m := _VERDICT_WORDS.search(self.message):
            raise ValueError(f"signal messages describe what changed; {m.group(0)!r} is a verdict: {self.message!r}")

    def evidence_json(self) -> dict[str, Any]:
        """Evidence in the shape stored in ``signal.evidence``."""
        return {"items": [e.to_json() for e in self.evidence]}


@dataclass(frozen=True)
class ReleaseFacts:
    """What is known about one release of the pair."""

    version: str
    published_at: datetime | None = None
    provenance: Provenance | None = None


@dataclass(frozen=True)
class PairAnalysis:
    """Everything a rule may look at for a pair of artifacts. ``None`` means unknown, which rules must not fire on."""

    ecosystem: str
    package: str
    old: ReleaseFacts
    new: ReleaseFacts
    files: tuple[FilePair, ...] = ()
    diffs: dict[str, _core.FileDiff] = field(default_factory=dict)
    # Decoded text of the new side of each added or changed text pair, by path, for parsing.
    new_text: dict[str, str] = field(default_factory=dict)
    # Decoded text of the old side of each changed text pair, by path.
    old_text: dict[str, str] = field(default_factory=dict)
    source: SourceComparison | CouldNotCompare | None = None
    # How the source is named in messages, such as "tag v2.5.0" or "commit 0123abc".
    source_label: str | None = None
    # Line diffs of package files that differ from the source, by package path: old is the source, new the package.
    source_diffs: dict[str, _core.FileDiff] = field(default_factory=dict)
    sdist: SourceComparison | None = None
    # Releases before `old` with what is known about them, oldest first.
    history: tuple[ReleaseFacts, ...] = ()


Check = Callable[[PairAnalysis], Iterable[Signal]]


@dataclass(frozen=True)
class Rule:
    """A named, versioned check."""

    id: str
    version: int
    summary: str
    check: Check

    def run(self, analysis: PairAnalysis) -> list[Signal]:
        """Run the check and make sure every signal names this rule."""
        signals = list(self.check(analysis))
        for s in signals:
            if s.rule_id != self.id:
                raise ValueError(f"rule {self.id} returned a signal for {s.rule_id}")
        return signals


class RuleSet:
    """An ordered collection of rules with a version derived from their ids and versions."""

    def __init__(self, rules: Iterable[Rule] = ()) -> None:
        """Start with ``rules``."""
        self._rules: dict[str, Rule] = {}
        for r in rules:
            self.add(r)

    def add(self, rule: Rule) -> Rule:
        """Add a rule; ids are ``group.name`` and unique."""
        if not _RULE_ID_RE.match(rule.id):
            raise ValueError(f"rule ids are group.name in lowercase: {rule.id!r}")
        if rule.id in self._rules:
            raise ValueError(f"duplicate rule id {rule.id!r}")
        if rule.version < 1:
            raise ValueError(f"rule {rule.id} needs a version of 1 or more")
        self._rules[rule.id] = rule
        return rule

    def rule(self, rule_id: str, version: int, summary: str) -> Callable[[Check], Check]:
        """Register the decorated function as a rule.

        Args:
            rule_id: ``group.name``, such as ``provenance.attestation_dropped``.
            version: Bumped whenever what the rule reports changes.
            summary: One line saying what the rule looks for.
        """

        def register(check: Check) -> Check:
            self.add(Rule(rule_id, version, summary, check))
            return check

        return register

    def __iter__(self) -> Iterator[Rule]:
        """Rules in id order."""
        return iter(sorted(self._rules.values(), key=lambda r: r.id))

    def __len__(self) -> int:
        """Number of rules."""
        return len(self._rules)

    @property
    def version(self) -> str:
        """``rs-`` and the first 16 hex digits of a hash over every rule's id and version."""
        manifest = "\n".join(f"{r.id}@{r.version}" for r in self)
        return "rs-" + hashlib.sha256(manifest.encode()).hexdigest()[:16]

    def run(self, analysis: PairAnalysis) -> list[Signal]:
        """Run every rule and return the signals, most severe first. A rule that raises fails the whole run."""
        signals = [s for r in self for s in r.run(analysis)]
        return sorted(signals, key=lambda s: LEVELS.index(s.level))


RULES = RuleSet()
