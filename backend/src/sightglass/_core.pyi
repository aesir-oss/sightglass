"""Type stubs for the Rust extension module built from crates/sightglass-py."""

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
    path: str | PathLike[str], dest: str | PathLike[str], limits: Limits | None = None
) -> list[ArchiveEntry]:
    """Extract an archive into ``dest``, which must not exist yet, and return its index.

    Only regular files and directories are written. On any error, ``dest`` is removed.

    Raises:
        UnsafeArchiveError: If the archive is refused.
        ArchiveFormatError: If it's damaged or unsupported.
        OSError: If it can't be read, or ``dest`` already exists.
    """
