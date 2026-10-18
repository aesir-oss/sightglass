"""Tests for recording extracted files."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sightglass.storage.blobs import StoredBlob, blob_key
from sightglass.worker import catalog


class _Session:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def scalars(self, _: object) -> list[str]:
        return ["already-recorded"]

    def add(self, row: Any) -> None:
        self.added.append(row)

    def flush(self) -> None: ...

    def get_bind(self) -> object:
        return None


class _BlobSession:
    def __init__(self, **_: object) -> None:
        self.committed = False

    def __enter__(self) -> _BlobSession:
        return self

    def __exit__(self, *_: object) -> None: ...

    def commit(self) -> None:
        self.committed = True


class _Blobs:
    def __init__(self, entries: list[Any], stored: set[str]) -> None:
        self.sha = {e.path: e.sha256 for e in entries}
        self.stored = stored
        self.put: list[str] = []

    def exists(self, sha256: str) -> bool:
        return sha256 in self.stored

    def put_hashed(self, path: Path, sha256: str, size: int) -> StoredBlob:
        self.put.append(path.name)
        return StoredBlob(sha256, size, "key")


def test_blobs_are_recorded_in_sha256_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Blob rows are locked in one order by every worker, so concurrent analyses can't deadlock on them."""
    entries = [
        SimpleNamespace(kind="file", path=name, sha256=sha, size=1, file_type=None)
        for name, sha in [("c", "cc" * 32), ("a", "aa" * 32), ("b", "bb" * 32)]
    ] + [
        SimpleNamespace(kind="dir", path="d", sha256=None, size=0, file_type=None),
        SimpleNamespace(kind="file", path="already-recorded", sha256="dd" * 32, size=1, file_type=None),
    ]
    recorded: list[StoredBlob] = []
    monkeypatch.setattr(catalog, "record_blobs", lambda session, blobs: recorded.extend(blobs))
    monkeypatch.setattr(catalog, "Session", _BlobSession)
    # "a" is on disk and new; "b" is already in the store; "c" was never written out (a source file matched by hash).
    (tmp_path / "a").write_bytes(b"a")
    blobs = _Blobs(entries[:3], stored={"bb" * 32})
    session = _Session()
    count = catalog.record_files(session, blobs, tmp_path, entries, artifact_id=1)  # type: ignore[arg-type]
    assert [b.sha256 for b in recorded] == ["aa" * 32, "bb" * 32, "cc" * 32]
    assert [b.storage_key for b in recorded] == ["key", blob_key("bb" * 32), None]
    assert blobs.put == ["a"]
    assert count == 3 and [f.path for f in session.added] == ["c", "a", "b"]
