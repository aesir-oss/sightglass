//! Python bindings for `sightglass-core`, importable as `sightglass._core`.

use pyo3::prelude::*;

#[pymodule]
mod _core {
    use pyo3::prelude::*;

    /// Version of the Rust core library.
    #[pyfunction]
    fn version() -> &'static str {
        sightglass_core::version()
    }
}
