"""Recording files from concurrent workers against a real Postgres."""

import hashlib
import os
import threading
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session

from sightglass.db import models
from sightglass.storage.blobs import LocalBlobStore
from sightglass.worker.catalog import record_files


@pytest.fixture
def owners(migrated_engine: Engine) -> Iterator[list[int]]:
    """Four committed artifacts to record files for; everything this test commits is deleted afterwards."""
    with Session(migrated_engine) as session:
        package = models.Package(ecosystem="pypi", name="orbit-locks", display_name="orbit-locks")
        release = models.Release(package=package, version="1.0")
        artifacts = [
            models.Artifact(
                release=release, filename=f"orbit_locks-1.0-{i}.whl", kind="wheel", sha256=f"{i}" * 64, size=1
            )
            for i in range(4)
        ]
        session.add_all(artifacts)
        session.commit()
        ids = [a.id for a in artifacts]
    yield ids
    with Session(migrated_engine) as session:
        session.execute(delete(models.Package).where(models.Package.name == "orbit-locks"))
        session.execute(delete(models.Blob).where(models.Blob.sha256.in_(_created)))
        session.commit()


_created: list[str] = []


def _entry(root: Path, name: str) -> Any:
    data = os.urandom(32)
    (root / name).write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    _created.append(sha)
    return SimpleNamespace(kind="file", path=name, sha256=sha, size=len(data), file_type=None)


@pytest.mark.integration
def test_overlapping_files_in_opposite_orders_do_not_deadlock(
    migrated_engine: Engine, owners: list[int], tmp_path: Path
) -> None:
    """Two workers each record x then y and y then x across separate archives, inside one open transaction each."""
    blobs = LocalBlobStore(tmp_path / "blobs")
    x, y = _entry(tmp_path, "x"), _entry(tmp_path, "y")
    a, b = Session(migrated_engine), Session(migrated_engine)
    errors: list[BaseException] = []
    try:
        record_files(a, blobs, tmp_path, [x], artifact_id=owners[0])
        record_files(b, blobs, tmp_path, [y], artifact_id=owners[1])

        def second_b() -> None:
            try:
                record_files(b, blobs, tmp_path, [x], artifact_id=owners[2])
            except Exception as exc:  # Collected for the assertion below.
                errors.append(exc)

        worker = threading.Thread(target=second_b)
        worker.start()
        record_files(a, blobs, tmp_path, [y], artifact_id=owners[3])
        worker.join(timeout=30)
        assert not worker.is_alive() and errors == []
        a.commit()
        b.commit()
    finally:
        a.close()
        b.close()
