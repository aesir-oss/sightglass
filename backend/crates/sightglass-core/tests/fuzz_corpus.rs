//! Replays the committed fuzz seeds and regression inputs on stable Rust, so a fixed crash stays fixed.
//!
//! Each file under `fuzz/corpus/<target>/` and `fuzz/regressions/<target>/` is indexed as that target's format.
//! Refusals and format errors are expected; a panic fails the test.

use std::fs;
use std::io::Cursor;
use std::path::{Path, PathBuf};

use sightglass_core::unpack::{Format, Limits, index_reader};

const TARGETS: [(&str, Format); 3] = [
    ("unpack_zip", Format::Zip),
    ("unpack_tar", Format::Tar),
    ("unpack_tar_gz", Format::TarGz),
];

fn fuzz_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fuzz")
}

fn inputs(kind: &str, target: &str) -> Vec<PathBuf> {
    let dir = fuzz_dir().join(kind).join(target);
    let mut files: Vec<_> = fs::read_dir(&dir)
        .unwrap_or_else(|e| panic!("{}: {e}", dir.display()))
        .map(|e| e.unwrap().path())
        .filter(|p| {
            p.is_file()
                && !p
                    .file_name()
                    .is_some_and(|n| n.to_string_lossy().starts_with('.'))
        })
        .collect();
    files.sort();
    files
}

#[test]
fn corpus_and_regressions_never_panic() {
    let limits = Limits {
        max_total_size: 16 << 20,
        max_files: 2_000,
        max_file_size: 8 << 20,
        max_ratio: 100,
        ratio_min_size: 1 << 20,
    };
    let mut replayed = 0;
    for (target, format) in TARGETS {
        let seeds = inputs("corpus", target);
        assert!(!seeds.is_empty(), "no seeds for {target}");
        for path in seeds.into_iter().chain(inputs("regressions", target)) {
            let data = fs::read(&path).unwrap();
            let _ = index_reader(Cursor::new(&data), data.len() as u64, Some(format), &limits);
            replayed += 1;
        }
    }
    assert!(replayed >= 30, "only {replayed} inputs replayed");
}

#[test]
fn real_seeds_index_cleanly() {
    let wheel =
        fs::read(fuzz_dir().join("corpus/unpack_zip/real-sampleproject-4.0.0-py3-none-any.whl"))
            .unwrap();
    let entries = index_reader(
        Cursor::new(&wheel),
        wheel.len() as u64,
        None,
        &Limits::default(),
    )
    .unwrap();
    assert!(entries.iter().any(|e| e.path == "sample/__init__.py"));

    let sdist =
        fs::read(fuzz_dir().join("corpus/unpack_tar_gz/real-sampleproject-621e497-github.tar.gz"))
            .unwrap();
    let entries = index_reader(
        Cursor::new(&sdist),
        sdist.len() as u64,
        None,
        &Limits::default(),
    )
    .unwrap();
    assert!(
        entries
            .iter()
            .all(|e| e.path.starts_with("sampleproject-621e4974"))
    );
}
