"""Integration tests for the local blob store and the blob catalog."""

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from sightglass.db.models import Blob
from sightglass.storage import (
    BlobCorruptError,
    BlobNotFoundError,
    LocalBlobStore,
    StoredBlob,
    blob_key,
    record_blob,
)

CONTENT = b"import os\nos.getenv('HOME')\n"
SHA = hashlib.sha256(CONTENT).hexdigest()


@pytest.fixture
def store(tmp_path: Path) -> LocalBlobStore:
    """A store in a fresh directory that keeps content up to 64 bytes."""
    return LocalBlobStore(tmp_path / "blobs", max_size=64)


def leftovers(store: LocalBlobStore) -> list[Path]:
    """Files left in the store's temp directory."""
    return list((store.root / ".tmp").iterdir())


@pytest.mark.integration
def test_put_bytes_round_trip(store: LocalBlobStore) -> None:
    """Content is stored under its sharded key and read back intact."""
    stored = store.put_bytes(CONTENT)

    assert stored == StoredBlob(SHA, len(CONTENT), blob_key(SHA))
    assert (store.root / blob_key(SHA)).read_bytes() == CONTENT
    assert store.exists(SHA)
    assert store.read(SHA) == CONTENT
    assert leftovers(store) == []


@pytest.mark.integration
def test_put_is_idempotent(store: LocalBlobStore) -> None:
    """Putting the same content again returns the same result and leaves the stored file untouched."""
    first = store.put_bytes(CONTENT)
    mtime = store.path_for(SHA).stat().st_mtime_ns

    assert store.put_bytes(CONTENT) == first
    assert store.path_for(SHA).stat().st_mtime_ns == mtime
    assert leftovers(store) == []


@pytest.mark.integration
def test_put_file_dedupes_with_put_bytes(store: LocalBlobStore, tmp_path: Path) -> None:
    """A file with the same content maps to the same blob, and the source file isn't changed."""
    source = tmp_path / "orbit.py"
    source.write_bytes(CONTENT)
    store.put_bytes(CONTENT)

    assert store.put_file(source) == StoredBlob(SHA, len(CONTENT), blob_key(SHA))
    assert source.read_bytes() == CONTENT
    assert leftovers(store) == []


@pytest.mark.integration
def test_put_file_new_content(store: LocalBlobStore, tmp_path: Path) -> None:
    """A file whose content isn't stored yet is copied in."""
    source = tmp_path / "tidepool.py"
    source.write_bytes(b"x = 1\n")
    stored = store.put_file(source)

    assert store.read(stored.sha256) == b"x = 1\n"


@pytest.mark.integration
@pytest.mark.parametrize("size", [65, 4096])
def test_content_over_limit_is_hashed_not_stored(store: LocalBlobStore, tmp_path: Path, size: int) -> None:
    """Large content gets a hash and size but no storage key, and nothing is written."""
    data = b"\x7fELF" + bytes(size - 4)
    source = tmp_path / "big.so"
    source.write_bytes(data)
    expected = StoredBlob(hashlib.sha256(data).hexdigest(), size, None)

    assert store.put_bytes(data) == expected
    assert store.put_file(source) == expected
    assert not store.exists(expected.sha256)
    assert leftovers(store) == []


@pytest.mark.integration
def test_put_file_missing_source_leaves_nothing(store: LocalBlobStore, tmp_path: Path) -> None:
    """A failed put cleans up its temp file."""
    with pytest.raises(FileNotFoundError):
        store.put_file(tmp_path / "absent.py")
    assert leftovers(store) == []


@pytest.mark.integration
def test_read_missing_raises(store: LocalBlobStore) -> None:
    """Reading a hash that was never stored raises BlobNotFoundError."""
    with pytest.raises(BlobNotFoundError):
        store.read(SHA)


@pytest.mark.integration
def test_read_detects_corruption(store: LocalBlobStore) -> None:
    """Stored bytes that no longer match their hash are refused, not returned."""
    store.put_bytes(CONTENT)
    store.path_for(SHA).write_bytes(b"tampered")

    with pytest.raises(BlobCorruptError, match=SHA):
        store.read(SHA)


@pytest.mark.integration
def test_record_blob_is_idempotent(db_session: Session, store: LocalBlobStore) -> None:
    """Recording the same blob twice leaves one row."""
    stored = store.put_bytes(CONTENT)
    record_blob(db_session, stored)
    record_blob(db_session, stored)

    rows = db_session.scalars(select(Blob)).all()
    assert [(r.sha256, r.size, r.storage_key) for r in rows] == [(SHA, len(CONTENT), blob_key(SHA))]


@pytest.mark.integration
def test_record_blob_fills_missing_key_but_never_clears_one(db_session: Session) -> None:
    """A later put that stored the content fills the key; a later unstored put doesn't erase it."""
    record_blob(db_session, StoredBlob(SHA, len(CONTENT), None))
    record_blob(db_session, StoredBlob(SHA, len(CONTENT), blob_key(SHA)))
    record_blob(db_session, StoredBlob(SHA, len(CONTENT), None))

    assert db_session.scalar(select(Blob.storage_key).where(Blob.sha256 == SHA)) == blob_key(SHA)
