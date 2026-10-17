//! Write the generated seed corpus: valid archives shaped like wheels and sdists, and one archive per refusal rule.
//!
//! Run from `backend/fuzz` with `cargo run --bin make-seeds`. The output is committed; rerun after changing it.

use std::fs;
use std::io::{Cursor, Write};
use std::path::Path;

use flate2::Compression;
use flate2::write::GzEncoder;
use zip::write::SimpleFileOptions;

fn opts(method: zip::CompressionMethod) -> SimpleFileOptions {
    SimpleFileOptions::default().compression_method(method)
}

fn zip_of(files: &[(&str, &[u8])], method: zip::CompressionMethod) -> Vec<u8> {
    let mut w = zip::ZipWriter::new(Cursor::new(Vec::new()));
    for (name, data) in files {
        if name.ends_with('/') {
            w.add_directory(*name, opts(method)).unwrap();
        } else {
            w.start_file(*name, opts(method)).unwrap();
            w.write_all(data).unwrap();
        }
    }
    w.finish().unwrap().into_inner()
}

fn patch_central(mut bytes: Vec<u8>, flags: Option<u16>, mode: Option<u32>) -> Vec<u8> {
    let at = bytes.windows(4).position(|w| w == b"PK\x01\x02").unwrap();
    if let Some(flags) = flags {
        bytes[at + 8..at + 10].copy_from_slice(&flags.to_le_bytes());
    }
    if let Some(mode) = mode {
        bytes[at + 5] = 3;
        bytes[at + 38..at + 42].copy_from_slice(&(mode << 16).to_le_bytes());
    }
    bytes
}

/// A raw tar entry: name bytes, type, data, link target. Names bypass the tar crate's path checks.
type RawEntry<'a> = (&'a [u8], tar::EntryType, &'a [u8], &'a [u8]);

