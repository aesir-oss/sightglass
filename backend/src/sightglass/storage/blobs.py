"""Blob stores keyed by sha256. Each distinct content is stored once, whatever file or release it came from."""

import hashlib
import os
import re
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from sightglass import _core
from sightglass.log import get_logger

log = get_logger(__name__)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_MAX_SIZE = 16 * 1024 * 1024


class BlobNotFoundError(KeyError):
    """No content is stored for the requested hash."""


class BlobCorruptError(Exception):
    """Stored content no longer matches its hash."""


@dataclass(frozen=True)
class StoredBlob:
    """The outcome of putting content into a store.

    Attributes:
        sha256: Lowercase hex digest of the content.
        size: Content size in bytes.
        storage_key: Where the content is kept, or None when it was too large to store.
    """

    sha256: str
    size: int
    storage_key: str | None


def blob_key(sha256: str) -> str:
    """Return the storage key for a hash: two levels of two-character prefixes, then the full hash.

    Args:
        sha256: Lowercase hex digest.

    Returns:
        A relative key such as ``ab/cd/abcd...``.

    Raises:
        ValueError: If ``sha256`` isn't 64 lowercase hex characters.
    """
    if not _SHA256_RE.match(sha256):
        raise ValueError(f"not a lowercase sha256 hex digest: {sha256!r}")
    return f"{sha256[:2]}/{sha256[2:4]}/{sha256}"


class BlobStore(Protocol):
    """Content-addressed storage. Implementations must make puts idempotent and atomic, and verify on read."""

    max_size: int

    def put_bytes(self, data: bytes) -> StoredBlob:
        """Store content held in memory."""
        ...

    def put_file(self, path: Path) -> StoredBlob:
        """Store the content of a file on disk."""
        ...

    def read(self, sha256: str) -> bytes:
        """Return stored content after checking it still matches its hash."""
        ...

    def exists(self, sha256: str) -> bool:
        """Report whether content for this hash is stored."""
        ...


class LocalBlobStore:
    """A blob store in a directory on local disk.

    Content is written to a temporary file in the same directory tree, flushed to disk, then renamed into place, so a
    reader never sees a partial blob. Content larger than ``max_size`` is hashed but not kept.
    """

    def __init__(self, root: Path, max_size: int = DEFAULT_MAX_SIZE) -> None:
        """Open or create a store rooted at ``root``.

        Args:
            root: Directory that holds the blobs; created if missing.
            max_size: Largest content, in bytes, that is stored. Larger content is only hashed.
        """
        self.root = root
        self.max_size = max_size
        self._tmp = root / ".tmp"
        self._tmp.mkdir(parents=True, exist_ok=True)

    def path_for(self, sha256: str) -> Path:
        """Return where content with this hash is, or would be, stored."""
        return self.root / blob_key(sha256)

    def exists(self, sha256: str) -> bool:
        """Report whether content for this hash is stored."""
        return self.path_for(sha256).is_file()

    def put_bytes(self, data: bytes) -> StoredBlob:
        """Store content held in memory.

        Args:
            data: The content.

        Returns:
            The content's hash, size and storage key (None if it exceeds ``max_size``).
        """
        sha256 = hashlib.sha256(data).hexdigest()
        if len(data) > self.max_size:
            return StoredBlob(sha256, len(data), None)
        if not self.exists(sha256):
            with self._temp_file() as (fh, tmp_path):
                fh.write(data)
                self._commit(fh, tmp_path, sha256)
        return StoredBlob(sha256, len(data), blob_key(sha256))

    def put_file(self, path: Path) -> StoredBlob:
        """Store the content of a file on disk.

        The hash is computed from the copy that is stored, so a file changing during the copy can't produce a blob
        under the wrong key.

        Args:
            path: The file to store. It isn't modified or moved.

        Returns:
            The content's hash, size and storage key (None if it exceeds ``max_size``).
        """
        if path.stat().st_size > self.max_size:
            sha256, size = _core.hash_file(path)
            if size > self.max_size:
                return StoredBlob(sha256, size, None)
        with self._temp_file() as (fh, tmp_path):
            with path.open("rb") as src:
                shutil.copyfileobj(src, fh)
            fh.flush()
            sha256, size = _core.hash_file(tmp_path)
            if size > self.max_size:
                return StoredBlob(sha256, size, None)
            if not self.exists(sha256):
                self._commit(fh, tmp_path, sha256)
        return StoredBlob(sha256, size, blob_key(sha256))

    def read(self, sha256: str) -> bytes:
        """Return stored content after checking it still matches its hash.

        Args:
            sha256: Lowercase hex digest.

        Returns:
            The content.

        Raises:
            BlobNotFoundError: If nothing is stored for the hash.
            BlobCorruptError: If the stored bytes no longer hash to ``sha256``.
        """
        path = self.path_for(sha256)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            raise BlobNotFoundError(sha256) from None
        actual = hashlib.sha256(data).hexdigest()
        if actual != sha256:
            log.error("blob_corrupt", sha256=sha256, actual=actual, path=str(path))
            raise BlobCorruptError(f"blob {sha256} hashes to {actual}")
        return data

    @contextmanager
    def _temp_file(self) -> Iterator[tuple[BinaryIO, Path]]:
        """Yield a new file in the store's temp directory; it is removed on exit unless renamed into place."""
        fd, name = tempfile.mkstemp(dir=self._tmp)
        tmp_path = Path(name)
        try:
            with os.fdopen(fd, "wb") as fh:
                yield fh, tmp_path
        finally:
            tmp_path.unlink(missing_ok=True)

    def _commit(self, fh: BinaryIO, tmp_path: Path, sha256: str) -> None:
        """Flush the temp file to disk and rename it to its key."""
        fh.flush()
        os.fsync(fh.fileno())
        dest = self.path_for(sha256)
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp_path, dest)
