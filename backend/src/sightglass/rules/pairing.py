"""Pairing the files of two artifacts, and checking a package's files against its source.

Release-to-release pairs match paths after normalizing the parts that change with every release: the versioned
``.dist-info`` and ``.data`` directory names in wheels, and the ``<name>-<version>/`` top-level directory of sdists.

The source check looks for each package file in a source tree (the git tag, or the sdist). Projects keep their code
under a root such as ``src/`` or ``python/``, so the root is the prefix under which most package files are found; files
not under it are looked for at the other candidate roots. Build metadata (``.dist-info``, ``PKG-INFO``,
``.egg-info``) is excluded, since a build always generates it.
"""

import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Literal

from sightglass import _core

PairStatus = Literal["added", "removed", "changed", "same"]
SourceStatus = Literal["matches", "differs", "missing"]

_DIST_INFO_RE = re.compile(r"^[^/]+-[^/]+\.(dist-info|data)/")
_SDIST_METADATA_RE = re.compile(r"^(?:[^/]+/)*(?:PKG-INFO$|[^/]+\.egg-info/)")
_TEXT_CATEGORIES = frozenset({"python", "text"})


@dataclass(frozen=True)
class IndexedFile:
    """A file or link of an artifact or source tree, as the unpacker indexed it."""

    path: str
    sha256: str | None
    text: bool
    link_target: str | None = None
    compiled: bool = False

    @classmethod
    def from_entry(cls, entry: _core.ArchiveEntry, prefix: str = "") -> IndexedFile:
        """Build from an unpacker entry, removing ``prefix`` (such as a top-level directory) from its path."""
        category = entry.file_type.category if entry.file_type else None
        return cls(
            entry.path.removeprefix(prefix),
            entry.sha256,
            category in _TEXT_CATEGORIES,
            entry.link_target,
            category == "compiled",
        )

    def same_content(self, other: IndexedFile) -> bool:
        """Whether both have the same bytes, or are links to the same target."""
        return (self.sha256, self.link_target) == (other.sha256, other.link_target)


@dataclass(frozen=True)
class FilePair:
    """One path across two artifacts."""

    path: str
    status: PairStatus
    old: IndexedFile | None
    new: IndexedFile | None

    @property
    def text(self) -> bool:
        """Whether every side present is text, so the pair can be line-diffed."""
        return all(f.text for f in (self.old, self.new) if f is not None)


@dataclass(frozen=True)
class SourceCheck:
    """Where a package file was found in the source, and whether it matches."""

    path: str
    status: SourceStatus
    source_path: str | None
    text: bool = True


@dataclass(frozen=True)
class SourceComparison:
    """The source check for every package file, and the files left out of it."""

    root: str
    files: tuple[SourceCheck, ...]
    excluded: tuple[str, ...]


def normalize_path(path: str) -> str:
    """Replace the versioned ``<name>-<version>.dist-info`` or ``.data`` directory with a fixed name."""
    return _DIST_INFO_RE.sub(lambda m: f"*.{m.group(1)}/", path, count=1)


def strip_top_level(files: Iterable[IndexedFile]) -> list[IndexedFile]:
    """Remove the top-level directory every path shares, as in sdists; paths are kept when there isn't one."""
    files = list(files)
    tops = {f.path.split("/", 1)[0] for f in files}
    if len(tops) != 1 or not all("/" in f.path for f in files):
        return files
    prefix = tops.pop() + "/"
    return [replace(f, path=f.path.removeprefix(prefix)) for f in files]


def pair_files(old: Iterable[IndexedFile], new: Iterable[IndexedFile]) -> list[FilePair]:
    """Pair two artifacts' files by normalized path and classify each pair.

    Args:
        old: Files of the earlier artifact, with any sdist top-level directory already removed.
        new: Files of the later artifact, likewise.

    Returns:
        One pair per normalized path, sorted by path.
    """
    by_path_old = {normalize_path(f.path): f for f in old}
    by_path_new = {normalize_path(f.path): f for f in new}
    pairs = []
    for path in sorted(by_path_old.keys() | by_path_new.keys()):
        o, n = by_path_old.get(path), by_path_new.get(path)
        status: PairStatus
        if o is None:
            status = "added"
        elif n is None:
            status = "removed"
        else:
            status = "same" if o.same_content(n) else "changed"
        pairs.append(FilePair(path, status, o, n))
    return pairs


def _excluded(path: str) -> bool:
    return path.startswith("*.dist-info/") or bool(_SDIST_METADATA_RE.match(path))


def _source_path(path: str) -> str:
    # .data/purelib/x and .data/platlib/x install to site-packages like x; scripts and data keep their subdirectory.
    for scheme in ("purelib/", "platlib/"):
        if path.startswith(f"*.data/{scheme}"):
            return path.removeprefix(f"*.data/{scheme}")
    return path.removeprefix("*.data/")


def check_source(package: Iterable[IndexedFile], source: Iterable[IndexedFile]) -> SourceComparison:
    """Look for each package file in a source tree and compare their contents.

    Args:
        package: The package's files (a wheel, or an sdist with its top-level directory removed).
        source: The source tree's files, with any top-level directory removed.

    Returns:
        A check per package file, sorted by path, the root most files were found under, and the excluded paths.
    """
    source_by_path = {f.path: f for f in source}
    by_name: defaultdict[str, list[str]] = defaultdict(list)
    for path in source_by_path:
        by_name[path.rsplit("/", 1)[-1]].append(path)

    included: list[tuple[str, IndexedFile, str]] = []
    excluded: list[str] = []
    for f in package:
        path = normalize_path(f.path)
        if _excluded(path):
            excluded.append(f.path)
        else:
            included.append((f.path, f, _source_path(path)))

    votes: Counter[str] = Counter()
    for _, _, wanted in included:
        for candidate in by_name.get(wanted.rsplit("/", 1)[-1], ()):
            if candidate == wanted or candidate.endswith("/" + wanted):
                votes[candidate.removesuffix(wanted)] += 1
    roots = sorted(votes, key=lambda r: (-votes[r], len(r), r))

    checks = []
    for original, f, wanted in sorted(included, key=lambda t: t[0]):
        found = next((root + wanted for root in roots if root + wanted in source_by_path), None)
        if found is None:
            checks.append(SourceCheck(original, "missing", None, f.text))
        else:
            status: SourceStatus = "matches" if f.same_content(source_by_path[found]) else "differs"
            checks.append(SourceCheck(original, status, found, f.text))
    return SourceComparison(roots[0] if roots else "", tuple(checks), tuple(sorted(excluded)))
