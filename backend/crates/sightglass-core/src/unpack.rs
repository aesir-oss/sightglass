//! Safe reading of untrusted archives: wheels and zip sdists, `.tar.gz` sdists and GitHub tag archives.
//!
//! Every entry is checked before anything touches disk. Paths must stay inside the archive root, links are recorded
//! but never created, special files are refused, and size, count and compression-ratio limits are enforced on the
//! bytes actually decompressed, not on what the archive declares.

use std::collections::HashSet;
use std::fmt;
use std::fs::{self, File, OpenOptions};
use std::io::{self, BufReader, Read, Seek, Write};
use std::path::{Path, PathBuf};

use flate2::read::GzDecoder;
use sha2::{Digest, Sha256};

use crate::filetype::{self, FileType, HEAD_SIZE};
use crate::hash::to_hex;

const BUFFER_SIZE: usize = 64 * 1024;
const MAX_LINK_TARGET: u64 = 4096;

/// Limits that bound the work an archive can cause.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Limits {
    /// Largest total of decompressed bytes across all files.
    pub max_total_size: u64,
    /// Largest number of files and links.
    pub max_files: u64,
    /// Largest single decompressed file.
    pub max_file_size: u64,
    /// Largest ratio of decompressed bytes to the archive's size on disk.
    pub max_ratio: u64,
    /// The ratio is only enforced once this many bytes have been decompressed, so small archives of text pass.
    pub ratio_min_size: u64,
}

impl Default for Limits {
    fn default() -> Self {
        Self {
            max_total_size: 4 << 30,
            max_files: 100_000,
            max_file_size: 1 << 30,
            max_ratio: 100,
            ratio_min_size: 16 << 20,
        }
    }
}

/// Container formats the unpacker reads.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Format {
    /// Zip: wheels, zip sdists, GitHub zipballs.
    Zip,
    /// Gzip-compressed tar: sdists and GitHub tarballs.
    TarGz,
    /// Uncompressed tar.
    Tar,
}

/// Detect the container format from an archive's leading bytes.
#[must_use]
pub fn detect(head: &[u8]) -> Option<Format> {
    match filetype::classify("", head).format {
        "zip" => Some(Format::Zip),
        "gzip" => Some(Format::TarGz),
        "tar" => Some(Format::Tar),
        _ => None,
    }
}

/// What an index entry is.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EntryKind {
    /// A regular file, hashed and classified.
    File,
    /// A symbolic link; recorded with its target, never created.
    Symlink,
    /// A tar hard link to another path in the archive; recorded, never created.
    HardLink,
}

impl EntryKind {
    /// Lowercase name for storage and Python.
    #[must_use]
    pub fn as_str(self) -> &'static str {
        match self {
            Self::File => "file",
            Self::Symlink => "symlink",
            Self::HardLink => "hardlink",
        }
    }
}

/// One file or link in an archive.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Entry {
    /// Normalized relative path with `/` separators.
    pub path: String,
    /// File or link.
    pub kind: EntryKind,
    /// Decompressed size in bytes; 0 for links.
    pub size: u64,
    /// Hex sha256 of the content, for files.
    pub sha256: Option<String>,
    /// Classification from the name and leading bytes, for files.
    pub file_type: Option<FileType>,
    /// Link target as written in the archive, for links.
    pub link_target: Option<String>,
}

/// Why an archive couldn't be read or was refused.
#[derive(Debug)]
pub enum Error {
    /// Reading the archive or writing output failed.
    Io(io::Error),
    /// The archive is damaged or isn't the format it claims.
    Malformed(String),
    /// A valid archive feature Sightglass doesn't handle: encryption, sparse files, unknown entry types.
    Unsupported(String),
    /// An entry path that is absolute, climbs out of the root, or can't be represented safely.
    UnsafePath {
        /// The path as written in the archive (lossily decoded).
        path: String,
        /// What was wrong with it.
        reason: &'static str,
    },
    /// A link whose target is outside the archive root.
    UnsafeLink {
        /// The link's path.
        path: String,
        /// Its target.
        target: String,
    },
    /// A device file, FIFO or socket.
    SpecialFile {
        /// The entry's path.
        path: String,
    },
    /// The same path appears twice, so different tools could see different content.
    Duplicate {
        /// The repeated path.
        path: String,
    },
    /// More files than [`Limits::max_files`].
    TooManyFiles {
        /// The limit that was exceeded.
        limit: u64,
    },
    /// One file larger than [`Limits::max_file_size`].
    FileTooLarge {
        /// The entry's path.
        path: String,
        /// The limit that was exceeded.
        limit: u64,
    },
    /// More decompressed bytes than [`Limits::max_total_size`].
    TotalTooLarge {
        /// The limit that was exceeded.
        limit: u64,
    },
    /// Decompressed bytes exceed [`Limits::max_ratio`] times the archive size.
    RatioExceeded {
        /// The limit that was exceeded.
        limit: u64,
    },
}

