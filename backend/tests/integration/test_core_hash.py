"""Integration tests for hashing real files through the Rust core."""

import hashlib
from pathlib import Path

import pytest

from sightglass import _core


@pytest.mark.integration
@pytest.mark.parametrize("size", [0, 1, 64 * 1024, 3 * 64 * 1024 + 17])
def test_hash_file_matches_hashlib(tmp_path: Path, size: int) -> None:
    """Digests and sizes match hashlib for files around the read buffer size."""
    path = tmp_path / "blob.bin"
    data = bytes(i % 251 for i in range(size))
    path.write_bytes(data)

    assert _core.hash_file(path) == (hashlib.sha256(data).hexdigest(), size)
    assert _core.hash_file(str(path)) == (hashlib.sha256(data).hexdigest(), size)


@pytest.mark.integration
def test_hash_file_missing_raises_file_not_found(tmp_path: Path) -> None:
    """A missing file raises the usual Python exception."""
    with pytest.raises(FileNotFoundError):
        _core.hash_file(tmp_path / "absent.whl")


@pytest.mark.integration
def test_hash_file_directory_raises_os_error(tmp_path: Path) -> None:
    """Reading a directory fails with an OSError rather than hashing nothing."""
    with pytest.raises(OSError, match=r"[Dd]irectory"):
        _core.hash_file(tmp_path)
