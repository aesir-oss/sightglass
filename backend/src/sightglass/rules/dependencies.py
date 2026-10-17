"""Dependency rules: ``Requires-Dist`` entries added, limited to some environments, changed or removed.

Requirements come from the wheel's ``METADATA`` or the sdist's ``PKG-INFO``, are parsed with ``packaging`` and are
compared by normalized name, so ``Orbit_Client`` and ``orbit-client`` are the same dependency.
"""

from dataclasses import dataclass
from email.parser import HeaderParser

from packaging.markers import Marker
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import NormalizedName, canonicalize_name

from sightglass.log import get_logger
from sightglass.rules.base import RULES, Evidence, PairAnalysis, Signal

log = get_logger(__name__)

METADATA_FILES = ("*.dist-info/METADATA", "PKG-INFO")
# Marker variables that limit a dependency to some platforms or interpreters (``extra`` is handled separately).
_ENVIRONMENT_VARIABLES = (
    "sys_platform",
    "platform_system",
    "platform_machine",
    "platform_release",
    "platform_version",
    "platform_python_implementation",
    "implementation_name",
    "os_name",
    "python_version",
    "python_full_version",
)


@dataclass(frozen=True)
class Entry:
    """One ``Requires-Dist`` line."""

    raw: str
    requirement: Requirement
    line: int

    @property
    def text(self) -> str:
        """The requirement in normalized form."""
        return str(self.requirement)

    @property
    def key(self) -> str:
        """The requirement with its name normalized, for comparing; specifiers are already in a fixed order."""
        req = self.requirement
        extras = f"[{','.join(sorted(req.extras))}]" if req.extras else ""
        target = f" @ {req.url}" if req.url else str(req.specifier)
        marker = f"; {req.marker}" if req.marker else ""
        return f"{canonicalize_name(req.name)}{extras}{target}{marker}"


@dataclass(frozen=True)
class Requirements:
    """Every requirement of a release, by normalized name, and the metadata file it came from."""

    path: str
    by_name: dict[NormalizedName, list[Entry]]


def read_requirements(texts: dict[str, str]) -> Requirements | None:
    """Parse ``Requires-Dist`` from the first metadata file present, or None when there is none."""
    path = next((p for p in METADATA_FILES if p in texts), None)
    if path is None:
        return None
    text = texts[path]
    headers = HeaderParser().parsestr(text)
    lines = text.splitlines()
    by_name: dict[NormalizedName, list[Entry]] = {}
    for raw in headers.get_all("Requires-Dist") or []:
        raw = " ".join(raw.split())
        try:
            req = Requirement(raw)
        except InvalidRequirement as exc:
            log.warning("invalid_requirement", path=path, requirement=raw, error=str(exc))
            continue
        line = next((i for i, x in enumerate(lines, 1) if x.startswith("Requires-Dist:") and raw in x), 0)
        by_name.setdefault(canonicalize_name(req.name), []).append(Entry(raw, req, line))
    return Requirements(path, by_name)


def _environment(marker: Marker | None) -> bool:
    return marker is not None and any(var in str(marker) for var in _ENVIRONMENT_VARIABLES)


def _extras(marker: Marker | None) -> list[str]:
    if marker is None:
        return []
    parts = str(marker).split("extra == ")[1:]
    return [p.split()[0].strip("\"'") for p in parts]


def _evidence(reqs: Requirements, entries: list[Entry], before: str | None, after: str | None) -> Evidence:
    line = min((e.line for e in entries if e.line), default=None)
    return Evidence(reqs.path, line, line, "new" if line else None, before=before, after=after)


def _pair(analysis: PairAnalysis) -> tuple[Requirements, Requirements] | None:
    old, new = read_requirements(analysis.old_text), read_requirements(analysis.new_text)
    return None if old is None or new is None else (old, new)


@RULES.rule("dependencies.added", 1, "New declared dependency")
def added(analysis: PairAnalysis) -> list[Signal]:
    """Report each newly declared dependency that applies in every environment."""
    pair = _pair(analysis)
    if pair is None:
        return []
    old, new = pair
    signals = []
    for name in sorted(new.by_name.keys() - old.by_name.keys()):
        entries = new.by_name[name]
        if any(_environment(e.requirement.marker) for e in entries):
            continue
        extras = sorted({x for e in entries for x in _extras(e.requirement.marker)})
        scope = ""
        if extras:
            scope = f" for the `{'`, `'.join(extras)}` extra{'s' if len(extras) > 1 else ''}"
        text = "; ".join(e.text for e in entries)
        signals.append(
            Signal(
                "dependencies.added",
                "check",
                f"{analysis.new.version} adds a dependency on `{text}`{scope}",
                (_evidence(new, entries, None, text),),
            )
        )
    return signals


@RULES.rule("dependencies.environment_specific", 1, "New dependency only on some platforms or markers")
def environment_specific(analysis: PairAnalysis) -> list[Signal]:
    """Report new dependencies whose markers limit them to some platforms, interpreters or Python versions."""
    pair = _pair(analysis)
    if pair is None:
        return []
    old, new = pair
    signals = []
    for name in sorted(new.by_name.keys() - old.by_name.keys()):
        entries = [e for e in new.by_name[name] if _environment(e.requirement.marker)]
        if not entries:
            continue
        markers = "; ".join(str(e.requirement.marker) for e in entries)
        signals.append(
            Signal(
                "dependencies.environment_specific",
                "check",
                f"{analysis.new.version} adds a dependency on `{name}` only when {markers}",
                (_evidence(new, entries, None, "; ".join(e.text for e in entries)),),
            )
        )
    return signals


@RULES.rule("dependencies.changed", 1, "Dependency constraint changed, or dependency removed")
def changed(analysis: PairAnalysis) -> list[Signal]:
    """Report dependencies whose specifiers, extras or markers changed, and dependencies that were dropped."""
    pair = _pair(analysis)
    if pair is None:
        return []
    old, new = pair
    signals = []
    for name in sorted(old.by_name):
        before = "; ".join(sorted(e.text for e in old.by_name[name]))
        old_keys = sorted(e.key for e in old.by_name[name])
        if name not in new.by_name:
            signals.append(
                Signal(
                    "dependencies.changed",
                    "note",
                    f"{analysis.new.version} no longer depends on `{name}` ({before} in {analysis.old.version})",
                    (Evidence(old.path, side="old", before=before),),
                )
            )
            continue
        after = "; ".join(sorted(e.text for e in new.by_name[name]))
        if old_keys != sorted(e.key for e in new.by_name[name]):
            signals.append(
                Signal(
                    "dependencies.changed",
                    "note",
                    f"The `{name}` requirement changed from `{before}` to `{after}`",
                    (_evidence(new, new.by_name[name], before, after),),
                )
            )
    return signals
