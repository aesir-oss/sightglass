"""Recording stored blobs in Postgres."""

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