impl Error {
    /// True when the archive was refused for safety or limits, rather than being unreadable.
    #[must_use]
    pub fn is_refusal(&self) -> bool {
        !matches!(
            self,
            Self::Io(_) | Self::Malformed(_) | Self::Unsupported(_)
        )
    }
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(e) => write!(f, "I/O error: {e}"),
            Self::Malformed(m) => write!(f, "malformed archive: {m}"),
            Self::Unsupported(m) => write!(f, "unsupported archive feature: {m}"),
            Self::UnsafePath { path, reason } => write!(f, "unsafe path {path:?}: {reason}"),
            Self::UnsafeLink { path, target } => {
                write!(f, "link {path:?} points outside the archive: {target:?}")
            }
            Self::SpecialFile { path } => write!(f, "special file {path:?}"),
            Self::Duplicate { path } => write!(f, "duplicate path {path:?}"),
            Self::TooManyFiles { limit } => write!(f, "more than {limit} files"),
            Self::FileTooLarge { path, limit } => {
                write!(f, "file {path:?} is larger than {limit} bytes")
            }
            Self::TotalTooLarge { limit } => write!(f, "more than {limit} bytes in total"),
            Self::RatioExceeded { limit } => {
                write!(f, "decompresses to more than {limit} times its size")
            }
        }
    }
}

impl std::error::Error for Error {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Io(e) => Some(e),
            _ => None,
        }
    }
}

impl From<io::Error> for Error {
    fn from(e: io::Error) -> Self {
        Self::Io(e)
    }
}

impl From<zip::result::ZipError> for Error {
    fn from(e: zip::result::ZipError) -> Self {
        match e {
            zip::result::ZipError::Io(io) => Self::Io(io),
            zip::result::ZipError::UnsupportedArchive(m) => Self::Unsupported(m.to_string()),
            other => Self::Malformed(other.to_string()),
        }
    }
}

/// Result type for this module.
pub type Result<T> = std::result::Result<T, Error>;

/// Hash and classify every entry of the archive at `archive` without writing anything to disk.
///
/// # Errors
///
/// Returns an [`Error`] for unreadable, unsupported or refused archives.
pub fn index(archive: &Path, limits: &Limits) -> Result<Vec<Entry>> {
    walk(archive, None, limits)
}

/// Extract the archive at `archive` into `dest`, which must not exist yet, and return its index.
///
/// Only regular files and directories are written. If the archive is refused or unreadable partway through, `dest`
/// is removed so no partial output is left behind.
///
/// # Errors
///
/// Returns an [`Error`] for unreadable, unsupported or refused archives, or if `dest` already exists.
pub fn extract(archive: &Path, dest: &Path, limits: &Limits) -> Result<Vec<Entry>> {
    fs::create_dir(dest)?;
    let result = walk(archive, Some(dest), limits);
    if result.is_err() {
        // Best effort: the original error is what the caller needs, not a cleanup failure.
        let _ = fs::remove_dir_all(dest);
    }
    result
}

fn walk(archive: &Path, dest: Option<&Path>, limits: &Limits) -> Result<Vec<Entry>> {
    let mut file = File::open(archive)?;
    let compressed_len = file.metadata()?.len();
    let mut head = Vec::with_capacity(512);
    (&mut file).take(512).read_to_end(&mut head)?;
    file.rewind()?;
    let mut state = State::new(limits, compressed_len, dest);
    match detect(&head) {
        Some(Format::Zip) => walk_zip(BufReader::new(file), &mut state)?,
        Some(Format::TarGz) => walk_tar(GzDecoder::new(BufReader::new(file)), &mut state)?,
        Some(Format::Tar) => walk_tar(BufReader::new(file), &mut state)?,
        None => {
            return Err(Error::Unsupported(
                "not a zip, tar or gzip archive".to_owned(),
            ));
        }
    }
    Ok(state.entries)
}

const S_IFMT: u32 = 0o170_000;
const S_IFREG: u32 = 0o100_000;
const S_IFDIR: u32 = 0o040_000;
const S_IFLNK: u32 = 0o120_000;

