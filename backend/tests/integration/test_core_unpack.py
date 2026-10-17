"""Integration tests for indexing and extracting real archives through the Rust core."""

import hashlib
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from sightglass import _core


def make_wheel(path: Path, files: dict[str, bytes]) -> Path:
    """Write a zip with the given members."""
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return path


def make_sdist(path: Path, files: dict[str, bytes], links: dict[str, str] | None = None) -> Path:
    """Write a .tar.gz with the given members and symlinks."""
    with tarfile.open(path, "w:gz") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        for name, target in (links or {}).items():
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            tf.addfile(info)
    return path


@pytest.mark.integration
def test_index_wheel(tmp_path: Path) -> None:
    """Each file gets its path, size, hash and type; nothing is written."""
    wheel = make_wheel(
        tmp_path / "orbit_client-2.5.0-py3-none-any.whl",
        {"orbit/__init__.py": b"import os\n", "orbit/_ext.so": b"\x7fELF\x02"},
    )
    entries = _core.index_archive(wheel)

    assert [(e.path, e.kind, e.size) for e in entries] == [
        ("orbit/__init__.py", "file", 10),
        ("orbit/_ext.so", "file", 5),
    ]
    assert entries[0].sha256 == hashlib.sha256(b"import os\n").hexdigest()
    assert entries[0].file_type is not None
    assert entries[0].file_type.category == "python"
    assert sorted(p.name for p in tmp_path.iterdir()) == [wheel.name]


@pytest.mark.integration
def test_extract_sdist_records_links(tmp_path: Path) -> None:
    """Files are extracted; in-root symlinks are listed but not created."""
    sdist = make_sdist(
        tmp_path / "tidepool-1.0.tar.gz",
        {"tidepool-1.0/tidepool/__init__.py": b"x = 1\n"},
        {"tidepool-1.0/README": "docs/README.md"},
    )
    dest = tmp_path / "out"
    entries = _core.extract_archive(sdist, dest)

    assert (dest / "tidepool-1.0/tidepool/__init__.py").read_bytes() == b"x = 1\n"
    assert not (dest / "tidepool-1.0/README").exists()
    link = next(e for e in entries if e.kind == "symlink")
    assert (link.link_target, link.sha256, link.file_type) == ("docs/README.md", None, None)
    assert "symlink" in repr(link)


@pytest.mark.integration
@pytest.mark.parametrize("name", ["../evil.py", "/etc/cron.d/evil", "pkg/../../evil.py"])
def test_unsafe_paths_refused(tmp_path: Path, name: str) -> None:
    """Paths that leave the root raise UnsafeArchiveError, and extraction leaves no output."""
    wheel = make_wheel(tmp_path / "evil.whl", {"ok.py": b"x", name: b"x"})
    with pytest.raises(_core.UnsafeArchiveError, match="unsafe path"):
        _core.index_archive(wheel)
    with pytest.raises(_core.UnsafeArchiveError):
        _core.extract_archive(wheel, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.integration
def test_escaping_symlink_refused(tmp_path: Path) -> None:
    """A symlink that resolves outside the root is refused."""
    sdist = make_sdist(tmp_path / "evil.tar.gz", {}, {"pkg/key": "../../../home/user/.ssh/id_ed25519"})
    with pytest.raises(_core.UnsafeArchiveError, match="points outside"):
        _core.index_archive(sdist)


@pytest.mark.integration
def test_limits_apply(tmp_path: Path) -> None:
    """Configured limits are enforced on the real decompressed bytes."""
    wheel = make_wheel(tmp_path / "big.whl", {"a.bin": b"1234", "b.bin": b"5678"})
    with pytest.raises(_core.UnsafeArchiveError, match="more than 1 files"):
        _core.index_archive(wheel, _core.Limits(max_files=1))
    with pytest.raises(_core.UnsafeArchiveError, match="larger than 3 bytes"):
        _core.index_archive(wheel, _core.Limits(max_file_size=3))


@pytest.mark.integration
def test_format_and_io_errors(tmp_path: Path) -> None:
    """Non-archives raise ArchiveFormatError; missing files and existing destinations raise OSError."""
    junk = tmp_path / "junk.whl"
    junk.write_bytes(b"not an archive at all")
    with pytest.raises(_core.ArchiveFormatError):
        _core.index_archive(junk)
    with pytest.raises(FileNotFoundError):
        _core.index_archive(tmp_path / "absent.whl")
    wheel = make_wheel(tmp_path / "ok.whl", {"a.py": b"x"})
    with pytest.raises(FileExistsError):
        _core.extract_archive(wheel, tmp_path)
    assert wheel.exists()
