# CLAUDE.md

Project guidance for aesir-oss/sightglass. The global CLAUDE.md (toolchain, harness, git workflow) applies; this file
covers what is specific here.

@.claude/memory/MEMORY.md

## Status

Scaffolding. The root pixi workspace, the Python backend in `backend/` and the Rust crates in `backend/crates/` exist;
the frontend and CI come next (Foundation milestone). After a Rust change, `pixi run develop` rebuilds
`sightglass._core`; the Python test tasks run it first. Python tasks run with `cwd = "backend"`, and pre-commit points ruff and mypy at
`backend/pyproject.toml`.

## Layout

| Path | What it is |
|---|---|
| `docs/design.md` | The design: goals, signals, architecture, data model, phases, risks, open questions |
| `docs/background.md` | Why this project was chosen over the other ideas |
| `docs/naming.md` | Why the name, and every name that was considered |
| `docs/mockups/` | Static HTML mockups of the phase 1 and phase 2 pages, with invented data |

## Workflow

- The maintainer works from a fork under `millsks` and opens pull requests to `aesir-oss/sightglass`.
- Branch names and commits follow the global CLAUDE.md (§5).

## Off-limits and traps

- Mockup data must stay invented. Never put fabricated findings about a real package, person or organization in a
  mockup, a test fixture or the docs.
- `.claude/memory/` is committed and public. Nothing private or about the maintainer's employer goes in it.
