"""Which packages a pixi workspace asks for itself, from its ``pixi.toml`` or ``pyproject.toml``.

A lockfile records what was resolved, not what was asked for. The manifest's dependency tables name the direct
dependencies of each feature, and ``[environments]`` says which features each environment combines. Ported from the
manifest reader in pixi-sbom (aesir-pixi-sbom ``src/manifest.rs``, Apache-2.0, same maintainer), for the tables pixi
projects use.
"""

import re
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from sightglass.lockfiles.model import Ecosystem
from sightglass.log import get_logger

log = get_logger(__name__)

# The feature the top-level tables belong to; every environment includes it unless it sets no-default-feature.
DEFAULT_FEATURE = "default"
_CONDA_TABLES = ("dependencies", "host-dependencies", "build-dependencies")
_GROUP_RE = re.compile(r"[-_.]+")


@dataclass(frozen=True)
class Declared:
    """One dependency a manifest declares, and the feature that declares it."""

    ecosystem: Ecosystem
    name: str
    feature: str


@dataclass(frozen=True)
class Manifest:
    """A workspace's declared dependencies and how its environments combine features."""

    declared: tuple[Declared, ...]
    environments: Mapping[str, tuple[frozenset[str], bool]]

    def features_of(self, environment: str) -> frozenset[str]:
        """The features an environment is built from; one the manifest doesn't name is the default feature alone."""
        if environment not in self.environments:
            return frozenset({DEFAULT_FEATURE})
        features, no_default = self.environments[environment]
        return features if no_default else features | {DEFAULT_FEATURE}

    def direct(self, environment: str) -> frozenset[tuple[Ecosystem, str]]:
        """The packages the environment's features declare, by ecosystem and normalized name."""
        features = self.features_of(environment)
        return frozenset((d.ecosystem, d.name) for d in self.declared if d.feature in features)


def _tables(tables: Mapping[str, Any], feature: str) -> list[Declared]:
    out = []
    for table in _CONDA_TABLES:
        out += [Declared("conda", str(n).lower(), feature) for n in _keys(tables.get(table))]
    out += [Declared("pypi", canonicalize_name(str(n)), feature) for n in _keys(tables.get("pypi-dependencies"))]
    # A platform's table declares for the same feature; other platforms' packages just aren't in the resolution.
    for target in _dicts(tables.get("target")):
        out += _tables(target, feature)
    return out


def _keys(value: Any) -> Iterable[str]:
    return value.keys() if isinstance(value, dict) else ()


def _dicts(value: Any) -> Iterable[Mapping[str, Any]]:
    return (v for v in value.values() if isinstance(v, dict)) if isinstance(value, dict) else ()


def _requirements(requirements: Any, feature: str) -> list[Declared]:
    out = []
    for text in requirements if isinstance(requirements, list) else ():
        try:
            out.append(Declared("pypi", canonicalize_name(Requirement(str(text)).name), feature))
        except InvalidRequirement:
            log.warning("manifest_requirement_unreadable", requirement=text)
    return out


def _group(groups: Mapping[str, Any], name: str, seen: frozenset[str] = frozenset()) -> list[str]:
    """A PEP 735 dependency group's requirements, with ``include-group`` entries expanded (cycles stop)."""
    wanted = _GROUP_RE.sub("-", name).lower()
    entries: Any = next((v for k, v in groups.items() if _GROUP_RE.sub("-", k).lower() == wanted), [])
    out: list[str] = []
    for entry in entries if isinstance(entries, list) else ():
        if isinstance(entry, str):
            out.append(entry)
        elif isinstance(entry, dict) and isinstance(entry.get("include-group"), str) and wanted not in seen:
            out += _group(groups, entry["include-group"], seen | {wanted})
    return out


def _from_pixi(table: Mapping[str, Any]) -> tuple[list[Declared], dict[str, tuple[frozenset[str], bool]]]:
    declared = _tables(table, DEFAULT_FEATURE)
    features = table.get("feature")
    for name, tables in features.items() if isinstance(features, dict) else ():
        if isinstance(tables, dict):
            declared += _tables(tables, str(name))
    environments: dict[str, tuple[frozenset[str], bool]] = {}
    envs = table.get("environments")
    for name, spec in envs.items() if isinstance(envs, dict) else ():
        if isinstance(spec, list):
            environments[str(name)] = (frozenset(str(f) for f in spec), False)
        elif isinstance(spec, dict):
            listed = spec.get("features", [])
            environments[str(name)] = (
                frozenset(str(f) for f in listed if isinstance(f, str)) if isinstance(listed, list) else frozenset(),
                bool(spec.get("no-default-feature", False)),
            )
    return declared, environments


def parse_manifest(name: str, content: bytes) -> Manifest | None:
    """Read a ``pixi.toml``, or a ``pyproject.toml`` with or without a ``[tool.pixi]`` table.

    Args:
        name: The file name, which says which format it is.
        content: The file's bytes.

    Returns:
        The manifest, or None when it can't be read; callers then treat packages nothing depends on as direct.
    """
    try:
        data = tomllib.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        log.warning("manifest_unreadable", name=name, error=str(exc))
        return None
    if name.endswith("pixi.toml"):
        declared, environments = _from_pixi(data)
        return Manifest(tuple(declared), environments)
    tool = data.get("tool", {})
    pixi = tool.get("pixi") if isinstance(tool, dict) else None
    declared, environments = _from_pixi(pixi) if isinstance(pixi, dict) else ([], {})
    project = data.get("project", {})
    if isinstance(project, dict):
        # PEP 621 requirements are the default feature's PyPI dependencies; pixi makes each extra a feature.
        declared += _requirements(project.get("dependencies"), DEFAULT_FEATURE)
        extras = project.get("optional-dependencies")
        for extra, requirements in extras.items() if isinstance(extras, dict) else ():
            declared += _requirements(requirements, str(extra))
    groups = data.get("dependency-groups")
    if isinstance(groups, dict):
        for group in groups:
            declared += _requirements(_group(groups, str(group)), str(group))
    return Manifest(tuple(declared), environments)
