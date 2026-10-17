"""Choosing which files of two releases to compare.

A release pair is compared through its sdists and one wheel from each release. The wheel pair is the same tag in both
releases when there is one, preferring ``py3-none-any`` and then the most widely installed platforms. When a project
changes its platform tags between releases (``manylinux2014`` to ``manylinux_2_28``, or ``cp312`` to ``cp313``), wheels
for the same OS and architecture are paired instead and the pair says so. Every other possible pair is kept, best
first, so the page can offer a picker.
"""

import re
from dataclasses import dataclass
from typing import Literal

from packaging.tags import Tag
from packaging.utils import InvalidWheelFilename, parse_wheel_filename

from sightglass.ecosystems.pypi import PypiFile, PypiRelease
from sightglass.log import get_logger

log = get_logger(__name__)

Match = Literal["same_tag", "platform_changed"]

PURE = Tag("py3", "none", "any")
# Most installs come from these, so a pair here is the one most users actually get.
_PLATFORM_PREFERENCE = (
    ("manylinux", "x86_64"),
    ("macosx", "arm64"),
    ("win", "amd64"),
    ("manylinux", "aarch64"),
    ("musllinux", "x86_64"),
    ("macosx", "x86_64"),
    ("macosx", "universal2"),
)
_LINUX_RE = re.compile(r"^(manylinux|musllinux)(?:1|2010|2014|_\d+_\d+)_(.+)$")
_MACOS_RE = re.compile(r"^macosx_\d+_\d+_(.+)$")
_CPYTHON_RE = re.compile(r"^cp(\d)(\d+)$")


@dataclass(frozen=True)
class ArtifactPair:
    """One file from each release, compared with each other."""

    kind: Literal["sdist", "wheel"]
    old: PypiFile
    new: PypiFile
    match: Match = "same_tag"


@dataclass(frozen=True)
class Selection:
    """The pairs chosen for a release pair, the alternatives, and the files left out."""

    sdist: ArtifactPair | None
    wheels: tuple[ArtifactPair, ...]
    unpaired_old: tuple[PypiFile, ...]
    unpaired_new: tuple[PypiFile, ...]

    @property
    def wheel(self) -> ArtifactPair | None:
        """The default wheel pair: the first of :attr:`wheels`."""
        return self.wheels[0] if self.wheels else None

    @property
    def chosen(self) -> tuple[ArtifactPair, ...]:
        """The pairs compared by default: the sdist pair and the default wheel pair, when they exist."""
        return tuple(p for p in (self.sdist, self.wheel) if p is not None)


@dataclass(frozen=True)
class _Wheel:
    file: PypiFile
    tags: frozenset[Tag]

    @property
    def platforms(self) -> frozenset[tuple[str, str]]:
        return frozenset(platform_key(t.platform) for t in self.tags)


def platform_key(platform: str) -> tuple[str, str]:
    """Reduce a wheel platform tag to its OS family and architecture, dropping the libc or OS version.

    Args:
        platform: A platform tag such as ``manylinux_2_17_x86_64`` or ``macosx_11_0_arm64``.

    Returns:
        ``(family, arch)``, for example ``("manylinux", "x86_64")``; unknown platforms are ``(platform, "")``.
    """
    if platform == "any":
        return ("any", "any")
    if platform == "win32":
        return ("win", "x86")
    if m := _LINUX_RE.match(platform):
        return (m.group(1), m.group(2))
    if m := _MACOS_RE.match(platform):
        return ("macosx", m.group(1))
    for family in ("linux", "win"):
        if platform.startswith(family + "_"):
            return (family, platform.removeprefix(family + "_"))
    return (platform, "")


def _rank(pair: ArtifactPair, new: _Wheel) -> tuple[int, int, int, int, str]:
    if PURE in new.tags:
        platform = 0
    elif ("any", "any") in new.platforms:
        platform = 1
    else:
        ranks = [_PLATFORM_PREFERENCE.index(p) for p in new.platforms if p in _PLATFORM_PREFERENCE]
        platform = 2 + min(ranks, default=len(_PLATFORM_PREFERENCE))
    abi3 = any(t.abi == "abi3" for t in new.tags)
    cpython = max((int(m.group(2)) for t in new.tags if (m := _CPYTHON_RE.match(t.interpreter))), default=0)
    return (pair.match != "same_tag", platform, not abi3, -cpython, new.file.filename)


def _wheels(release: PypiRelease) -> list[_Wheel]:
    out = []
    for f in release.files:
        if f.kind != "wheel":
            continue
        try:
            tags = parse_wheel_filename(f.filename)[3]
        except InvalidWheelFilename:
            log.warning("invalid_wheel_filename", version=release.version, filename=f.filename)
            continue
        out.append(_Wheel(f, tags))
    return out


def preferred_sdist(release: PypiRelease) -> PypiFile | None:
    """The release's sdist to analyze: the ``.tar.gz`` one when there are several."""
    sdists = [f for f in release.files if f.kind == "sdist"]
    return min(sdists, key=lambda f: (not f.filename.endswith(".tar.gz"), f.filename), default=None)


def _wheel_pairs(old: list[_Wheel], new: list[_Wheel]) -> list[ArtifactPair]:
    ranked: list[tuple[tuple[int, int, int, int, str], ArtifactPair]] = []
    exact_old: set[str] = set()
    exact_new: set[str] = set()
    for n in new:
        for o in old:
            if o.tags & n.tags:
                ranked.append((_rank(pair := ArtifactPair("wheel", o.file, n.file), n), pair))
                exact_old.add(o.file.filename)
                exact_new.add(n.file.filename)
    for n in new:
        if n.file.filename in exact_new:
            continue
        for o in old:
            if o.file.filename not in exact_old and o.platforms & n.platforms:
                pair = ArtifactPair("wheel", o.file, n.file, "platform_changed")
                ranked.append((_rank(pair, n), pair))
    ranked.sort(key=lambda r: (r[0], r[1].old.filename))
    return [pair for _, pair in ranked]


def select_artifacts(old: PypiRelease, new: PypiRelease) -> Selection:
    """Choose the files to compare between two releases of a project.

    Args:
        old: The earlier release.
        new: The later release.

    Returns:
        The sdist pair, every wheel pair best first, and the files of each release that are in no pair.
    """
    old_sdist, new_sdist = preferred_sdist(old), preferred_sdist(new)
    sdist = ArtifactPair("sdist", old_sdist, new_sdist) if old_sdist and new_sdist else None
    wheels = tuple(_wheel_pairs(_wheels(old), _wheels(new)))
    paired_old = {p.old.filename for p in (*wheels, *([sdist] if sdist else []))}
    paired_new = {p.new.filename for p in (*wheels, *([sdist] if sdist else []))}
    selection = Selection(
        sdist=sdist,
        wheels=wheels,
        unpaired_old=tuple(f for f in old.files if f.filename not in paired_old),
        unpaired_new=tuple(f for f in new.files if f.filename not in paired_new),
    )
    log.debug(
        "artifacts_selected",
        old=old.version,
        new=new.version,
        chosen=[(p.old.filename, p.new.filename) for p in selection.chosen],
        alternatives=len(wheels),
    )
    return selection
