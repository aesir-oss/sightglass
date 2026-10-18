"""What a lockfile resolves to, whatever its format: packages per environment and platform, and their dependencies.

Every parser returns a :class:`Lockfile`. Names are normalized for their ecosystem (PEP 503 for PyPI, lowercase for
conda), so the same package is found by any spelling, and a dependency points at the package that satisfies it in the
same resolution when there is one.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal

Ecosystem = Literal["conda", "pypi"]
Format = Literal["pixi.lock", "uv.lock"]


@dataclass(frozen=True)
class Dependency:
    """One requirement of a locked package.

    Attributes:
        ecosystem: Where the requirement is looked up: conda specs name conda packages, Python requirements PyPI ones.
        name: The normalized name required.
        marker: The environment marker on a Python requirement, such as ``extra == 'fast'``; None when it has none.
    """

    ecosystem: Ecosystem
    name: str
    marker: str | None = None


@dataclass(frozen=True)
class LockedPackage:
    """One package as a resolution pins it.

    Attributes:
        ecosystem: ``conda`` or ``pypi``.
        name: The normalized name.
        version: The pinned version as written.
        location: Where it's installed from: an artifact URL, or a path for a local project.
        dependencies: Its requirements, in lockfile order.
        provides: Other names the package satisfies; a conda package lists the PyPI projects it installs, so a
            Python requirement on one of them is met by the conda package.
    """

    ecosystem: Ecosystem
    name: str
    version: str
    location: str
    dependencies: tuple[Dependency, ...] = ()
    provides: tuple[tuple[Ecosystem, str], ...] = ()

    @property
    def key(self) -> tuple[Ecosystem, str]:
        """The package's identity within a resolution."""
        return (self.ecosystem, self.name)


@dataclass(frozen=True)
class Resolution:
    """The packages one environment resolves to on one platform."""

    environment: str
    platform: str
    packages: tuple[LockedPackage, ...]
    _by_key: dict[tuple[Ecosystem, str], LockedPackage] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Index the packages by key, and the names they provide."""
        by_key: dict[tuple[Ecosystem, str], LockedPackage] = {}
        for p in self.packages:
            by_key.setdefault(p.key, p)
        for p in self.packages:
            for provided in p.provides:
                by_key.setdefault(provided, p)
        object.__setattr__(self, "_by_key", by_key)

    def find(self, ecosystem: Ecosystem, name: str) -> LockedPackage | None:
        """The package locked under this name, or the one that provides it, if any."""
        return self._by_key.get((ecosystem, name))

    def edges(self) -> Iterator[tuple[LockedPackage, LockedPackage, Dependency]]:
        """Every dependency that a package in this resolution satisfies, as (dependent, dependency, requirement)."""
        for p in self.packages:
            for dep in p.dependencies:
                if (target := self.find(dep.ecosystem, dep.name)) is not None and target is not p:
                    yield p, target, dep


@dataclass(frozen=True)
class Lockfile:
    """A parsed lockfile: every environment's resolution on every platform."""

    format: Format
    resolutions: tuple[Resolution, ...]

    def resolution(self, environment: str, platform: str) -> Resolution | None:
        """One environment on one platform, if the lockfile has it."""
        return next(
            (r for r in self.resolutions if (r.environment, r.platform) == (environment, platform)),
            None,
        )
