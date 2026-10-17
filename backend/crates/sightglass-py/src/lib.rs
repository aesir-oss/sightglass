//! Python bindings for `sightglass-core`, importable as `sightglass._core`.

use pyo3::create_exception;
use pyo3::exceptions::PyException;
use pyo3::prelude::*;

create_exception!(
    sightglass._core,
    ArchiveError,
    PyException,
    "An archive couldn't be read safely."
);
create_exception!(
    sightglass._core,
    UnsafeArchiveError,
    ArchiveError,
    "The archive was refused: an unsafe path, link or file type, or a size, count or ratio limit."
);
create_exception!(
    sightglass._core,
    ArchiveFormatError,
    ArchiveError,
    "The archive is damaged, or uses a feature that isn't supported."
);

#[pymodule]
mod _core {
    use std::fs::File;
    use std::path::PathBuf;

    use pyo3::prelude::*;
    use sightglass_core::{filetype, hash, unpack};

    #[pymodule_export]
    use super::{ArchiveError, ArchiveFormatError, UnsafeArchiveError};

    #[pymodule_export]
    const HEAD_SIZE: usize = filetype::HEAD_SIZE;

    /// Version of the Rust core library.
    #[pyfunction]
    fn version() -> &'static str {
        sightglass_core::version()
    }

    /// Stream a file through sha256 without loading it into memory; returns (hex digest, size).
    #[pyfunction]
    fn hash_file(py: Python<'_>, path: PathBuf) -> PyResult<(String, u64)> {
        let hashed = py.detach(move || File::open(&path).and_then(hash::sha256_reader))?;
        Ok((hashed.sha256, hashed.size))
    }

    /// The result of classifying a file.
    #[pyclass(frozen, get_all, eq, module = "sightglass._core")]
    #[derive(Clone, PartialEq)]
    struct FileType {
        category: &'static str,
        format: &'static str,
        encoding: Option<&'static str>,
    }

    impl From<filetype::FileType> for FileType {
        fn from(t: filetype::FileType) -> Self {
            Self {
                category: t.category.as_str(),
                format: t.format,
                encoding: t.encoding,
            }
        }
    }

    #[pymethods]
    impl FileType {
        fn __repr__(&self) -> String {
            let encoding = self
                .encoding
                .map_or_else(|| "None".to_owned(), |e| format!("'{e}'"));
            format!(
                "FileType(category='{}', format='{}', encoding={encoding})",
                self.category, self.format
            )
        }
    }

    /// Classify a file from its name and leading bytes (up to `HEAD_SIZE` are useful).
    #[pyfunction]
    fn classify(name: &str, head: &[u8]) -> FileType {
        filetype::classify(name, head).into()
    }

    /// Limits that bound the work an archive can cause.
    #[pyclass(frozen, get_all, eq, module = "sightglass._core")]
    #[derive(Clone, PartialEq)]
    struct Limits {
        max_total_size: u64,
        max_files: u64,
        max_file_size: u64,
        max_ratio: u64,
        ratio_min_size: u64,
    }

    #[pymethods]
    impl Limits {
        #[new]
        #[pyo3(signature = (*, max_total_size=None, max_files=None, max_file_size=None, max_ratio=None, ratio_min_size=None))]
        fn new(
            max_total_size: Option<u64>,
            max_files: Option<u64>,
            max_file_size: Option<u64>,
            max_ratio: Option<u64>,
            ratio_min_size: Option<u64>,
        ) -> Self {
            let d = unpack::Limits::default();
            Self {
                max_total_size: max_total_size.unwrap_or(d.max_total_size),
                max_files: max_files.unwrap_or(d.max_files),
                max_file_size: max_file_size.unwrap_or(d.max_file_size),
                max_ratio: max_ratio.unwrap_or(d.max_ratio),
                ratio_min_size: ratio_min_size.unwrap_or(d.ratio_min_size),
            }
        }
    }

    fn core_limits(limits: Option<&Limits>) -> unpack::Limits {
        limits.map_or_else(unpack::Limits::default, |l| unpack::Limits {
            max_total_size: l.max_total_size,
            max_files: l.max_files,
            max_file_size: l.max_file_size,
            max_ratio: l.max_ratio,
            ratio_min_size: l.ratio_min_size,
        })
    }

    /// One file or link in an archive.
    #[pyclass(frozen, get_all, module = "sightglass._core")]
    struct ArchiveEntry {
        path: String,
        kind: &'static str,
        size: u64,
        sha256: Option<String>,
        file_type: Option<FileType>,
        link_target: Option<String>,
    }

    #[pymethods]
    impl ArchiveEntry {
        fn __repr__(&self) -> String {
            format!(
                "ArchiveEntry(path={:?}, kind='{}', size={})",
                self.path, self.kind, self.size
            )
        }
    }

    fn to_python(result: unpack::Result<Vec<unpack::Entry>>) -> PyResult<Vec<ArchiveEntry>> {
        let entries = result.map_err(|e| match e {
            unpack::Error::Io(io) => PyErr::from(io),
            unpack::Error::Malformed(_) | unpack::Error::Unsupported(_) => {
                ArchiveFormatError::new_err(e.to_string())
            }
            refusal => UnsafeArchiveError::new_err(refusal.to_string()),
        })?;
        Ok(entries
            .into_iter()
            .map(|e| ArchiveEntry {
                path: e.path,
                kind: e.kind.as_str(),
                size: e.size,
                sha256: e.sha256,
                file_type: e.file_type.map(FileType::from),
                link_target: e.link_target,
            })
            .collect())
    }

    /// Hash and classify every entry of an archive without writing anything to disk.
    #[pyfunction]
    #[expect(
        clippy::needless_pass_by_value,
        reason = "PyO3 extracts arguments by value"
    )]
    #[pyo3(signature = (path, limits=None))]
    fn index_archive(
        py: Python<'_>,
        path: PathBuf,
        limits: Option<PyRef<'_, Limits>>,
    ) -> PyResult<Vec<ArchiveEntry>> {
        let limits = core_limits(limits.as_deref());
        to_python(py.detach(move || unpack::index(&path, &limits)))
    }

    /// Extract an archive into `dest`, which must not exist yet, and return its index.
    #[pyfunction]
    #[expect(
        clippy::needless_pass_by_value,
        reason = "PyO3 extracts arguments by value"
    )]
    #[pyo3(signature = (path, dest, limits=None))]
    fn extract_archive(
        py: Python<'_>,
        path: PathBuf,
        dest: PathBuf,
        limits: Option<PyRef<'_, Limits>>,
    ) -> PyResult<Vec<ArchiveEntry>> {
        let limits = core_limits(limits.as_deref());
        to_python(py.detach(move || unpack::extract(&path, &dest, &limits)))
    }
}