fn walk_zip<R: Read + Seek>(reader: R, state: &mut State<'_>) -> Result<()> {
    let mut zip = zip::ZipArchive::new(reader)?;
    if zip.len() as u64 > state.limits.max_files {
        return Err(Error::TooManyFiles {
            limit: state.limits.max_files,
        });
    }
    for i in 0..zip.len() {
        let mut entry = zip.by_index(i)?;
        let raw = entry.name_raw().to_vec();
        if entry.encrypted() {
            return Err(Error::Unsupported(format!(
                "encrypted entry {}",
                String::from_utf8_lossy(&raw)
            )));
        }
        let mode_type = entry.unix_mode().map_or(0, |m| m & S_IFMT);
        let path = safe_path(&raw)?;
        match mode_type {
            S_IFLNK => {
                let mut target = Vec::new();
                (&mut entry)
                    .take(MAX_LINK_TARGET)
                    .read_to_end(&mut target)?;
                state.add_link(path, EntryKind::Symlink, &target)?;
            }
            0 | S_IFREG | S_IFDIR if entry.is_dir() || mode_type == S_IFDIR => {
                state.add_dir(&path)?;
            }
            0 | S_IFREG => state.add_file(path, &mut entry)?,
            _ => return Err(Error::SpecialFile { path }),
        }
    }
    Ok(())
}

fn walk_tar<R: Read>(reader: R, state: &mut State<'_>) -> Result<()> {
    let mut archive = tar::Archive::new(reader);
    for entry in archive.entries().map_err(tar_error)? {
        let mut entry = entry.map_err(tar_error)?;
        let kind = entry.header().entry_type();
        if kind.is_pax_global_extensions() {
            continue;
        }
        let raw = entry.path_bytes().into_owned();
        let path = safe_path(&raw)?;
        if kind.is_dir() {
            state.add_dir(&path)?;
        } else if kind.is_file() || kind.is_contiguous() {
            state.add_file(path, &mut entry)?;
        } else if kind.is_symlink() || kind.is_hard_link() {
            let target = entry.link_name_bytes().unwrap_or_default().into_owned();
            let link_kind = if kind.is_symlink() {
                EntryKind::Symlink
            } else {
                EntryKind::HardLink
            };
            state.add_link(path, link_kind, &target)?;
        } else if kind.is_character_special() || kind.is_block_special() || kind.is_fifo() {
            return Err(Error::SpecialFile { path });
        } else {
            return Err(Error::Unsupported(format!(
                "tar entry type {:?} at {path:?}",
                kind.as_byte() as char
            )));
        }
    }
    Ok(())
}

fn tar_error(e: io::Error) -> Error {
    if e.kind() == io::ErrorKind::Other || e.kind() == io::ErrorKind::InvalidData {
        Error::Malformed(e.to_string())
    } else {
        Error::Io(e)
    }
}

/// Normalize an entry path, refusing anything that could resolve outside the archive root.
fn safe_path(raw: &[u8]) -> Result<String> {
    let lossy = || String::from_utf8_lossy(raw).into_owned();
    let unsafe_path = |reason| Error::UnsafePath {
        path: lossy(),
        reason,
    };
    let text = std::str::from_utf8(raw).map_err(|_| unsafe_path("not UTF-8"))?;
    if text.contains('\0') {
        return Err(unsafe_path("contains a NUL byte"));
    }
    if text.contains('\\') {
        return Err(unsafe_path("contains a backslash"));
    }
    if text.starts_with('/') {
        return Err(unsafe_path("absolute path"));
    }
    if text.as_bytes().get(1) == Some(&b':') {
        return Err(unsafe_path("drive letter"));
    }
    let mut parts = Vec::new();
    for part in text.split('/') {
        match part {
            "" | "." => {}
            ".." => return Err(unsafe_path("parent directory component")),
            p => parts.push(p),
        }
    }
    if parts.is_empty() {
        return Err(unsafe_path("empty path"));
    }
    Ok(parts.join("/"))
}

/// Check that a symlink at `link` (a normalized path) with `target` resolves inside the root.
fn symlink_stays_inside(link: &str, target: &str) -> bool {
    if target.is_empty()
        || target.starts_with('/')
        || target.contains('\\')
        || target.as_bytes().get(1) == Some(&b':')
    {
        return false;
    }
    let mut depth: Vec<&str> = link.split('/').collect();
    depth.pop();
    for part in target.split('/') {
        match part {
            "" | "." => {}
            ".." => {
                if depth.pop().is_none() {
                    return false;
                }
            }
            p => depth.push(p),
        }
    }
    true
}

