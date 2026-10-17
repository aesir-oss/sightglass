# Fuzzing the unpacker

Coverage-guided fuzzing of `sightglass-core::unpack` with [cargo-fuzz](https://github.com/rust-fuzz/cargo-fuzz)
(libFuzzer and AddressSanitizer). Each target indexes its input as one container format and checks the invariants
every accepted archive must satisfy (`src/lib.rs`): safe relative paths, no duplicates, limits respected, consistent
file and link entries. Refusals and format errors are expected; a panic or a broken invariant is a finding.

| Target | Format |
|---|---|
| `unpack_zip` | zip (wheels, zip sdists, GitHub zipballs) |
| `unpack_tar` | uncompressed tar |
| `unpack_tar_gz` | gzip-compressed tar (sdists, GitHub tarballs) |

## Setup

cargo-fuzz needs nightly Rust, which conda-forge doesn't provide, so this is the one part of the project outside pixi.
It's never part of `pixi run ci`.

```bash
rustup toolchain install nightly --profile minimal
cargo install cargo-fuzz --version 0.13.2 --locked
```

## Running

```bash
pixi run fuzz                # each target for 60 seconds
pixi run fuzz-zip 600        # one target, for 10 minutes
pixi run fuzz-seeds          # regenerate the generated seeds after changing src/bin/make_seeds.rs
```

`run.sh` puts nightly's `rustc` ahead of pixi's on `PATH`. New interesting inputs go to `work/<target>/`, which is
ignored; `corpus/<target>/` is the committed seed set and is only read. The [Fuzz workflow](../../.github/workflows/fuzz.yml)
runs every target for 10 minutes each Monday, and on demand.

## When it finds a crash

1. libFuzzer writes the input to `artifacts/<target>/crash-*` (CI uploads it as a workflow artifact).
2. Reproduce it: `bash run.sh <target>` with the file as the corpus, or index it with `index_reader` in a test.
3. Fix the bug, then copy the input to `regressions/<target>/` with a descriptive name.
   `crates/sightglass-core/tests/fuzz_corpus.rs` replays every seed and regression on stable Rust in `pixi run ci`,
   so it can't come back.

## Seed corpus

`gen-*` files come from `src/bin/make_seeds.rs`: valid archives shaped like wheels and sdists (invented packages), and
one archive per refusal rule (traversal, absolute paths, escaping links, device files, encryption, sparse files,
duplicates, a zip bomb). Regenerating them is byte-for-byte reproducible.

`real-*` files are published artifacts of [pypa/sampleproject](https://github.com/pypa/sampleproject) 4.0.0 (MIT
license):

| File | Source | sha256 |
|---|---|---|
| `unpack_zip/real-sampleproject-4.0.0-py3-none-any.whl` | PyPI | `c23e447ea90d796d1e645c35c4b2de125040add12a845825546f91c93f391b6b` |
| `unpack_tar_gz/real-sampleproject-4.0.0.tar.gz` | PyPI | `0ace7980f82c5815ede4cd7bf9f6693684cec2ae47b9b7ade9add533b8627c6b` |
| `unpack_tar_gz/real-sampleproject-621e497-github.tar.gz` | GitHub archive of commit `621e497`, the one the 4.0.0 attestation names | `fd8597e4d351a9fd42007f48339dc93ee6469d8555fd0ff24906c69905357c01` |
| `unpack_tar/real-sampleproject-621e497-github.tar` | The same archive, decompressed | `2ff36ca2baf0acabb62591454ee68b46cb27f7bc4de64d4e1202e5c8a2360875` |

The PyPI files were checked against the digests PyPI publishes.
