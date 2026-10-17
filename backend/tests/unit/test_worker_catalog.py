"""Tests for recording extracted files."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sightglass.storage.blobs import StoredBlob
from sightglass.worker import catalog


class _Session:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def scalar(self, _: object) -> None:
        return None

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
    def __init__(self, entries: list[Any]) -> None:
        self.sha = {e.path: e.sha256 for e in entries}

    def put_file(self, path: Path) -> StoredBlob:
        return StoredBlob(self.sha[path.name], 1, None)


def test_blobs_are_recorded_in_sha256_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Blob rows are locked in one order by every worker, so concurrent analyses can't deadlock on them."""
    entries = [
        SimpleNamespace(kind="file", path=name, sha256=sha, size=1, file_type=None)
        for name, sha in [("c", "cc" * 32), ("a", "aa" * 32), ("b", "bb" * 32)]
    ] + [SimpleNamespace(kind="dir", path="d", sha256=None, size=0, file_type=None)]
    recorded: list[str] = []
    monkeypatch.setattr(catalog, "record_blob", lambda session, blob: recorded.append(blob.sha256))
    monkeypatch.setattr(catalog, "Session", _BlobSession)
    session = _Session()
    count = catalog.record_files(session, _Blobs(entries[:3]), tmp_path, entries, artifact_id=1)  # type: ignore[arg-type]
    assert recorded == ["aa" * 32, "bb" * 32, "cc" * 32]
    assert count == 3 and [f.path for f in session.added] == ["c", "a", "b"]
