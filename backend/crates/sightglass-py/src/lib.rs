//! Python bindings for `sightglass-core`, importable as `sightglass._core`.

use pyo3::prelude::*;

#[pymodule]
mod _core {
    use std::fs::File;
    use std::path::PathBuf;

    use pyo3::prelude::*;
    use sightglass_core::{filetype, hash};

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
    #[derive(PartialEq)]
    struct FileType {
        category: &'static str,
        format: &'static str,
        encoding: Option<&'static str>,
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
        let t = filetype::classify(name, head);
        FileType {
            category: t.category.as_str(),
            format: t.format,
            encoding: t.encoding,
        }
    }
}
