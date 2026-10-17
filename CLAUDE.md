# CLAUDE.md

Project guidance for aesir-oss/sightglass. The global CLAUDE.md (toolchain, harness, git workflow) applies; this file
covers what is specific here.

@.claude/memory/MEMORY.md

## Status

Phase 1 analysis engine. The backend analyzes a PyPI release pair end to end: `pixi run analyze pypi <pkg> <from> <to>`
runs the pipeline locally, and `pixi run worker` processes queued jobs. The API and pages are next. The root pixi
workspace, the Rust crates in `backend/crates/`, the React frontend in `frontend/`, and CI exist.

- Python tasks run with `cwd = "backend"`; pre-commit points ruff and mypy at `backend/pyproject.toml`.
- After a Rust change, `pixi run develop` rebuilds `sightglass._core`; the Python test tasks run it first.
- Python 3.14 only, an exception to the global 3.12–3.14 matrix: Sightglass is a hosted service and its container image
  fixes the runtime. mypy targets 3.14 and the extension is `abi3-py314`. A CLI published to PyPI (#76) would bring
  back a matrix for that package only.
- GitHub Actions are pinned to commit SHAs.
- Every change to `sightglass/db/models.py` needs an Alembic revision in `sightglass/db/migrations/versions/`
  (`pixi run db-revision -m "..."` against a scratch database, then review it). The integration tests fail if the
  migrations and models drift. They start their own Postgres from conda-forge over TCP, since macOS temp paths are
  too long for its Unix socket.
- The job queue's schema is procrastinate's own, vendored at 3.10.0 in `sightglass/db/migrations/sql/` and applied by
  revision 0003. Upgrading procrastinate needs a new revision that runs its `procrastinate/sql/migrations/` files for
  the versions in between. procrastinate is a PyPI dependency until it is on conda-forge.
- `pixi run worker` processes analysis jobs (`SIGHTGLASS_DATABASE_URL`; downloads cached in `SIGHTGLASS_CACHE_DIR`).
- After changing an API route or model, run `pixi run gen-api-types` and commit `frontend/src/api/`. CI's
  `check-api-types` fails when the committed schema or types are stale.
- Frontend tasks run with `cwd = "frontend"` through pnpm, with Node from pixi.
- In production FastAPI serves `frontend/dist` (or `SIGHTGLASS_FRONTEND_DIR`), with `index.html` for every non-API
  path. `pixi run dev` runs the API, a worker and Vite, which proxies `/api` to port 8000.

## Layout

| Path | What it is |
|---|---|
| `pixi.toml` | The one workspace: Python, Rust and Node from conda-forge, and every task |
| `backend/src/sightglass/` | Python backend: `api/`, `worker/`, `rules/`, `ecosystems/`, `lockfiles/` |
| `backend/crates/sightglass-core/` | Pure Rust: unpacking, hashing, file typing, line diffs |
| `backend/crates/sightglass-py/` | PyO3 bindings, built by maturin as `sightglass._core` |
| `backend/tests/` | `unit/` and `integration/` |
| `frontend/` | React, Vite and TypeScript, managed with pnpm |
| `docs/design.md` | The design: goals, signals, architecture, data model, phases, risks, open questions |
| `docs/rules.md` | Writing signal rules: ids, versions, unknown inputs, levels and message wording |
| `docs/background.md` | Why this project was chosen over the other ideas |
| `docs/naming.md` | Why the name, and every name that was considered |
| `docs/mockups/` | Static HTML mockups of the phase 1 and phase 2 pages, with invented data |

## Workflow

- The maintainer works from a fork under `millsks` and opens pull requests to `aesir-oss/sightglass`.
- Branch names and commits follow the global CLAUDE.md (§5).

## Off-limits and traps

- `frontend/pnpm-workspace.yaml` sets `minimumReleaseAge` to 7 days. `pnpm add` picks the newest version that old, and an
  explicit range whose floor is newer fails to resolve. Don't add packages to `minimumReleaseAgeExclude` to get around it.
- Dependency install scripts are blocked (`onlyBuiltDependencies: []`). Allow one only with a reason in the PR.
- No AI or LLM features. The maintainer decided against them (2026-10-16).
- Mockup data must stay invented. Never put fabricated findings about a real package, person or organization in a
  mockup, a test fixture or the docs.
- `.claude/memory/` is committed and public. Nothing private or about the maintainer's employer goes in it.