fn tar_of(entries: &[RawEntry<'_>]) -> Vec<u8> {
    let mut b = tar::Builder::new(Vec::new());
    for (name, kind, data, link) in entries {
        let mut h = tar::Header::new_gnu();
        let gnu = h.as_gnu_mut().unwrap();
        gnu.name[..name.len()].copy_from_slice(name);
        gnu.linkname[..link.len()].copy_from_slice(link);
        if *kind == tar::EntryType::GNUSparse {
            gnu.realsize.copy_from_slice(b"00000000000\0");
        }
        h.set_entry_type(*kind);
        h.set_size(data.len() as u64);
        h.set_mode(0o644);
        h.set_cksum();
        b.append(&h, *data).unwrap();
    }
    b.into_inner().unwrap()
}

fn tar_with_long_name() -> Vec<u8> {
    let mut b = tar::Builder::new(Vec::new());
    let name = format!("tidepool-1.0/{}/__init__.py", "deep/".repeat(40));
    let mut h = tar::Header::new_gnu();
    h.set_size(6);
    h.set_mode(0o644);
    b.append_data(&mut h, name, &b"x = 1\n"[..]).unwrap();
    b.into_inner().unwrap()
}

fn gzip(bytes: &[u8]) -> Vec<u8> {
    let mut e = GzEncoder::new(Vec::new(), Compression::default());
    e.write_all(bytes).unwrap();
    e.finish().unwrap()
}

fn write(dir: &Path, name: &str, bytes: &[u8]) {
    fs::write(dir.join(name), bytes).unwrap();
}

fn main() {
    use tar::EntryType::{
        Block, Char, Directory, Fifo, GNUSparse, Link, Regular, Symlink, XGlobalHeader,
    };
    use zip::CompressionMethod::{Deflated, Stored};

    let corpus = Path::new("corpus");
    let zips = corpus.join("unpack_zip");
    let tars = corpus.join("unpack_tar");
    let tgzs = corpus.join("unpack_tar_gz");
    for d in [&zips, &tars, &tgzs] {
        fs::create_dir_all(d).unwrap();
    }

    let wheel: &[(&str, &[u8])] = &[
        ("orbit/", b""),
        ("orbit/__init__.py", b"import os\nVERSION = '2.5.0'\n"),
        ("orbit/_speedups.so", b"\x7fELF\x02\x01\x01\x00"),
        (
            "orbit-2.5.0.dist-info/METADATA",
            b"Metadata-Version: 2.4\nName: orbit-client\n",
        ),
        ("orbit-2.5.0.dist-info/RECORD", b"orbit/__init__.py,,\n"),
    ];
    write(&zips, "gen-wheel-stored.zip", &zip_of(wheel, Stored));
    write(&zips, "gen-wheel-deflated.zip", &zip_of(wheel, Deflated));
    let mut w = zip::ZipWriter::new(Cursor::new(Vec::new()));
    w.start_file("pkg/__init__.py", opts(Stored)).unwrap();
    w.write_all(b"x = 1\n").unwrap();
    w.add_symlink("pkg/link", "__init__.py", opts(Stored))
        .unwrap();
    w.add_symlink("pkg/escape", "../../../etc/passwd", opts(Stored))
        .unwrap();
    write(&zips, "gen-symlinks.zip", &w.finish().unwrap().into_inner());
    for (i, name) in [
        "../evil.py",
        "/etc/cron.d/evil",
        "C:/evil.py",
        "pkg\\evil.py",
    ]
    .iter()
    .enumerate()
    {
        write(
            &zips,
            &format!("gen-unsafe-path-{i}.zip"),
            &zip_of(&[(name, b"x")], Stored),
        );
    }
    write(
        &zips,
        "gen-device.zip",
        &patch_central(zip_of(&[("dev/null", b"")], Stored), None, Some(0o020_644)),
    );
    write(
        &zips,
        "gen-encrypted.zip",
        &patch_central(zip_of(&[("a.py", b"x")], Stored), Some(1), None),
    );
    write(
        &zips,
        "gen-bomb.zip",
        &zip_of(&[("zeros.bin", &vec![0u8; 2 << 20])], Deflated),
    );

    let sdist = tar_of(&[
        (
            b"pax_global_header",
            XGlobalHeader,
            b"52 comment=0123456789abcdef0123456789abcdef01234567\n",
            b"",
        ),
        (b"tidepool-1.0/", Directory, b"", b""),
        (
            b"tidepool-1.0/setup.py",
            Regular,
            b"from setuptools import setup\nsetup()\n",
            b"",
        ),
        (
            b"tidepool-1.0/tidepool/__init__.py",
            Regular,
            b"x = 1\n",
            b"",
        ),
        (b"tidepool-1.0/README", Symlink, b"", b"docs/README.md"),
        (b"tidepool-1.0/copy.py", Link, b"", b"tidepool-1.0/setup.py"),
    ]);
    let unsafe_tars: Vec<(&str, Vec<u8>)> = vec![
        ("traversal", tar_of(&[(b"../evil", Regular, b"x", b"")])),
        ("absolute", tar_of(&[(b"/abs/evil", Regular, b"x", b"")])),
        ("non-utf8", tar_of(&[(b"pkg/\xff.py", Regular, b"x", b"")])),
        (
            "symlink-escape",
            tar_of(&[(b"pkg/passwd", Symlink, b"", b"../../etc/passwd")]),
        ),
        (
            "hardlink-escape",
            tar_of(&[(b"pkg/x", Link, b"", b"../outside")]),
        ),
        ("char-device", tar_of(&[(b"dev/sda", Char, b"", b"")])),
        ("block-device", tar_of(&[(b"dev/sdb", Block, b"", b"")])),
        ("fifo", tar_of(&[(b"run/pipe", Fifo, b"", b"")])),
        ("sparse", tar_of(&[(b"sparse.img", GNUSparse, b"", b"")])),
        (
            "duplicate",
            tar_of(&[
                (b"a.py", Regular, b"good", b""),
                (b"./a.py", Regular, b"evil", b""),
            ]),
        ),
    ];
    write(&tars, "gen-sdist.tar", &sdist);
    write(&tars, "gen-long-name.tar", &tar_with_long_name());
    write(&tgzs, "gen-sdist.tar.gz", &gzip(&sdist));
    write(&tgzs, "gen-long-name.tar.gz", &gzip(&tar_with_long_name()));
    for (name, bytes) in &unsafe_tars {
        write(&tars, &format!("gen-{name}.tar"), bytes);
        write(&tgzs, &format!("gen-{name}.tar.gz"), &gzip(bytes));
    }
}