struct State<'a> {
    limits: &'a Limits,
    compressed_len: u64,
    dest: Option<&'a Path>,
    total: u64,
    files: u64,
    seen: HashSet<String>,
    entries: Vec<Entry>,
}

impl<'a> State<'a> {
    fn new(limits: &'a Limits, compressed_len: u64, dest: Option<&'a Path>) -> Self {
        Self {
            limits,
            compressed_len,
            dest,
            total: 0,
            files: 0,
            seen: HashSet::new(),
            entries: Vec::new(),
        }
    }

    fn claim(&mut self, path: &str) -> Result<()> {
        if !self.seen.insert(path.to_owned()) {
            return Err(Error::Duplicate {
                path: path.to_owned(),
            });
        }
        self.files += 1;
        if self.files > self.limits.max_files {
            return Err(Error::TooManyFiles {
                limit: self.limits.max_files,
            });
        }
        Ok(())
    }

    fn output_path(dest: &Path, path: &str) -> PathBuf {
        path.split('/')
            .fold(dest.to_path_buf(), |acc, part| acc.join(part))
    }

    fn add_dir(&mut self, path: &str) -> Result<()> {
        if let Some(dest) = self.dest {
            fs::create_dir_all(Self::output_path(dest, path))?;
        }
        Ok(())
    }

    fn add_link(&mut self, path: String, kind: EntryKind, raw_target: &[u8]) -> Result<()> {
        let target = String::from_utf8_lossy(raw_target).into_owned();
        let inside = match kind {
            EntryKind::Symlink => {
                std::str::from_utf8(raw_target).is_ok() && symlink_stays_inside(&path, &target)
            }
            _ => safe_path(raw_target).is_ok(),
        };
        if !inside {
            return Err(Error::UnsafeLink { path, target });
        }
        self.claim(&path)?;
        self.entries.push(Entry {
            path,
            kind,
            size: 0,
            sha256: None,
            file_type: None,
            link_target: Some(target),
        });
        Ok(())
    }

    fn add_file(&mut self, path: String, reader: &mut dyn Read) -> Result<()> {
        self.claim(&path)?;
        let mut out = match self.dest {
            Some(dest) => {
                let target = Self::output_path(dest, &path);
                if let Some(parent) = target.parent() {
                    fs::create_dir_all(parent)?;
                }
                Some(
                    OpenOptions::new()
                        .write(true)
                        .create_new(true)
                        .open(target)?,
                )
            }
            None => None,
        };
        let mut hasher = Sha256::new();
        let mut head = Vec::with_capacity(HEAD_SIZE);
        let mut buffer = vec![0u8; BUFFER_SIZE];
        let mut size: u64 = 0;
        loop {
            let n = match reader.read(&mut buffer) {
                Ok(0) => break,
                Ok(n) => n,
                Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
                Err(e) => return Err(Error::Io(e)),
            };
            let chunk = &buffer[..n];
            size += n as u64;
            self.total += n as u64;
            self.check_sizes(&path, size)?;
            hasher.update(chunk);
            let room = HEAD_SIZE - head.len();
            head.extend_from_slice(&chunk[..room.min(n)]);
            if let Some(out) = out.as_mut() {
                out.write_all(chunk)?;
            }
        }
        if let Some(out) = out.as_mut() {
            out.flush()?;
        }
        let file_type = filetype::classify(&path, &head);
        self.entries.push(Entry {
            path,
            kind: EntryKind::File,
            size,
            sha256: Some(to_hex(&hasher.finalize())),
            file_type: Some(file_type),
            link_target: None,
        });
        Ok(())
    }

    fn check_sizes(&self, path: &str, size: u64) -> Result<()> {
        let limits = self.limits;
        if size > limits.max_file_size {
            return Err(Error::FileTooLarge {
                path: path.to_owned(),
                limit: limits.max_file_size,
            });
        }
        if self.total > limits.max_total_size {
            return Err(Error::TotalTooLarge {
                limit: limits.max_total_size,
            });
        }
        if self.total > limits.ratio_min_size
            && self.total > limits.max_ratio.saturating_mul(self.compressed_len.max(1))
        {
            return Err(Error::RatioExceeded {
                limit: limits.max_ratio,
            });
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests;
