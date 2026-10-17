# Routine release sample

For [#55](https://github.com/aesir-oss/sightglass/issues/55), run 2026-10-17. Phase 1 is done when the rule set
produces no high signals on 200 routine releases of popular packages that we've checked by hand. This page says how
the samples were chosen and checked and what the rules were changed to; the generated results are in
[routine-sample-results.md](routine-sample-results.md) (tuning) and
[routine-holdout-results.md](routine-holdout-results.md) (held out), each with a JSON file of every signal.

## Short answer

| Sample | Packages | High signals | False alarms among them |
|---|---|---|---|
| Tuning, before changes (ranks 1-200) | 200 | 296 in 112 packages | almost all |
| Tuning, after changes | 200 | 7 in 5 packages | 0 |
| Held out, rules frozen (ranks 201-402) | 200 | 18 in 9 packages | 15 in 7 packages (3.5% of packages) |
| Validation, after the held-out fixes (ranks 403-604) | 200 | 21 in 12 packages | 1 in 1 package (0.5%) |

The tuning sample reaches the target. The held-out sample, run once with no changes afterwards, gave the first honest
estimate: about one routine release in 30 got a high signal it shouldn't. Its four causes were fixed in
[#146](https://github.com/aesir-oss/sightglass/issues/146), [#147](https://github.com/aesir-oss/sightglass/issues/147),
[#148](https://github.com/aesir-oss/sightglass/issues/148) and [#149](https://github.com/aesir-oss/sightglass/issues/149),
and a third, fresh sample measured the result: one false alarm in 200 packages.

High signals that are accurate still appear on about one routine release in 17 (12 of 200 in the validation sample).
They are real changes in how a package is built or published, listed below, and are what the page is for; they are
not counted as false alarms.

## Method

- **Packages:** the top 200 of the committed download ranking (`rules/data/top_packages.json`, ClickHouse, 30 days to
  2026-10-17), in rank order.
- **Release:** for each package, the newest stable release that is at least 30 days old and not yanked. Thirty days is
  long past the point where a compromised release of a top package is noticed, reported and yanked.
- **Previous release:** the highest stable, unyanked version below it, also published before the cutoff. Ordering by
  version rather than by date keeps the pair on one release line, so a backport such as 4.2.25 published after 5.2.6
  isn't compared with 5.2.6.
- **Analysis:** the full pipeline, exactly as the service runs it: the sdist pair and the default wheel pair, the
  source check against the GitHub tag, attestations and every rule.
- The list is [routine-sample.json](routine-sample.json); `pixi run sample select --today 2026-10-17` reproduces it
  while the index hasn't changed. `pixi run sample run` analyzes it and rewrites the results.
- **Validation sample:** the same method from rank 403 ([routine-validation.json](routine-validation.json)), selected
  and run once after the held-out fixes merged.
- **Held-out sample:** the same method from download rank 201 ([routine-holdout.json](routine-holdout.json),
  `pixi run sample select --name routine-holdout --first-rank 201 --today 2026-10-17`). It was selected before the
  tuning sample's final results were seen and run once, after the last rule change.

## How the releases were checked

Every release in the sample was checked for the things that would make it not routine:

1. **Not yanked** and still on PyPI on the sampling date (`select` skips yanked releases).
2. **At least 30 days old** at sampling, with no later yank.
3. **Every high signal reviewed by hand** against the release's diff and source repository. A false alarm on the
   tuning sample led to a general rule change, each covered by a unit test; an accurate one is listed below with what
   it is. On the held-out sample nothing was changed; each signal is classified instead.
4. **Every check signal read** the same way, to confirm it describes the change accurately. Check signals are allowed
   on routine releases; they're listed in the results for the record.

What wasn't done: a line-by-line audit of all 200 diffs. The sample is a test of the rules' false-positive rate on
ordinary updates, not a security review of these packages.

## Rule changes

The first run gave 296 high signals. Reading them showed bugs and levels set without the "breaks a pattern" test
that [rules.md](../rules.md#levels) asks for. Every change is a general rule about how packages are built; none names
a package.

| Change | High signals it explained |
|---|---|
| A release workflow can run on a later commit than the one it builds (packaging 26.3 was attested from a commit already at 26.4.dev0): the version tag is tried before the attested commit | `source.*` for packaging, cryptography |
| A release built in a separate repository that pulls the code in as a git submodule (numpy, scipy, scikit-learn `-release` repos): when the attested repository holds less than half the package, the listed one is used | thousands of `source.not_in_tag` files |
| Source files a project already shipped unchanged, or that the previous release also didn't match in its own source, are a kept pattern: note | most remaining `source.*`, including playwright's driver and generated `version.py` files |
| Sdist files in top-level `tests/`, `docs/`, `examples/`, `scripts/`, `tools/`, `benchmarks/` and dot directories aren't installed: note | 54 `behavior.*` signals in test files |
| Files that aren't code (documentation, licenses, lock files, declarative config, type stubs): note | README, `Cargo.lock`, `uv.lock`, `pyproject.toml` rewrites |
| Build output named by the build: files in a git submodule, files generated from `X.in` or `X.cmake`, Cython `.c`/`.cpp`/`.cxx` next to a `.pyx`, versioneer's generated `_version.py`, and Python that only assigns values | aiohttp, lxml, numpy, rapidfuzz, duckdb, pandas, s3fs |
| Python that runs the same code as the tag apart from comments, formatting and the values of version names (`__version__`, versioneer's archive keywords): note. Any other changed value, a URL for example, stays high | deprecation (tag left at 2.0.7), wheel scripts with a rewritten `#!` line |
| A package directory installed under another name (`package_dir={"psycopg2": "lib"}`) is followed; installed scripts and headers are found by unique file name | psycopg2, jmespath, greenlet |
| A network, subprocess, exec or decoding call is high only when the previous release made no such call anywhere; otherwise check | pyjwt, setuptools, dnspython |
| `behavior.network` lists calls that connect, not every name in a networking module (`aiohttp.ClientTimeout`, `socket.fileno`, `ssl.create_default_context` and `paramiko.Message` don't) | aiobotocore, pexpect, paramiko |
| New module-level code in `__init__.py` is high only when it makes one of those calls; `re.compile` or `dataclass` is a note | 39 `behavior.import_time_code` signals |
| A changed `setup.py` or in-tree backend is check, or high when the added lines make one of those calls | 18 `hooks.setup_py` signals |

The runs also found three bugs, fixed in their own pull requests or here: workers deadlocking on blob rows
([#143](https://github.com/aesir-oss/sightglass/pull/143), [#144](https://github.com/aesir-oss/sightglass/pull/144)),
and the encoded-payload rule crashing on string literals with lone surrogates.

## Tuning sample: the 7 remaining high signals

Each was read against its diff. All are accurate, and each is a change from what the project did before.

| Package | Signal | What it is |
|---|---|---|
| scikit-learn 1.9.0 → 1.9.1 | `provenance.publisher_changed` (sdist, wheel) | 1.9.1 is published from a new `scikit-learn-release` repository |
| annotated-doc 0.0.4 → 0.0.5 | `provenance.attestation_dropped` (sdist, wheel) | 0.0.5 has no attestation; 0.0.4 did |
| chardet 7.5.1 → 7.6.0 | `behavior.subprocess` | a new build hook, `hatch_build_cython.py`, runs `subprocess.run` |
| playwright 1.62.0 → 1.63.0 | `source.not_in_tag` | nine new JavaScript files in the bundled driver, which comes from npm at build time |
| psutil 7.2.1 → 7.2.2 | `source.differs_from_tag` | the wheel's `__all__` lists `"STATUS_LOCKED"` twice; tag `v7.2.2` doesn't. The wheel wasn't built from the tagged code |

## Held-out sample: the 18 high signals

Accurate (3 signals, 2 packages):

| Package | Signal | What it is |
|---|---|---|
| ddtrace 4.14.1 → 4.15.0 | `hooks.setup_py` | `setup.py` adds `subprocess.run` calls (cargo, patchelf, objcopy) |
| pip-api 0.0.34 → 0.0.35 | `behavior.dynamic_exec` (sdist, wheel) | newly vendored `packaging` calls `compile(expression, "", "eval")` to check license expressions |

False alarms (15 signals, 7 packages), by cause:

| Cause | Packages | Follow-up |
|---|---|---|
| The tag search takes the repository's `3.3.1` tag in a monorepo that tags this package `pool-3.3.1` | psycopg-pool (2) | Prefer a tag with the package's name when one exists |
| Python files with a byte-order mark aren't parsed, so "same code apart from line endings" isn't recognized | msal (3) | Decode with `utf-8-sig` before parsing |
| Sdist files outside the package in directories the list doesn't name (`openapi/`, a root `Makefile`, `include/cargo/` vendored crates) | pygithub (1), nodeenv (1), orjson (2) | Decide "installed" from the release's wheel instead of a list of directory names |
| A build that renames the package (`Crypto` to `Cryptodome`) | pycryptodomex (2) | Accept as reviewed, or compare modulo the rename |
| Generated bindings in a new versioned directory (`devtools/v153`) that the previous release had under another name | selenium (4) | Accept as reviewed |

Three pairs couldn't be analyzed: reportlab 5.0.1 (an sdist entry that already exists when unpacked), delta-spark
4.4.0 (a file name too long for the file system) and events 0.5 (no artifact kind shared with 0.4). The first two
are unpacking bugs to fix; the last is correct.

## Validation sample: the 21 high signals

Run once with the rules as of [#153](https://github.com/aesir-oss/sightglass/pull/153); results in
[routine-validation-results.md](routine-validation-results.md). Nothing was changed after it.

False alarm (1 signal, 1 package):

| Package | Signal | Cause |
|---|---|---|
| dacite 1.9.1 → 1.9.2 | `source.differs_from_tag` | Tag `v1.9.2` still says `version="1.9.1"` in `setup.py`. Version values are recognized in assignments, not yet as the `version=` argument of `setup()` |

Accurate (20 signals, 11 packages):

| Package | Signal | What it is |
|---|---|---|
| confection 1.3.2 → 1.3.3 | `provenance.publisher_changed` (sdist, wheel) | now published from `explosion/wheelmonger` instead of `explosion/confection` |
| google-cloud-aiplatform 2.1.0 → 2.1.3 | `hooks.pth_import`, `source.not_in_sdist`, `source.not_in_tag` | a new `-nspkg.pth` file that runs code at every Python startup, generated by the build |
| sympy 1.13.3 → 1.14.0 | `hooks.setup_py`, `source.differs_from_tag` (sdist, wheel) | `setup.py` now runs `exec` on `sympy/release.py`; nine files differ from tag `1.14.0` in code (type annotations, assumptions), so the release wasn't built from the tagged commit |
| sentencepiece 0.2.1 → 0.2.2 | `hooks.setup_py`, `source.not_in_tag`, `source.differs_from_tag` | `setup.py` runs `build_bundled.sh` with `subprocess`, and the sdist carries 1,764 files of abseil-cpp that aren't in the repository |
| pybase64 1.4.3 → 1.5.0 | `hooks.setup_py` | `setup.py` adds subprocess calls |
| litellm 1.100.1 → 1.101.0 | `source.not_in_tag` (sdist, wheel) | 147 JavaScript files of the built web UI, with new content-hashed names, aren't in the repository |
| parsedatetime 2.5 → 2.6 | `source.differs_from_tag` (sdist, wheel) | the published `__init__.py` has a different `__copyright__` year from tag `v2.6` |
| sqlparse 0.5.5 → 0.6.0 | `source.differs_from_tag` | the sdist's `Makefile` differs from tag `0.6.0` |
| papermill 2.6.0 → 2.7.0 | `behavior.subprocess` | an installed test file adds `subprocess.Popen`; the package made no subprocess calls before |
| pyogrio 0.12.1 → 0.13.0 | `behavior.network` (sdist, wheel) | an installed test file adds `urllib.request.urlopen`; the package made no network calls before |
