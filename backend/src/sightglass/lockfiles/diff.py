"""What a lockfile change changes: packages added, removed or moved to another version, and how each is reached.

Every environment and platform of the base lockfile is compared with the same one in the head. A change is listed
once with the environments and platforms it appears in, and flagged when an environment has it on only some of its
platforms: a package resolved only for ``osx-arm64`` never runs in CI on Linux. Each change gets the shortest path
from what the project asks for directly to the package, to answer "why is this in my lockfile now?".
"""

from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal

from sightglass.lockfiles.model import Ecosystem, LockedPackage, Lockfile, Resolution

ChangeKind = Literal["added", "removed", "changed"]
# The packages an environment's project asks for itself, by ecosystem and normalized name; empty when unknown.
DirectDependencies = Callable[[str], Iterable[tuple[Ecosystem, str]]]


@dataclass(frozen=True)
class Change:
    """One package change, merged across the environments and platforms it appears in.

    Attributes:
        ecosystem: ``conda`` or ``pypi``.
        name: The normalized package name.
        kind: Added, removed, or changed version.
        from_version: The base version; None when added.
        to_version: The head version; None when removed.
        environments: The environments with this change, sorted.
        platforms: The platforms with this change, sorted.
        only_some_platforms: Whether an environment with the change lacks it on one of its platforms.
        path: Package names from where the project starts (a declared direct dependency, or the project itself when
            the lockfile includes it) to this package, both included.
    """

    ecosystem: Ecosystem
    name: str
    kind: ChangeKind
    from_version: str | None
    to_version: str | None
    environments: tuple[str, ...]
    platforms: tuple[str, ...]
    only_some_platforms: bool
    path: tuple[str, ...]


def _roots(resolution: Resolution, direct: Iterable[tuple[Ecosystem, str]]) -> list[LockedPackage]:
    """Where paths start: the declared direct dependencies present here, else packages nothing here depends on.

    In a uv workspace the latter is the project at the root, so its paths run through the workspace members.
    """
    declared = [p for key in direct if (p := resolution.find(*key)) is not None]
    if declared:
        return declared
    depended_on = {id(target) for _, target, _ in resolution.edges()}
    return [p for p in resolution.packages if id(p) not in depended_on]


def shortest_path(
    resolution: Resolution, target: LockedPackage, direct: Iterable[tuple[Ecosystem, str]]
) -> tuple[str, ...]:
    """Package names from the nearest root to ``target`` along dependency edges; empty when nothing reaches it."""
    graph: dict[int, list[LockedPackage]] = {}
    for a, b, _ in resolution.edges():
        graph.setdefault(id(a), []).append(b)
    roots = _roots(resolution, direct)
    queue: deque[tuple[LockedPackage, tuple[str, ...]]] = deque((r, (r.name,)) for r in roots)
    seen = {id(r) for r in roots}
    while queue:
        node, path = queue.popleft()
        if node is target:
            return path
        for nxt in graph.get(id(node), []):
            if id(nxt) not in seen:
                seen.add(id(nxt))
                queue.append((nxt, (*path, nxt.name)))
    return ()


def diff_lockfiles(base: Lockfile, head: Lockfile, direct: DirectDependencies) -> list[Change]:
    """The packages that change between two versions of a lockfile.

    Args:
        base: The lockfile before the change.
        head: The lockfile after it.
        direct: What each environment's project asks for directly, from its manifest.

    Returns:
        One entry per package and version change, sorted by kind, ecosystem and name. First-party packages (the
        project's own workspace members) aren't listed.
    """
    platforms_of: dict[str, set[str]] = {}
    found: dict[tuple[Ecosystem, str, ChangeKind, str | None, str | None], dict[str, set[str]]] = {}
    paths: dict[tuple[Ecosystem, str, ChangeKind, str | None, str | None], tuple[str, ...]] = {}
    keys = {(r.environment, r.platform) for r in (*base.resolutions, *head.resolutions)}
    for environment, platform in sorted(keys):
        platforms_of.setdefault(environment, set()).add(platform)
        old = base.resolution(environment, platform) or Resolution(environment, platform, ())
        new = head.resolution(environment, platform) or Resolution(environment, platform, ())
        before = {p.key: p for p in old.packages if not p.first_party}
        after = {p.key: p for p in new.packages if not p.first_party}
        for key in before.keys() | after.keys():
            a, b = before.get(key), after.get(key)
            if a is not None and b is not None and a.version == b.version:
                continue
            kind: ChangeKind = "added" if a is None else "removed" if b is None else "changed"
            change = (key[0], key[1], kind, a.version if a else None, b.version if b else None)
            found.setdefault(change, {}).setdefault(environment, set()).add(platform)
            if not paths.get(change):
                resolution, target = (old, a) if b is None else (new, b)
                assert target is not None
                paths[change] = shortest_path(resolution, target, direct(environment))
    changes = []
    for (ecosystem, name, kind, old_v, new_v), where in found.items():
        changes.append(
            Change(
                ecosystem,
                name,
                kind,
                old_v,
                new_v,
                tuple(sorted(where)),
                tuple(sorted({p for ps in where.values() for p in ps})),
                any(ps < platforms_of[env] for env, ps in where.items()),
                paths[(ecosystem, name, kind, old_v, new_v)],
            )
        )
    order = {"added": 0, "changed": 1, "removed": 2}
    return sorted(changes, key=lambda c: (order[c.kind], c.ecosystem, c.name, c.from_version or "", c.to_version or ""))
