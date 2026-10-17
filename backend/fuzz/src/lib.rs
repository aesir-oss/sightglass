//! Shared checks for the unpacker fuzz targets.

use std::io::Cursor;

use sightglass_core::unpack::{EntryKind, Format, Limits, index_reader};

/// Small limits so each input runs fast; refusals are fine, panics and broken invariants are not.
pub const LIMITS: Limits = Limits {
    max_total_size: 16 << 20,
    max_files: 2_000,
    max_file_size: 8 << 20,
    max_ratio: 100,
    ratio_min_size: 1 << 20,
};

/// Index `data` as `format` and assert the invariants every accepted archive must satisfy.
///
/// # Panics
///
/// When an accepted archive breaks an invariant; that is what the fuzzer is looking for.
pub fn check(data: &[u8], format: Format) {
    let Ok(entries) = index_reader(Cursor::new(data), data.len() as u64, Some(format), &LIMITS)
    else {
        return;
    };
    assert!(entries.len() as u64 <= LIMITS.max_files);
    let mut total = 0u64;
    let mut seen = std::collections::HashSet::new();
    for e in &entries {
        assert!(
            !e.path.is_empty() && !e.path.starts_with('/'),
            "unsafe path {:?}",
            e.path
        );
        assert!(
            !e.path.contains('\\') && !e.path.contains('\0'),
            "unsafe path {:?}",
            e.path
        );
        assert!(
            e.path
                .split('/')
                .all(|p| !p.is_empty() && p != "." && p != ".."),
            "unsafe path {:?}",
            e.path
        );
        assert!(seen.insert(e.path.clone()), "duplicate {:?}", e.path);
        match e.kind {
            EntryKind::File => {
                assert!(e.size <= LIMITS.max_file_size);
                assert_eq!(e.sha256.as_ref().map(String::len), Some(64));
                assert!(e.file_type.is_some() && e.link_target.is_none());
                total += e.size;
            }
            EntryKind::Symlink | EntryKind::HardLink => {
                assert_eq!(
                    (e.size, e.sha256.is_none(), e.file_type.is_none()),
                    (0, true, true)
                );
                assert!(
                    e.link_target
                        .as_ref()
                        .is_some_and(|t| !t.is_empty() && !t.starts_with('/'))
                );
            }
        }
    }
    assert!(total <= LIMITS.max_total_size);
}
