"""Parse ``uv.lock`` into the per-platform model the ``pixi.lock`` parser returns.

A uv lockfile is one universal resolution: dependencies carry environment markers, and a package can be locked at
several versions that apply under different markers. Each of :data:`PLATFORMS` gets its own resolution, evaluated at
the lowest Python the project allows: starting from the project's own packages (with all their optional dependencies
and dependency groups, since CI installs those too), every dependency whose marker holds is followed, and so are the
extras it asks for. A package that only another Python version or architecture would install isn't in any of them.

The walk, the members, edge resolution, the Python floor and the artifact choice follow pixi-sbom's uv.lock reader
(``src/uv.rs`` and ``src/pylock.rs`` in aesir-pixi-sbom, Apache-2.0, by the same maintainer).
"""

import re
import tomllib
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from packaging.markers import InvalidMarker, Marker
from packaging.utils import canonicalize_name

from sightglass.lockfiles.model import Dependency, LockedPackage, Lockfile, Resolution
from sightglass.lockfiles.pixi import MAX_LOCKFILE_SIZE, LockfileError
from sightglass.log import get_logger

log = get_logger(__name__)

# The platforms a uv lockfile is expanded for, named like pixi's, with their marker values.
PLATFORMS: dict[str, dict[str, str]] = {
    "linux-64": {"sys_platform": "linux", "platform_system": "Linux", "os_name": "posix", "platform_machine": "x86_64"},
    "osx-arm64": {
        "sys_platform": "darwin",
        "platform_system": "Darwin",
        "os_name": "posix",
        "platform_machine": "arm64",
    },
    "win-64": {"sys_platform": "win32", "platform_system": "Windows", "os_name": "nt", "platform_machine": "AMD64"},
}
# Python assumed for markers when the lockfile names none.
FALLBACK_PYTHON = "3.14"
_FLOOR_RE = re.compile(r"^\s*(?:>=|~=|==)\s*(\d+)\.(\d+)")


@dataclass(frozen=True)
class _Entry:
    """One ``[[package]]`` table."""

    name: str
    version: str
    dependencies: tuple[dict[str, Any], ...]
    extras: Mapping[str, tuple[dict[str, Any], ...]]
    groups: Mapping[str, tuple[dict[str, Any], ...]]
    member: bool
    source: Mapping[str, Any]
    wheels: tuple[str, ...]
    sdist: str | None


def _wheel_fits(url: str, platform: str) -> bool:
    """Whether a wheel's platform tag installs on ``platform``."""
    tag = url.rsplit("/", 1)[-1].removesuffix(".whl").rsplit("-", 1)[-1]
    if tag == "any":
        return True
    for t in tag.split("."):
        if platform == "linux-64" and "linux" in t and t.endswith("x86_64"):
            return True
        if platform == "osx-arm64" and t.startswith("macosx") and t.endswith(("arm64", "universal2")):
            return True
        if platform == "win-64" and t == "win_amd64":
            return True
    return False


def _location(entry: _Entry, platform: str, python: str) -> str:
    """What this platform would install.

    A universal wheel, else a wheel for the platform (built for this Python, then abi3, then any), else the sdist,
    else where the source points.
    """
    universal = next((w for w in entry.wheels if w.endswith("-none-any.whl")), None)
    fitting = [w for w in entry.wheels if _wheel_fits(w, platform)]
    cp = f"-cp{python.replace('.', '')}-"
    chosen = (
        universal
        or next((w for w in fitting if cp in w), None)
        or next((w for w in fitting if "-abi3-" in w), None)
        or next(iter(fitting), None)
        or entry.sdist
    )
    if chosen:
        return chosen
    for key in ("git", "url", "path", "directory", "editable", "virtual", "registry"):
        if isinstance(entry.source.get(key), str):
            return str(entry.source[key])
    return ""


def _deps(value: Any) -> tuple[dict[str, Any], ...]:
    return (
        tuple(d for d in value if isinstance(d, dict) and isinstance(d.get("name"), str))
        if isinstance(value, list)
        else ()
    )


def _entry(table: Mapping[str, Any], members: frozenset[str]) -> _Entry:
    source = table.get("source", {})
    source = source if isinstance(source, dict) else {}
    name = canonicalize_name(str(table.get("name", "")))
    sdist = table.get("sdist")
    return _Entry(
        name=name,
        version=str(table.get("version", "")),
        dependencies=_deps(table.get("dependencies")),
        extras={k: _deps(v) for k, v in (table.get("optional-dependencies") or {}).items()},
        groups={k: _deps(v) for k, v in (table.get("dev-dependencies") or {}).items()},
        # A workspace member: listed in [manifest], or the project at the root (virtual, or editable ".").
        member="virtual" in source or name in members or source.get("editable") in (".", "./"),
        source=source,
        wheels=tuple(str(w["url"]) for w in table.get("wheels", []) if isinstance(w, dict) and "url" in w),
        sdist=str(sdist["url"]) if isinstance(sdist, dict) and "url" in sdist else None,
    )


