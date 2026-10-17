//! Tests for the unpacker, including a crafted archive for every refusal rule.

use std::io::{Cursor, Write};
use std::sync::atomic::{AtomicU32, Ordering};

use flate2::Compression;
use flate2::write::GzEncoder;
use zip::write::SimpleFileOptions;

use super::*;
use crate::filetype::Category;

static COUNTER: AtomicU32 = AtomicU32::new(0);

/// A directory under the system temp dir, removed on drop.
struct TempDir(PathBuf);

impl TempDir {
    fn new() -> Self {
        let n = COUNTER.fetch_add(1, Ordering::Relaxed);
        let dir = std::env::temp_dir().join(format!("sg-unpack-{}-{n}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        Self(dir)
    }

    fn write(&self, name: &str, bytes: &[u8]) -> PathBuf {
        let path = self.0.join(name);
        fs::write(&path, bytes).unwrap();
        path
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn stored() -> SimpleFileOptions {
    SimpleFileOptions::default().compression_method(zip::CompressionMethod::Stored)
}

fn zip_of(files: &[(&str, &[u8])]) -> Vec<u8> {
    let mut w = zip::ZipWriter::new(Cursor::new(Vec::new()));
    for (name, data) in files {
        if name.ends_with('/') {
            w.add_directory(*name, stored()).unwrap();
        } else {
            w.start_file(*name, stored()).unwrap();
            w.write_all(data).unwrap();
        }
    }
    w.finish().unwrap().into_inner()
}

fn zip_with_symlink(name: &str, target: &str) -> Vec<u8> {
    let mut w = zip::ZipWriter::new(Cursor::new(Vec::new()));
    w.start_file("pkg/__init__.py", stored()).unwrap();
    w.write_all(b"x = 1\n").unwrap();
    w.add_symlink(name, target, stored()).unwrap();
    w.finish().unwrap().into_inner()
}

/// Patch the first central directory header: `flags` at offset 8 and the Unix mode in the external attributes.
fn patch_central(mut bytes: Vec<u8>, flags: Option<u16>, mode: Option<u32>) -> Vec<u8> {
    let at = bytes.windows(4).position(|w| w == b"PK\x01\x02").unwrap();
    if let Some(flags) = flags {
        bytes[at + 8..at + 10].copy_from_slice(&flags.to_le_bytes());
    }
    if let Some(mode) = mode {
        bytes[at + 5] = 3; // "version made by" host = Unix, so the mode is honored
        bytes[at + 38..at + 42].copy_from_slice(&(mode << 16).to_le_bytes());
    }
    bytes
}

enum TarItem<'a> {
    Dir(&'a [u8]),
    File(&'a [u8], &'a [u8]),
    Link(&'a [u8], tar::EntryType, &'a [u8]),
    Special(&'a [u8], tar::EntryType),
    PaxGlobal,
}

/// Build a tar from raw header names, bypassing the tar crate's own path checks.
fn tar_of(items: &[TarItem<'_>]) -> Vec<u8> {
    let mut b = tar::Builder::new(Vec::new());
    for item in items {
        let mut h = tar::Header::new_gnu();
        let (name, kind, data, link): (&[u8], _, &[u8], Option<&[u8]>) = match item {
            TarItem::Dir(name) => (name, tar::EntryType::Directory, b"", None),
            TarItem::File(name, data) => (name, tar::EntryType::Regular, data, None),
            TarItem::Link(name, kind, target) => (name, *kind, b"", Some(target)),
            TarItem::Special(name, kind) => (name, *kind, b"", None),
            TarItem::PaxGlobal => (
                b"pax_global_header",
                tar::EntryType::XGlobalHeader,
                b"52 comment=0123\n",
                None,
            ),
        };
        let gnu = h.as_gnu_mut().unwrap();
        gnu.name[..name.len()].copy_from_slice(name);
        if let Some(target) = link {
            gnu.linkname[..target.len()].copy_from_slice(target);
        }
        if kind == tar::EntryType::GNUSparse {
            gnu.realsize.copy_from_slice(b"00000000000\0");
        }
        h.set_entry_type(kind);
        h.set_size(data.len() as u64);
        h.set_mode(0o644);
        h.set_cksum();
        b.append(&h, data).unwrap();
    }
    b.into_inner().unwrap()
}

fn gzip(bytes: &[u8]) -> Vec<u8> {
    let mut e = GzEncoder::new(Vec::new(), Compression::default());
    e.write_all(bytes).unwrap();
    e.finish().unwrap()
}

fn index_bytes(bytes: &[u8], limits: &Limits) -> Result<Vec<Entry>> {
    let dir = TempDir::new();
    index(&dir.write("archive", bytes), limits)
}

fn sha(data: &[u8]) -> String {
    to_hex(&Sha256::digest(data))
}

#[test]
fn indexes_a_wheel_without_writing() {
    let wheel = zip_of(&[
        ("orbit/", b""),
        ("orbit/__init__.py", b"import os\n"),
        ("orbit/_speedups.so", b"\x7fELF\x02\x01"),
        ("orbit-2.5.0.dist-info/METADATA", b"Name: orbit-client\n"),
    ]);
    let dir = TempDir::new();
    let path = dir.write("orbit-2.5.0-py3-none-any.whl", &wheel);
    let entries = index(&path, &Limits::default()).unwrap();

    let summary: Vec<_> = entries
        .iter()
        .map(|e| {
            (
                e.path.as_str(),
                e.kind,
                e.size,
                e.file_type.as_ref().map(|t| t.category),
            )
        })
        .collect();
    assert_eq!(
        summary,
        [
            (
                "orbit/__init__.py",
                EntryKind::File,
                10,
                Some(Category::Python)
            ),
            (
                "orbit/_speedups.so",
                EntryKind::File,
                6,
                Some(Category::Compiled)
            ),
            (
                "orbit-2.5.0.dist-info/METADATA",
                EntryKind::File,
                19,
                Some(Category::Text)
            ),
        ]
    );
    assert_eq!(
        entries[0].sha256.as_deref(),
        Some(sha(b"import os\n").as_str())
    );
    assert_eq!(fs::read_dir(&dir.0).unwrap().count(), 1);
}

#[test]
fn extracts_files_and_records_links_without_creating_them() {
    let dir = TempDir::new();
    let archive = dir.write("a.zip", &zip_with_symlink("pkg/link", "__init__.py"));
    let dest = dir.0.join("out");
    let entries = extract(&archive, &dest, &Limits::default()).unwrap();

    assert_eq!(fs::read(dest.join("pkg/__init__.py")).unwrap(), b"x = 1\n");
    assert!(fs::symlink_metadata(dest.join("pkg/link")).is_err());
    let link = entries
        .iter()
        .find(|e| e.kind == EntryKind::Symlink)
        .unwrap();
    assert_eq!(link.link_target.as_deref(), Some("__init__.py"));
    assert_eq!((link.size, link.sha256.as_ref()), (0, None));
}

#[test]
fn reads_github_style_tarball() {
    let tarball = gzip(&tar_of(&[
        TarItem::PaxGlobal,
        TarItem::File(
            b"kestrel-orbit-0123abc/./src/orbit/__init__.py",
            b"VERSION = '2.5.0'\n",
        ),
        TarItem::Link(
            b"kestrel-orbit-0123abc/docs/README",
            tar::EntryType::Symlink,
            b"../README.md",
        ),
        TarItem::Link(
            b"kestrel-orbit-0123abc/copy.py",
            tar::EntryType::Link,
            b"kestrel-orbit-0123abc/src/orbit/__init__.py",
        ),
    ]));
    let entries = index_bytes(&tarball, &Limits::default()).unwrap();
    let paths: Vec<_> = entries.iter().map(|e| (e.path.as_str(), e.kind)).collect();
    assert_eq!(
        paths,
        [
            (
                "kestrel-orbit-0123abc/src/orbit/__init__.py",
                EntryKind::File
            ),
            ("kestrel-orbit-0123abc/docs/README", EntryKind::Symlink),
            ("kestrel-orbit-0123abc/copy.py", EntryKind::HardLink),
        ]
    );
}

#[test]
fn extracts_tar_with_directories() {
    let dir = TempDir::new();
    let tar = tar_of(&[
        TarItem::Dir(b"tidepool-1.0/"),
        TarItem::Dir(b"tidepool-1.0/empty/"),
        TarItem::File(b"tidepool-1.0/tidepool/__init__.py", b"x = 1\n"),
    ]);
    let archive = dir.write("tidepool-1.0.tar.gz", &gzip(&tar));
    let dest = dir.0.join("out");
    let entries = extract(&archive, &dest, &Limits::default()).unwrap();

    assert_eq!(entries.len(), 1);
    assert!(dest.join("tidepool-1.0/empty").is_dir());
    assert_eq!(
        fs::read(dest.join("tidepool-1.0/tidepool/__init__.py")).unwrap(),
        b"x = 1\n"
    );
}

#[test]
fn corrupt_tar_header_is_malformed() {
    let mut tar = tar_of(&[TarItem::File(b"a.py", b"x")]);
    tar[148] ^= 0x01; // checksum field
    assert!(matches!(
        index_bytes(&tar, &Limits::default()).unwrap_err(),
        Error::Malformed(_)
    ));
}

#[test]
fn reads_plain_tar() {
    let tar = tar_of(&[TarItem::File(
        b"tidepool-1.0/setup.py",
        b"from setuptools import setup\n",
    )]);
    assert_eq!(index_bytes(&tar, &Limits::default()).unwrap().len(), 1);
}

#[test]
fn refuses_unsafe_zip_paths() {
    for name in [
        "../evil.py",
        "pkg/../../evil.py",
        "/etc/cron.d/evil",
        "C:/evil.py",
        "pkg\\evil.py",
    ] {
        let err = index_bytes(&zip_of(&[(name, b"x")]), &Limits::default()).unwrap_err();
        assert!(matches!(err, Error::UnsafePath { .. }), "{name}: {err}");
        assert!(err.is_refusal());
    }
}

#[test]
fn refuses_unsafe_tar_paths() {
    let cases: [(&[u8], &str); 5] = [
        (b"../evil", "parent directory component"),
        (b"/abs/evil", "absolute path"),
        (b"pkg/\xff.py", "not UTF-8"),
        (b"./", "empty path"),
        (b"pkg/../../x", "parent directory component"),
    ];
    for (name, reason) in cases {
        let err =
            index_bytes(&tar_of(&[TarItem::File(name, b"x")]), &Limits::default()).unwrap_err();
        match err {
            Error::UnsafePath { reason: r, .. } => assert_eq!(r, reason),
            other => panic!("{}: {other}", String::from_utf8_lossy(name)),
        }
    }
}

#[test]
fn refuses_links_that_escape() {
    let cases = [
        tar_of(&[TarItem::Link(
            b"pkg/passwd",
            tar::EntryType::Symlink,
            b"../../etc/passwd",
        )]),
        tar_of(&[TarItem::Link(
            b"pkg/passwd",
            tar::EntryType::Symlink,
            b"/etc/passwd",
        )]),
        tar_of(&[TarItem::Link(b"pkg/x", tar::EntryType::Link, b"../outside")]),
        tar_of(&[TarItem::Link(b"pkg/x", tar::EntryType::Symlink, b"")]),
        zip_with_symlink("pkg/link", "../../../home/user/.ssh/id_ed25519"),
    ];
    for archive in cases {
        let err = index_bytes(&archive, &Limits::default()).unwrap_err();
        assert!(matches!(err, Error::UnsafeLink { .. }), "{err}");
    }
}

#[test]
fn refuses_special_files() {
    for kind in [
        tar::EntryType::Char,
        tar::EntryType::Block,
        tar::EntryType::Fifo,
    ] {
        let err = index_bytes(
            &tar_of(&[TarItem::Special(b"dev/sda", kind)]),
            &Limits::default(),
        )
        .unwrap_err();
        assert!(matches!(err, Error::SpecialFile { .. }), "{err}");
    }
    let device = patch_central(zip_of(&[("dev/null", b"")]), None, Some(0o020_644));
    assert!(matches!(
        index_bytes(&device, &Limits::default()).unwrap_err(),
        Error::SpecialFile { .. }
    ));
}

#[test]
fn refuses_duplicate_paths() {
    let tar = tar_of(&[
        TarItem::File(b"pkg/a.py", b"good"),
        TarItem::File(b"pkg/./a.py", b"evil"),
    ]);
    assert!(matches!(
        index_bytes(&tar, &Limits::default()).unwrap_err(),
        Error::Duplicate { .. }
    ));
}

#[test]
fn enforces_file_count() {
    let limits = Limits {
        max_files: 2,
        ..Limits::default()
    };
    let zip = zip_of(&[("a", b"1"), ("b", b"2"), ("c", b"3")]);
    assert!(matches!(
        index_bytes(&zip, &limits).unwrap_err(),
        Error::TooManyFiles { limit: 2 }
    ));
    let tar = tar_of(&[
        TarItem::File(b"a", b"1"),
        TarItem::File(b"b", b"2"),
        TarItem::File(b"c", b"3"),
    ]);
    assert!(matches!(
        index_bytes(&tar, &limits).unwrap_err(),
        Error::TooManyFiles { limit: 2 }
    ));
}

#[test]
fn enforces_file_and_total_size_on_real_bytes() {
    let per_file = Limits {
        max_file_size: 4,
        ..Limits::default()
    };
    assert!(matches!(
        index_bytes(&zip_of(&[("a", b"12345")]), &per_file).unwrap_err(),
        Error::FileTooLarge { limit: 4, .. }
    ));
    let total = Limits {
        max_total_size: 6,
        ..Limits::default()
    };
    assert!(matches!(
        index_bytes(&zip_of(&[("a", b"1234"), ("b", b"5678")]), &total).unwrap_err(),
        Error::TotalTooLarge { limit: 6 }
    ));
}

#[test]
fn stops_zip_bombs_by_ratio() {
    let mut w = zip::ZipWriter::new(Cursor::new(Vec::new()));
    let deflated =
        SimpleFileOptions::default().compression_method(zip::CompressionMethod::Deflated);
    w.start_file("zeros.bin", deflated).unwrap();
    w.write_all(&vec![0u8; 4 << 20]).unwrap();
    let bomb = w.finish().unwrap().into_inner();
    let limits = Limits {
        ratio_min_size: 1 << 20,
        ..Limits::default()
    };
    assert!(matches!(
        index_bytes(&bomb, &limits).unwrap_err(),
        Error::RatioExceeded { limit: 100 }
    ));
    // Below the threshold, a small, very compressible archive is fine.
    let small = Limits {
        ratio_min_size: 8 << 20,
        ..Limits::default()
    };
    assert_eq!(index_bytes(&bomb, &small).unwrap()[0].size, 4 << 20);
}

#[test]
fn refused_extraction_leaves_no_output() {
    let dir = TempDir::new();
    let archive = dir.write(
        "a.tar",
        &tar_of(&[
            TarItem::File(b"ok.py", b"x"),
            TarItem::File(b"../evil", b"x"),
        ]),
    );
    let dest = dir.0.join("out");
    assert!(extract(&archive, &dest, &Limits::default()).is_err());
    assert!(!dest.exists());
}

#[test]
fn extraction_never_reuses_an_existing_directory() {
    let dir = TempDir::new();
    let archive = dir.write("a.zip", &zip_of(&[("a.py", b"x")]));
    let err = extract(&archive, &dir.0, &Limits::default()).unwrap_err();
    assert!(matches!(&err, Error::Io(e) if e.kind() == io::ErrorKind::AlreadyExists));
    assert!(dir.0.join("a.zip").exists());
}

#[test]
fn unreadable_and_unsupported_archives() {
    assert!(matches!(
        index_bytes(b"not an archive", &Limits::default()).unwrap_err(),
        Error::Unsupported(_)
    ));
    let truncated = zip_of(&[("a.py", b"x")])[..30].to_vec();
    assert!(matches!(
        index_bytes(&truncated, &Limits::default()).unwrap_err(),
        Error::Malformed(_)
    ));
    let bad_gzip = b"\x1f\x8b\x08\x00garbage".to_vec();
    let err = index_bytes(&bad_gzip, &Limits::default()).unwrap_err();
    assert!(!err.is_refusal(), "{err}");
    let encrypted = patch_central(zip_of(&[("a.py", b"x")]), Some(1), None);
    assert!(matches!(
        index_bytes(&encrypted, &Limits::default()).unwrap_err(),
        Error::Unsupported(_)
    ));
    let sparse = tar_of(&[TarItem::Special(b"sparse.img", tar::EntryType::GNUSparse)]);
    assert!(matches!(
        index_bytes(&sparse, &Limits::default()).unwrap_err(),
        Error::Unsupported(_)
    ));
    let missing = index(Path::new("/nonexistent/sightglass.whl"), &Limits::default()).unwrap_err();
    assert!(matches!(missing, Error::Io(_)));
}

#[test]
fn index_reader_from_memory_with_or_without_format() {
    let wheel = zip_of(&[("orbit/__init__.py", b"x = 1\n")]);
    let len = wheel.len() as u64;
    let detected = index_reader(Cursor::new(&wheel), len, None, &Limits::default()).unwrap();
    let forced = index_reader(
        Cursor::new(&wheel),
        len,
        Some(Format::Zip),
        &Limits::default(),
    )
    .unwrap();
    assert_eq!(detected, forced);
    let wrong = index_reader(
        Cursor::new(&wheel),
        len,
        Some(Format::Tar),
        &Limits::default(),
    );
    assert!(wrong.is_err());
    let junk = index_reader(Cursor::new(b"junk"), 4, None, &Limits::default()).unwrap_err();
    assert!(matches!(junk, Error::Unsupported(_)));
}

#[test]
fn path_rules() {
    assert_eq!(safe_path(b"./pkg//mod.py").unwrap(), "pkg/mod.py");
    assert!(matches!(
        safe_path(b"pkg/\0.py"),
        Err(Error::UnsafePath {
            reason: "contains a NUL byte",
            ..
        })
    ));
    assert!(symlink_stays_inside("pkg/sub/link", "../other.py"));
    assert!(symlink_stays_inside("link", "./pkg/x"));
    assert!(!symlink_stays_inside("link", "../x"));
    assert!(!symlink_stays_inside("pkg/link", "C:/x"));
    assert!(!symlink_stays_inside("pkg/link", "a\\b"));
}

#[test]
fn names_and_messages() {
    assert_eq!(
        [EntryKind::File, EntryKind::Symlink, EntryKind::HardLink].map(EntryKind::as_str),
        ["file", "symlink", "hardlink"]
    );
    assert_eq!(detect(b"PK\x03\x04"), Some(Format::Zip));
    assert_eq!(detect(b"\x1f\x8b"), Some(Format::TarGz));
    assert_eq!(detect(b"hello"), None);
    let messages = [
        Error::Io(io::Error::other("x")).to_string(),
        Error::Malformed("x".into()).to_string(),
        Error::Unsupported("x".into()).to_string(),
        Error::UnsafePath {
            path: "p".into(),
            reason: "r",
        }
        .to_string(),
        Error::UnsafeLink {
            path: "p".into(),
            target: "t".into(),
        }
        .to_string(),
        Error::SpecialFile { path: "p".into() }.to_string(),
        Error::Duplicate { path: "p".into() }.to_string(),
        Error::CaseCollision {
            path: "p".into(),
            other: "P".into(),
        }
        .to_string(),
        Error::PathTooLong { path: "p".into() }.to_string(),
        Error::TooManyFiles { limit: 1 }.to_string(),
        Error::FileTooLarge {
            path: "p".into(),
            limit: 1,
        }
        .to_string(),
        Error::TotalTooLarge { limit: 1 }.to_string(),
        Error::RatioExceeded { limit: 1 }.to_string(),
    ];
    assert!(messages.iter().all(|m| !m.is_empty()));
    assert!(std::error::Error::source(&Error::Io(io::Error::other("x"))).is_some());
    assert!(std::error::Error::source(&Error::TooManyFiles { limit: 1 }).is_none());
}

#[test]
fn names_differing_only_in_case_extract_or_say_why() {
    // Both files are written on a case-sensitive file system; on one that ignores case the error names both paths.
    let dir = TempDir::new();
    let archive = dir.write(
        "case.zip",
        &zip_of(&[("pkg/SampleH.gif", b"upper"), ("pkg/sampleh.gif", b"lower")]),
    );
    match extract(&archive, &dir.0.join("out"), &Limits::default()) {
        Ok(entries) => assert_eq!(entries.len(), 2),
        Err(Error::CaseCollision { path, other }) => {
            assert_eq!(
                (path.as_str(), other.as_str()),
                ("pkg/sampleh.gif", "pkg/SampleH.gif")
            );
            assert!(!Error::CaseCollision { path, other }.is_refusal());
        }
        Err(e) => panic!("unexpected error: {e}"),
    }
}

#[test]
fn a_path_too_long_for_the_file_system_is_named() {
    let dir = TempDir::new();
    let long = format!("pkg/{}.py", "n".repeat(300));
    let archive = dir.write("long.zip", &zip_of(&[(long.as_str(), b"x")]));
    let err = extract(&archive, &dir.0.join("out"), &Limits::default()).unwrap_err();
    assert!(
        matches!(&err, Error::PathTooLong { path } if *path == long),
        "{err}"
    );
    assert!(!err.is_refusal());
}
