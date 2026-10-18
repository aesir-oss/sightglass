"""Type stubs for the Rust extension module built from crates/sightglass-py."""

from collections.abc import Collection
from os import PathLike
from typing import Final, Literal, final

HEAD_SIZE: Final[int]

def version() -> str:
    """Return the version of the Rust core library."""

def hash_file(path: str | PathLike[str]) -> tuple[str, int]:
    """Stream a file through sha256 without loading it into memory.

    Returns:
        The lowercase hex digest and the size in bytes.

    Raises:
        OSError: If the file can't be opened or read, for example FileNotFoundError.
    """

@final
class FileType:
    """The result of classifying a file."""

    @property
    def category(self) -> Literal["python", "text", "compiled", "archive", "other"]:
        """Broad kind of file."""
    @property
    def format(self) -> str:
        """Specific format, such as ``elf``, ``zip``, ``text`` or ``python``."""
    @property
    def encoding(self) -> Literal["utf-8", "utf-8-sig", "utf-16le", "utf-16be"] | None:
        """Text encoding for text and Python files, otherwise None."""

def classify(name: str, head: bytes) -> FileType:
    """Classify a file from its name and leading bytes (up to ``HEAD_SIZE`` are useful)."""

class ArchiveError(Exception):
    """An archive couldn't be read safely."""

class UnsafeArchiveError(ArchiveError):
    """The archive was refused: an unsafe path, link or file type, or a size, count or ratio limit."""

class ArchiveFormatError(ArchiveError):
    """The archive is damaged, or uses a feature that isn't supported."""

@final
class Limits:
    """Limits that bound the work an archive can cause. Unset arguments take the defaults."""

    def __init__(
        self,
        *,
        max_total_size: int | None = None,
        max_files: int | None = None,
        max_file_size: int | None = None,
        max_ratio: int | None = None,
        ratio_min_size: int | None = None,
    ) -> None:
        """Create limits, defaulting each unset value."""
    @property
    def max_total_size(self) -> int:
        """Largest total of decompressed bytes."""
    @property
    def max_files(self) -> int:
        """Largest number of files and links."""
    @property
    def max_file_size(self) -> int:
        """Largest single decompressed file."""
    @property
    def max_ratio(self) -> int:
        """Largest ratio of decompressed bytes to the archive's size."""
    @property
    def ratio_min_size(self) -> int:
        """Decompressed bytes after which the ratio is enforced."""

@final
class ArchiveEntry:
    """One file or link in an archive."""

    @property
    def path(self) -> str:
        """Normalized relative path with ``/`` separators."""
    @property
    def kind(self) -> Literal["file", "symlink", "hardlink"]:
        """File or link. Links are recorded but never created."""
    @property
    def size(self) -> int:
        """Decompressed size; 0 for links."""
    @property
    def sha256(self) -> str | None:
        """Hex digest of the content, for files."""
    @property
    def file_type(self) -> FileType | None:
        """Classification, for files."""
    @property
    def link_target(self) -> str | None:
        """Target as written in the archive, for links."""

def index_archive(path: str | PathLike[str], limits: Limits | None = None) -> list[ArchiveEntry]:
    """Hash and classify every entry of a zip, tar or tar.gz archive without writing to disk.

    Raises:
        UnsafeArchiveError: If the archive is refused.
        ArchiveFormatError: If it's damaged or unsupported.
        OSError: If it can't be read.
    """

def extract_archive(
    path: str | PathLike[str],
    dest: str | PathLike[str],
    limits: Limits | None = None,
    only: Collection[str] | None = None,
) -> list[ArchiveEntry]:
    """Extract an archive into ``dest``, which must not exist yet, and return its index.

    Only regular files and directories are written; with ``only``, just the files at those paths, though every entry
    is still checked, hashed and returned. On any error, ``dest`` is removed.

    Raises:
        UnsafeArchiveError: If the archive is refused.
        ArchiveFormatError: If it's damaged or unsupported, or can't be written to this file system: a path that is
            too long, or two that differ only in letter case where case is ignored.
        OSError: If it can't be read, or ``dest`` already exists.
    """

@final
class DiffLimits:
    """Limits that bound the work a line diff can cause. Unset arguments take the defaults."""

    def __init__(
        self,
        *,
        max_size: int | None = None,
        max_lines: int | None = None,
        timeout: float | None = None,
        context: int | None = None,
    ) -> None:
        """Create limits, defaulting each unset value.

        Raises:
            ValueError: If ``timeout`` isn't between 0 and 86400 seconds.
        """
    @property
    def max_size(self) -> int:
        """Largest input on either side, in bytes."""
    @property
    def max_lines(self) -> int:
        """Most lines on either side."""
    @property
    def timeout(self) -> float:
        """Seconds after which the diff stops looking for a minimal result."""
    @property
    def context(self) -> int:
        """Unchanged lines kept around each change."""

@final
class DiffLine:
    """One line of a hunk."""

    @property
    def kind(self) -> Literal["context", "added", "removed"]:
        """Whether the line is unchanged, added or removed."""
    @property
    def old_line(self) -> int | None:
        """1-based line number in the old file, for context and removed lines."""
    @property
    def new_line(self) -> int | None:
        """1-based line number in the new file, for context and added lines."""
    @property
    def text(self) -> str:
        """The line without its newline, with invalid UTF-8 replaced."""
    @property
    def missing_newline(self) -> bool:
        """The line is the last in its file and has no newline."""

@final
class Hunk:
    """A unified diff hunk. An empty side's start is the line before it, as in ``diff -u``."""

    @property
    def old_start(self) -> int:
        """First old line, 1-based."""
    @property
    def old_len(self) -> int:
        """Old lines in the hunk."""
    @property
    def new_start(self) -> int:
        """First new line, 1-based."""
    @property
    def new_len(self) -> int:
        """New lines in the hunk."""
    @property
    def lines(self) -> list[DiffLine]:
        """The hunk's lines in order."""

@final
class FileDiff:
    """The line diff of two inputs, or a result saying they were too large to diff."""

    @property
    def too_large(self) -> bool:
        """An input was over the size or line limit, so there are no hunks."""
    @property
    def hunks(self) -> list[Hunk]:
        """The hunks; empty when the inputs are identical."""
    @property
    def added(self) -> int:
        """Lines added."""
    @property
    def removed(self) -> int:
        """Lines removed."""
    @property
    def approximate(self) -> bool:
        """The deadline was reached, so the diff is correct but may not be minimal."""
    def added_lines(self) -> list[tuple[int, str]]:
        """Every added line as ``(line number in the new file, text)``."""

def diff_lines(old: bytes, new: bytes, limits: DiffLimits | None = None) -> FileDiff:
    """Diff two versions of a file line by line, comparing lines as bytes."""
