"""Parse ``pixi.lock`` with py-rattler, the library behind pixi itself.

Conda packages depend on other conda packages through match specs (``python >=3.10``); PyPI packages through Python
requirements. A conda package that installs a Python project lists it as a ``pkg:pypi/...`` purl, which is how a
PyPI package's requirement on, say, ``numpy`` is met by conda-forge's numpy in a pixi environment.
"""

import json
import re
import tempfile
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from rattler import LockFile
from rattler.exceptions import ParseCondaLockError

from sightglass.lockfiles.model import Dependency, Ecosystem, LockedPackage, Lockfile, Resolution
from sightglass.log import get_logger

log = get_logger(__name__)

# Lockfiles are fetched from repositories Sightglass doesn't control; a real one is a few megabytes at most.
MAX_LOCKFILE_SIZE = 32 * 1024 * 1024
# The package name at the start of a conda match spec, as in `kestrel-core >=1.2` or `tidepool 0.9.*`.
_SPEC_NAME_RE = re.compile(r"^\s*([A-Za-z0-9_][A-Za-z0-9_.\-]*)")
_PYPI_PURL_RE = re.compile(r"^pkg:pypi/([^?@#]+)")


class LockfileError(ValueError):
    """The lockfile is too large or isn't one the parser can read."""


def _conda_dependencies(depends: list[str]) -> tuple[Dependency, ...]:
    deps = []
    for spec in depends:
        match = _SPEC_NAME_RE.match(spec)
        # Virtual packages (`__glibc`, `__unix`) describe the machine, not something installed.
        if match and not match.group(1).startswith("__"):
            deps.append(Dependency("conda", match.group(1).lower()))
    return tuple(deps)


def _pypi_dependencies(requires: list[str], package: str) -> tuple[Dependency, ...]:
    deps = []
    for text in requires:
        try:
            req = Requirement(text)
        except InvalidRequirement:
            log.warning("lockfile_requirement_unreadable", package=package, requirement=text)
            continue
        deps.append(Dependency("pypi", canonicalize_name(req.name), str(req.marker) if req.marker else None))
    return tuple(deps)


def _provides(record_json: str) -> tuple[tuple[Ecosystem, str], ...]:
    purls = json.loads(record_json).get("purls") or []
    names = (canonicalize_name(m.group(1)) for p in purls if isinstance(p, str) and (m := _PYPI_PURL_RE.match(p)))
    return tuple(("pypi", n) for n in dict.fromkeys(names))


def _package(locked: object) -> LockedPackage:
    kind = type(locked).__name__
    if kind.startswith("Conda"):
        record = locked.package_record  # type: ignore[attr-defined]
        return LockedPackage(
            "conda",
            record.name.normalized,
            str(record.version),
            str(locked.location),  # type: ignore[attr-defined]
            _conda_dependencies(list(record.depends)),
            _provides(locked.repo_data_record().to_json()),  # type: ignore[attr-defined]
        )
    name = canonicalize_name(str(locked.name))  # type: ignore[attr-defined]
    location = str(locked.location)  # type: ignore[attr-defined]
    return LockedPackage(
        "pypi",
        name,
        str(locked.version),  # type: ignore[attr-defined]
        location,
        _pypi_dependencies(list(locked.requires_dist), name),  # type: ignore[attr-defined]
        # A path rather than a URL is the workspace's own package, such as an editable install of the project.
        first_party="://" not in location,
    )


def parse_pixi_lock(content: bytes) -> Lockfile:
    """Parse a ``pixi.lock``.

    Args:
        content: The lockfile's bytes, as fetched.

    Returns:
        A resolution per environment and platform, sorted by both (py-rattler doesn't keep the file's order).

    Raises:
        LockfileError: If it's over :data:`MAX_LOCKFILE_SIZE` or py-rattler can't read it.
    """
    if len(content) > MAX_LOCKFILE_SIZE:
        raise LockfileError(f"pixi.lock is {len(content)} bytes, over the {MAX_LOCKFILE_SIZE} limit")
    # py-rattler reads lockfiles from a path.
    with tempfile.TemporaryDirectory(prefix="sg-lock-") as tmp:
        path = Path(tmp) / "pixi.lock"
        path.write_bytes(content)
        try:
            lock = LockFile.from_path(path)
        except ParseCondaLockError as exc:
            raise LockfileError(f"pixi.lock couldn't be read: {exc}") from exc
    resolutions = []
    for environment, env in sorted(lock.environments(), key=lambda e: e[0]):
        for platform in sorted(env.platforms(), key=lambda p: p.name):
            packages = tuple(_package(p) for p in env.packages(platform) or ())
            resolutions.append(Resolution(environment, platform.name, packages))
    return Lockfile("pixi.lock", tuple(resolutions))
