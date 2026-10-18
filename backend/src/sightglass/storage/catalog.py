"""Recording stored blobs in Postgres."""

from collections.abc import Iterable

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from sightglass.db.models import Blob
from sightglass.storage.blobs import StoredBlob


def record_blob(session: Session, blob: StoredBlob) -> None:
    """Insert a ``blob`` row, or fill in its storage key if an earlier put didn't store the content.

    Recording the same blob twice is a no-op, so callers don't need to check first.

    Args:
        session: The session to write through; the caller commits.
        blob: What a blob store returned.
    """
    stmt = insert(Blob).values(sha256=blob.sha256, size=blob.size, storage_key=blob.storage_key)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Blob.sha256],
        set_={"storage_key": func.coalesce(Blob.storage_key, stmt.excluded.storage_key)},
    )
    session.execute(stmt)


# Rows per statement when recording many blobs at once.
BATCH = 1000


def record_blobs(session: Session, blobs: Iterable[StoredBlob]) -> None:
    """Record many blobs like :func:`record_blob`, a batch per statement, in the order given.

    Callers that can run concurrently pass blobs sorted by sha256, so every caller takes row locks in the same order.

    Args:
        session: The session to write through; the caller commits.
        blobs: What a blob store returned; a sha256 that appears twice is recorded once.
    """
    unique = list({b.sha256: b for b in blobs}.values())
    for start in range(0, len(unique), BATCH):
        batch = unique[start : start + BATCH]
        stmt = insert(Blob).values([{"sha256": b.sha256, "size": b.size, "storage_key": b.storage_key} for b in batch])
        stmt = stmt.on_conflict_do_update(
            index_elements=[Blob.sha256],
            set_={"storage_key": func.coalesce(Blob.storage_key, stmt.excluded.storage_key)},
        )
        session.execute(stmt)
