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
