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
    use std::time::Duration;

    use pyo3::prelude::*;
    use sightglass_core::{diff, filetype, hash, unpack};

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

    /// Limits that bound the work a line diff can cause.
    #[pyclass(frozen, get_all, eq, module = "sightglass._core")]
    #[derive(Clone, PartialEq)]
    struct DiffLimits {
        max_size: u64,
        max_lines: usize,
        timeout: f64,
        context: usize,
    }

    #[pymethods]
    impl DiffLimits {
        #[new]
        #[pyo3(signature = (*, max_size=None, max_lines=None, timeout=None, context=None))]
        fn new(
            max_size: Option<u64>,
            max_lines: Option<usize>,
            timeout: Option<f64>,
            context: Option<usize>,
        ) -> PyResult<Self> {
            let d = diff::Limits::default();
            let timeout = timeout.unwrap_or(d.timeout.as_secs_f64());
            if !(0.0..=86_400.0).contains(&timeout) {
                return Err(pyo3::exceptions::PyValueError::new_err(
                    "timeout must be between 0 and 86400 seconds",
                ));
            }
            Ok(Self {
                max_size: max_size.unwrap_or(d.max_size),
                max_lines: max_lines.unwrap_or(d.max_lines),
                timeout,
                context: context.unwrap_or(d.context),
            })
        }
    }

    /// One line of a hunk.
    #[pyclass(frozen, get_all, module = "sightglass._core")]
    struct DiffLine {
        kind: &'static str,
        old_line: Option<usize>,
        new_line: Option<usize>,
        text: String,
        missing_newline: bool,
    }

    #[pymethods]
    impl DiffLine {
        fn __repr__(&self) -> String {
            let number = |n: Option<usize>| n.map_or_else(|| "None".to_owned(), |n| n.to_string());
            format!(
                "DiffLine(kind='{}', old_line={}, new_line={}, text={:?})",
                self.kind,
                number(self.old_line),
                number(self.new_line),
                self.text
            )
        }
    }

    /// A unified diff hunk.
    #[pyclass(frozen, get_all, module = "sightglass._core")]
    struct Hunk {
        old_start: usize,
        old_len: usize,
        new_start: usize,
        new_len: usize,
        lines: Vec<Py<DiffLine>>,
    }

    #[pymethods]
    impl Hunk {
        fn __repr__(&self) -> String {
            format!(
                "Hunk(-{},{} +{},{})",
                self.old_start, self.old_len, self.new_start, self.new_len
            )
        }
    }

    /// The line diff of two inputs, or a result saying they were too large to diff.
    #[pyclass(frozen, get_all, module = "sightglass._core")]
    struct FileDiff {
        too_large: bool,
        hunks: Vec<Py<Hunk>>,
        added: usize,
        removed: usize,
        approximate: bool,
    }

    #[pymethods]
    impl FileDiff {
        /// Every added line as `(line number in the new file, text)`.
        fn added_lines(&self) -> Vec<(usize, String)> {
            self.hunks
                .iter()
                .flat_map(|h| h.get().lines.iter().map(Py::get))
                .filter(|l| l.kind == "added")
                .filter_map(|l| Some((l.new_line?, l.text.clone())))
                .collect()
        }

        fn __repr__(&self) -> String {
            format!(
                "FileDiff(too_large={}, hunks={}, added={}, removed={})",
                if self.too_large { "True" } else { "False" },
                self.hunks.len(),
                self.added,
                self.removed
            )
        }
    }

    fn file_diff(py: Python<'_>, result: diff::FileDiff) -> PyResult<FileDiff> {
        let diff::FileDiff::Lines(d) = result else {
            return Ok(FileDiff {
                too_large: true,
                hunks: Vec::new(),
                added: 0,
                removed: 0,
                approximate: false,
            });
        };
        let mut hunks = Vec::with_capacity(d.hunks.len());
        for h in d.hunks {
            let lines = h
                .lines
                .into_iter()
                .map(|l| {
                    Py::new(
                        py,
                        DiffLine {
                            kind: l.kind.as_str(),
                            old_line: l.old_line,
                            new_line: l.new_line,
                            text: l.text,
                            missing_newline: l.missing_newline,
                        },
                    )
                })
                .collect::<PyResult<_>>()?;
            hunks.push(Py::new(
                py,
                Hunk {
                    old_start: h.old_start,
                    old_len: h.old_len,
                    new_start: h.new_start,
                    new_len: h.new_len,
                    lines,
                },
            )?);
        }
        Ok(FileDiff {
            too_large: false,
            hunks,
            added: d.added,
            removed: d.removed,
            approximate: d.approximate,
        })
    }

    /// Diff two versions of a file line by line.
    #[pyfunction]
    #[expect(
        clippy::needless_pass_by_value,
        reason = "PyO3 extracts arguments by value"
    )]
    #[pyo3(signature = (old, new, limits=None))]
    fn diff_lines(
        py: Python<'_>,
        old: &[u8],
        new: &[u8],
        limits: Option<PyRef<'_, DiffLimits>>,
    ) -> PyResult<FileDiff> {
        let limits = limits
            .as_deref()
            .map_or_else(diff::Limits::default, |l| diff::Limits {
                max_size: l.max_size,
                max_lines: l.max_lines,
                timeout: Duration::from_secs_f64(l.timeout),
                context: l.context,
            });
        let result = py.detach(|| diff::diff(old, new, &limits));
        file_diff(py, result)
    }
}
