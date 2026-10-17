# Contributing

Thanks for helping. Read [the design](docs/design.md) first; it explains what Sightglass is and isn't.

## Project rules

These aren't style preferences. A pull request that breaks one won't be merged.

- **Never run package code.** No installs, builds, imports or sandboxed runs of analyzed packages, in any code path or
  test. Workers only read archives and text.
- **Facts, not verdicts.** A signal is an observation with evidence and a level. Never label a package malicious or
  safe, and word messages as observations ("is in the wheel but not in the git tag").
- **No vulnerability database.** Sightglass doesn't match CVEs; it links to tools that do.
- **No fabricated findings about real packages.** Fixtures, mockups and docs use invented package, account and
  repository names, and `example.net`-style reserved domains.
- **Security reports go through [SECURITY.md](SECURITY.md)**, not issues.

## Setup

Install [pixi](https://pixi.sh). It provides Python, Rust and Node; nothing else needs a global install.

```bash
pixi install
pixi run bootstrap   # pre-commit and commit-msg hooks
```

Run Python through pixi (`pixi run python ...`), and add dependencies with `pixi add`, conda-forge first. Frontend
dependencies go through pnpm inside `frontend/`, which only resolves versions at least 7 days old.

## Making a change

1. Pick or open an issue, and say you're working on it.
2. Branch from `main`: `feature/<name>`, `bugfix/<name>` or `hotfix/<name>`.
3. Write the change with tests. Unit tests go in `backend/tests/unit/` and must not touch the network, disk or a
   database. Integration tests go in `backend/tests/integration/`, are marked `@pytest.mark.integration`, and use real
   resources (`tmp_path`, Postgres, recorded HTTP with `respx`). Rust tests sit next to the code; frontend tests sit
   next to their component as `*.test.tsx`.
4. Run the fast checks while you work: `pixi run test`, `pixi run fmt`, `pixi run lint`, `pixi run check`, and their
   `-rs` and `-web` variants.
5. Run `pixi run ci` before committing. It must exit 0: pre-commit, builds, type checks, lint, and every test suite
   with at least 90% coverage.
6. Commit with [Conventional Commits](https://www.conventionalcommits.org/) (`feat(rules): ...`, `fix(api): ...`). The
   commit-msg hook checks it. Don't use `--no-verify`.
7. Open a pull request against `main` that says what changed and how you verified it, and links the issue.

## Signal rules

Rules, their versions and how to word their messages are covered in [docs/rules.md](docs/rules.md). Bump a rule's
`version` whenever its output changes, so stored analyses are recomputed.

## Benchmarks

Line diff benchmarks run with `pixi run bench-rs` (criterion, not part of `pixi run ci`); run them before and
after changing `crates/sightglass-core/src/diff.rs`.

## Fuzzing

The archive unpacker is fuzzed with cargo-fuzz, which needs nightly Rust from rustup; it's the only tool outside pixi
and never part of `pixi run ci`. Setup, tasks (`pixi run fuzz`) and what to do with a crash are in
[backend/fuzz/README.md](backend/fuzz/README.md). A crash input becomes a file in `backend/fuzz/regressions/`, which
the normal test suite replays.

## Code style

- Python: PEP 8 at 120 columns, full type hints (mypy strict), Google-style docstrings, `X | Y` and `list[X]` syntax.
  Log with structlog (`sightglass.log.get_logger`), never `print()` or the standard `logging` module. Catch specific
  exceptions, and never swallow one silently.
- Rust: rustfmt and clippy pedantic with warnings denied; no `unsafe`.
- TypeScript: eslint strict type-checked and prettier. Render file contents and package metadata as text, never as HTML.

## License

By contributing you agree that your contributions are licensed under [Apache-2.0](LICENSE).
