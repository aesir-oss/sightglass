"""Tests for sightglass.storage.blobs that need no disk."""

import pytest

from sightglass.storage import StoredBlob, blob_key

SHA = "ab" * 32


def test_blob_key_shards_by_two_prefixes() -> None:
    """Keys spread blobs over two directory levels."""
    assert blob_key(SHA) == f"ab/ab/{SHA}"


@pytest.mark.parametrize("bad", ["", "AB" * 32, "ab" * 31, "zz" * 32, f"../{SHA}"])
def test_blob_key_rejects_non_hashes(bad: str) -> None:
    """Anything but a lowercase hex digest is refused, so a key can never escape the store root."""
    with pytest.raises(ValueError, match="sha256"):
        blob_key(bad)


def test_stored_blob_is_a_value() -> None:
    """Results compare by content."""
    assert StoredBlob(SHA, 3, None) == StoredBlob(SHA, 3, None)
