"""Pairing and the source check on archives indexed by the Rust core."""

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from sightglass import _core
from sightglass.rules.pairing import IndexedFile, check_source, pair_files, strip_top_level


def wheel(path: Path, version: str, files: dict[str, bytes]) -> Path:
    """Write an invented orbit-client wheel."""
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
        zf.writestr(f"orbit_client-{version}.dist-info/METADATA", f"Version: {version}\n")
    return path


def sdist(path: Path, files: dict[str, bytes]) -> Path:
    """Write an invented orbit-client sdist, with a symlink."""
    with tarfile.open(path, "w:gz") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(f"orbit_client-2.5.0/{name}")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo("orbit_client-2.5.0/LICENSE")
        link.type, link.linkname = tarfile.SYMTYPE, "LICENSE.txt"
        tf.addfile(link)
    return path


def indexed(path: Path) -> list[IndexedFile]:
    """Index an archive into IndexedFiles."""
    return [IndexedFile.from_entry(e) for e in _core.index_archive(path)]


@pytest.mark.integration
def test_wheels_pair_and_check_against_sdist(tmp_path: Path) -> None:
    """Real entries carry hashes and text types through pairing and the source check."""
    old = wheel(tmp_path / "old.whl", "2.4.1", {"orbit/__init__.py": b"V = 1\n", "orbit/_fast.so": b"\x7fELF\x02"})
    new = wheel(tmp_path / "new.whl", "2.5.0", {"orbit/__init__.py": b"V = 2\n", "orbit/_fast.so": b"\x7fELF\x02"})
    src = sdist(tmp_path / "orbit_client-2.5.0.tar.gz", {"PKG-INFO": b"x\n", "src/orbit/__init__.py": b"V = 2\n"})

    pairs = {p.path: p for p in pair_files(indexed(old), indexed(new))}
    assert {path: (p.status, p.text) for path, p in pairs.items()} == {
        "*.dist-info/METADATA": ("changed", True),
        "orbit/__init__.py": ("changed", True),
        "orbit/_fast.so": ("same", False),
    }
    fast = pairs["orbit/_fast.so"].new
    assert fast is not None and fast.compiled

    source = strip_top_level(indexed(src))
    link = next(f for f in source if f.path == "LICENSE")
    assert (link.sha256, link.link_target, link.text) == (None, "LICENSE.txt", False)
    checks = {c.path: c.status for c in check_source(indexed(new), source).files}
    assert checks == {"orbit/__init__.py": "matches", "orbit/_fast.so": "missing"}


@pytest.mark.integration
def test_from_entry_removes_prefix(tmp_path: Path) -> None:
    """A known top-level directory can be removed while converting."""
    src = sdist(tmp_path / "s.tar.gz", {"setup.py": b"\n"})
    paths = sorted(IndexedFile.from_entry(e, "orbit_client-2.5.0/").path for e in _core.index_archive(src))
    assert paths == ["LICENSE", "setup.py"]