def _holds(marker: str | None, env: Mapping[str, str]) -> bool:
    if not marker:
        return True
    try:
        return Marker(marker).evaluate(dict(env))
    except InvalidMarker:
        log.warning("lockfile_marker_unreadable", marker=marker)
        return True


def _python_floor(requires: str | None) -> str:
    """The lowest Python ``requires-python`` allows (``>=3.12`` gives ``3.12``), else :data:`FALLBACK_PYTHON`."""
    for clause in (requires or "").split(","):
        if match := _FLOOR_RE.match(clause):
            return f"{match.group(1)}.{match.group(2)}"
    return FALLBACK_PYTHON


def _environment(platform: str, python: str) -> dict[str, str]:
    return {
        **PLATFORMS[platform],
        "python_version": python,
        "python_full_version": f"{python}.0",
        "implementation_name": "cpython",
        "implementation_version": f"{python}.0",
        "platform_python_implementation": "CPython",
        # Set so packaging doesn't fill them from the machine running Sightglass.
        "platform_release": "",
        "platform_version": "",
        "extra": "",
    }


def _pick(candidates: list[_Entry], dep: Mapping[str, Any]) -> _Entry | None:
    """The entry a dependency refers to. uv writes the version and source on an edge whenever the name is ambiguous."""
    return next(
        (
            c
            for c in candidates
            if (not isinstance(dep.get("version"), str) or c.version == dep["version"])
            and (not isinstance(dep.get("source"), dict) or c.source == dep["source"])
        ),
        None,
    )


def _resolve(entries: list[_Entry], platform: str, python: str) -> Resolution:
    env = _environment(platform, python)
    by_name: dict[str, list[_Entry]] = {}
    for e in entries:
        by_name.setdefault(e.name, []).append(e)
    reached: dict[tuple[str, str], set[str]] = {}
    queue: deque[tuple[_Entry, frozenset[str]]] = deque()
    for e in entries:
        if e.member:
            queue.append((e, frozenset(e.extras) | {f"group:{g}" for g in e.groups}))
    while queue:
        entry, wanted = queue.popleft()
        key = (entry.name, entry.version)
        seen = reached.setdefault(key, set())
        if seen and wanted <= seen:
            continue
        seen |= wanted
        for dep in _followed(entry, wanted, env):
            target = _pick(by_name.get(canonicalize_name(dep["name"]), []), dep)
            if target is not None:
                queue.append((target, frozenset(x for x in dep.get("extra", []) if isinstance(x, str))))
    packages = []
    for e in entries:
        if (e.name, e.version) in reached:
            asked = reached[(e.name, e.version)]
            packages.append(
                LockedPackage(
                    "pypi",
                    e.name,
                    e.version,
                    _location(e, platform, python),
                    tuple(
                        Dependency("pypi", canonicalize_name(d["name"]), d.get("marker"))
                        for d in _followed(e, frozenset(asked), env)
                    ),
                )
            )
    return Resolution("default", platform, tuple(packages))


def _followed(entry: _Entry, wanted: Iterable[str], env: Mapping[str, str]) -> list[dict[str, Any]]:
    """A package's dependencies that apply here: its own, the extras asked for, and its groups for the project."""
    deps = list(entry.dependencies)
    for name in wanted:
        if name.startswith("group:"):
            deps += entry.groups.get(name.removeprefix("group:"), ())
        else:
            deps += entry.extras.get(name, ())
    return [d for d in deps if _holds(d.get("marker"), env)]


def parse_uv_lock(content: bytes) -> Lockfile:
    """Parse a ``uv.lock`` into one resolution per platform in :data:`PLATFORMS`.

    Args:
        content: The lockfile's bytes, as fetched.

    Returns:
        The resolutions, in platform order.

    Raises:
        LockfileError: If it's over the size limit or isn't a uv lockfile.
    """
    if len(content) > MAX_LOCKFILE_SIZE:
        raise LockfileError(f"uv.lock is {len(content)} bytes, over the {MAX_LOCKFILE_SIZE} limit")
    try:
        data = tomllib.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise LockfileError(f"uv.lock couldn't be read: {exc}") from exc
    tables = data.get("package")
    if not isinstance(data.get("version"), int) or not isinstance(tables, list):
        raise LockfileError("uv.lock couldn't be read: no version or [[package]] tables")
    manifest = data.get("manifest")
    listed = manifest.get("members", []) if isinstance(manifest, dict) else []
    members = frozenset(canonicalize_name(m) for m in listed if isinstance(m, str))
    entries = [_entry(t, members) for t in tables if isinstance(t, dict) and t.get("name")]
    python = _python_floor(data.get("requires-python"))
    return Lockfile("uv.lock", tuple(_resolve(entries, platform, python) for platform in PLATFORMS))
