# Sightglass

[![CI](https://github.com/aesir-oss/sightglass/actions/workflows/ci.yml/badge.svg)](https://github.com/aesir-oss/sightglass/actions/workflows/ci.yml)

See what a package release actually ships.

Sightglass compares the files people install from a package index with the previous release and with the project's
git tag, and shows the differences that matter for supply chain security: a dropped attestation, files that aren't in
the source, new code that runs on import. Later, a GitHub App brings the same view into pull requests that update a
lockfile.

Status: early development. The Python backend, its Rust core and the React frontend are scaffolded; nothing runs yet.

- [Design](docs/design.md)
- [Background](docs/background.md): why this project, and the ideas it was chosen over
- [Naming](docs/naming.md)
- [Mockups](docs/mockups/README.md) (open the HTML files in a browser):
  - [Release diff page](docs/mockups/release-diff.html), phase 1
  - [Pull request review page](docs/mockups/lockfile-lens.html), phase 2

Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md). Report vulnerabilities privately as described in
[SECURITY.md](SECURITY.md).

## Installation

Install [pixi](https://pixi.sh), then:

```bash
pixi install
pixi run bootstrap   # installs the pre-commit hooks
```

## Quick start

Analyze one release pair of a PyPI package, without the web service:

```bash
pixi run analyze pypi <package> <from-version> <to-version>                # signals as JSON log events on stderr
pixi run analyze pypi <package> <from-version> <to-version> --format json  # one JSON document on stdout
```

It downloads and verifies the artifacts, finds the source on GitHub, and runs the rules; nothing from the package is
executed. Results go to `SIGHTGLASS_DATABASE_URL` if set, or to a local Postgres under `~/.cache/sightglass`
(`SIGHTGLASS_CACHE_DIR`), which also caches downloads between runs.

## Development

| Command | What it runs |
|---|---|
| `pixi run test` | Backend unit tests |
| `pixi run test-integration` | Backend integration tests |
| `pixi run fmt` / `lint` / `check` | ruff format, ruff check, mypy (strict) |
| `pixi run cov` | Full backend test suite with the 90% coverage gate |
| `pixi run db-upgrade` / `db-revision -m "..."` | Apply migrations, or autogenerate a new one from the models (needs `SIGHTGLASS_DATABASE_URL`) |
| `pixi run worker` | Process queued analysis jobs (needs `SIGHTGLASS_DATABASE_URL`) |
| `pixi run refresh-top-packages` | Refresh the top-packages list for the lookalike-name rule; review and commit the diff |
| `pixi run develop` | Rebuild the Rust extension in place (the Python test tasks run it first) |
| `pixi run fmt-rs` / `lint-rs` / `test-rs` / `cov-rs` | rustfmt, clippy, cargo test, cargo llvm-cov (90% gate) |
| `pixi run dev` | API (port 8000), a worker and the Vite dev server (proxying `/api`) together; uses `SIGHTGLASS_DATABASE_URL` or a local Postgres |
| `pixi run dev-web` | Vite dev server for the frontend |
| `pixi run fmt-web` / `lint-web` / `check-web` / `test-web` / `cov-web` | prettier, eslint, tsc, vitest, vitest coverage (90% gate) |
| `pixi run gen-api-types` | Export the FastAPI schema and regenerate `frontend/src/api/schema.d.ts`; commit both |
| `pixi run build-web` | Production frontend bundle in `frontend/dist/` |
| `pixi run ci` | Everything above plus pre-commit and the build; must pass before a commit |

Layout: `backend/` holds the Python package (`backend/src/sightglass/`), its tests, and the Rust crates
(`backend/crates/`, exposed to Python as `sightglass._core`); `frontend/` holds the React app
(Vite, TypeScript, pnpm; Node comes from pixi).

## License

[Apache-2.0](LICENSE).
