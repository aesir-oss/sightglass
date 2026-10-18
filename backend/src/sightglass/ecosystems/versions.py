"""Which release a version is compared with by default, and which release is a project's latest.

Both follow version order, not publish order: a project that maintains several release lines publishes backports after
newer releases (django's 5.2.17 came out after 6.0.8), and comparing by publish date would run backwards.
"""

from packaging.version import InvalidVersion, Version
from rattler import Version as CondaVersion
from rattler.exceptions import InvalidVersionError as InvalidCondaVersion

from sightglass.ecosystems.pypi import PypiProject, PypiRelease


def parse(version: str) -> Version | None:
    """The version, or None when it isn't a valid PEP 440 version."""
    try:
        return Version(version)
    except InvalidVersion:
        return None


def stable(version: str) -> Version | None:
    """The version when it's a final release, or None for pre-releases, dev releases and invalid versions."""
    v = parse(version)
    return None if v is None or v.is_prerelease or v.is_devrelease else v


def predecessor(project: PypiProject, version: str) -> PypiRelease | None:
    """The release ``version`` is compared with when no other is named.

    The highest stable, unyanked version below it that was published no later than it, so a backport is compared with
    the release before it on its own line. Failing that, the highest version below it; and for versions that don't
    parse, the release published just before it.

    Args:
        project: The project and its releases.
        version: A version the project has.

    Returns:
        The predecessor, or None when nothing comes before it.
    """
    releases = {r.version: r for r in project.releases}
    target = releases.get(version)
    current = parse(version)
    if target is None:
        return None
    if current is None:
        order = [r.version for r in project.releases]
        index = order.index(version)
        return project.releases[index - 1] if index > 0 else None
    lower = [(v, r) for r in project.releases if (v := parse(r.version)) is not None and v < current]
    preferred = [
        (v, r)
        for v, r in lower
        if stable(r.version)
        and not r.yanked
        and (r.published_at is None or target.published_at is None or r.published_at <= target.published_at)
    ]
    chosen = max(preferred or lower, key=lambda pair: pair[0], default=None)
    return chosen[1] if chosen else None


def latest(project: PypiProject) -> PypiRelease | None:
    """The project's highest stable, unyanked version; else its highest version; else the last one published."""
    parsed = [(v, r) for r in project.releases if (v := parse(r.version)) is not None]
    preferred = [(v, r) for v, r in parsed if stable(r.version) and not r.yanked]
    chosen = max(preferred or parsed, key=lambda pair: pair[0], default=None)
    if chosen is not None:
        return chosen[1]
    return project.releases[-1] if project.releases else None


def is_downgrade(ecosystem: str, from_version: str, to_version: str) -> bool:
    """Whether moving from ``from_version`` to ``to_version`` goes to an older version.

    PyPI versions compare by PEP 440 and conda ones by conda's rules (py-rattler); versions that don't parse aren't
    called a downgrade.
    """
    if ecosystem == "conda":
        try:
            return bool(CondaVersion(to_version) < CondaVersion(from_version))
        except ValueError, TypeError, InvalidCondaVersion:
            return False
    old, new = parse(from_version), parse(to_version)
    return old is not None and new is not None and new < old
