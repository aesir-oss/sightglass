"""Recording what the pipeline learned: packages, releases, artifacts, and the files inside archives."""

from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from sightglass import _core
from sightglass.db import models
from sightglass.ecosystems.pypi import PypiFile, PypiProject, PypiRelease
from sightglass.storage.blobs import BlobStore
from sightglass.storage.catalog import record_blob


def _upsert(session: Session, table: type[models.Base], keys: list[str], values: dict[str, object]) -> int:
    stmt = insert(table).values(**values)
    updates = {k: stmt.excluded[k] for k in values if k not in keys}
    stmt = (
        stmt.on_conflict_do_update(index_elements=keys, set_=updates)
        if updates
        else stmt.on_conflict_do_nothing(index_elements=keys)
    )
    row_id = session.execute(stmt.returning(table.id)).scalar()  # type: ignore[attr-defined]
    if row_id is None:
        where = [getattr(table, k) == values[k] for k in keys]
        row_id = session.scalar(select(table.id).where(*where))  # type: ignore[attr-defined]
    assert row_id is not None
    return int(row_id)


def record_package(session: Session, project: PypiProject) -> int:
    """Insert or update a PyPI package row; returns its id."""
    return _upsert(
        session,
        models.Package,
        ["ecosystem", "name"],
        {"ecosystem": "pypi", "name": project.normalized_name, "display_name": project.name},
    )


def record_release(session: Session, package_id: int, release: PypiRelease) -> int:
    """Insert or update a release row; returns its id."""
    return _upsert(
        session,
        models.Release,
        ["package_id", "version"],
        {
            "package_id": package_id,
            "version": release.version,
            "published_at": release.published_at,
            "yanked": release.yanked,
        },
    )


def record_artifact(session: Session, release_id: int, file: PypiFile) -> int:
    """Insert or update an artifact row; returns its id."""
    if file.kind not in ("wheel", "sdist"):
        raise ValueError(f"only wheels and sdists are analyzed, not {file.filename}")
    return _upsert(
        session,
        models.Artifact,
        ["release_id", "filename"],
        {
            "release_id": release_id,
            "filename": file.filename,
            "kind": file.kind,
            "sha256": file.sha256,
            "size": file.size,
            "uploaded_at": file.uploaded_at,
            "requires_python": file.requires_python,
        },
    )


def record_files(
    session: Session,
    blobs: BlobStore,
    root: Path,
    entries: Iterable[_core.ArchiveEntry],
    *,
    artifact_id: int | None = None,
    source_snapshot_id: int | None = None,
) -> int:
    """Store each extracted file's content in the blob store and record a ``file`` row, once per owner.

    Args:
        session: The session to write through; the caller commits.
        blobs: Where file contents go.
        root: The directory the archive was extracted into.
        entries: The archive's index from the extraction.
        artifact_id: The artifact the files belong to, or
        source_snapshot_id: the source snapshot they belong to.

    Returns:
        The number of files recorded; 0 when the owner's files were recorded before.
    """
    owner = models.File.artifact_id if artifact_id is not None else models.File.source_snapshot_id
    owner_id = artifact_id if artifact_id is not None else source_snapshot_id
    if session.scalar(select(models.File.id).where(owner == owner_id).limit(1)) is not None:
        return 0
    files = [e for e in entries if e.kind == "file" and e.sha256 is not None]
    # Workers recording overlapping files lock blob rows; taking them in one order across workers avoids deadlocks.
    for entry in sorted(files, key=lambda e: (e.sha256 or "", e.path)):
        record_blob(session, blobs.put_file(root / entry.path))
    for entry in files:
        session.add(
            models.File(
                artifact_id=artifact_id,
                source_snapshot_id=source_snapshot_id,
                path=entry.path,
                sha256=entry.sha256,
                size=entry.size,
                file_type=entry.file_type.category if entry.file_type else "other",
            )
        )
    session.flush()
    return len(files)
