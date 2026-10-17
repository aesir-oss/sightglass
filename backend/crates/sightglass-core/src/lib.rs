//! Core analysis primitives for Sightglass: archive unpacking, hashing, file typing and line diffs.
//!
//! This crate is pure Rust with no Python dependency; `sightglass-py` exposes it to Python.

pub mod filetype;
pub mod hash;
pub mod unpack;

/// Version of this crate, as published in its manifest.
#[must_use]
pub fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_matches_manifest() {
        assert_eq!(version(), "0.1.0");
    }
}
