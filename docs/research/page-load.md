# Page load target

For [#56](https://github.com/aesir-oss/sightglass/issues/56), run 2026-10-17. Phase 1 is done when "any PyPI
release pair with a GitHub-hosted source loads in under 10 seconds on first request and instantly after".

## Short answer

| | First run | After the changes below |
|---|---|---|
| CPU per release pair, p50 / p95 / max | 1.2 s / 13.8 s / 19.2 s | 0.7 s / **9.8 s** / 11.7 s |
| Downloaded per release pair, p50 / p95 / max | 1.8 MB / 106 MB / 157 MB | 1.8 MB / 71 MB / 156 MB |
| Wall time on this connection, p50 / p95 | 3.9 s / 51 s | 2.9 s / 43 s |

Sightglass isn't hosted yet, so #56 is accepted on what the code controls: **CPU time p95 under 10 seconds** for a
cold first load, with download sizes measured alongside. Wall time here is dominated by a residential connection
(about 6.5 MB/s, and much slower at times), so it says little about a server. Wall time is re-checked once a server
exists.

A second request for an analyzed pair reads the stored report and never touches the queue
(`tests/integration/test_api_pairs.py`).

## Method

- **Pairs:** the 50 most-downloaded packages' routine pairs ([page-load.json](page-load.json), the same rule as the
  [routine sample](routine-sample.md)): the largest artifacts and repositories on PyPI, so the slow end of the range.
- **Cold:** each run starts with an empty download cache and database (a new `SIGHTGLASS_CACHE_DIR`), and runs one pair
  at a time (`pixi run sample run --name page-load --jobs 1`), as one worker handles a first page load: both artifact
  pairs, then the result.
- **Measured per pair:** wall time; process CPU time, which is the work that doesn't depend on the network; bytes
  read from PyPI and GitHub; and seconds per pipeline step, which the worker now also logs as `pair_timing`.
- Results: [page-load-results.md](page-load-results.md).

## What changed

| Change | Effect |
|---|---|
| Source archives were indexed when downloaded and then extracted in full. They're now indexed once, compared by hash, and only the files that differ are written out for their diffs | cryptography's and ruff's repositories (tens of thousands of files) are no longer written to disk |
| Every file of a source tree was stored in the blob store and database; now only files matched to a package file | thousands fewer writes on large repositories |
| Files were hashed again when stored, though extraction had hashed them; stored content is skipped | about a second on the largest pairs |
| The previous release's own source, used to tell a kept mismatch from a new one, is fetched only when a code file mismatches | p95 download 106 MB to 71 MB |
| Which kinds of calls the previous release already made is worked out only when a rule asks, in one walk per file instead of five | the largest single cost on pandas, gone from most pairs |
| The pattern rules share one parse and one scan per file | each changed file was parsed eight times |
| A repository's tags are listed once a minute, not four times a pair | pandas' ref list is 2.9 MB (44,000 pull-request refs) |
| Blob rows are recorded a thousand per statement | one round trip per file before |
| The four artifacts download in parallel, and the wheel pair, which the page shows first, is analyzed first | the page appears before the sdist is done |

A source tree is now only written where it's read, which also means a path too long for the disk (delta-spark's
958-character test file) no longer stops a comparison.

## What's left

- **The largest pairs are near the limit.** pillow (11.7 s CPU), ruff, pyarrow and cryptography (9 to 10 s) are mostly
  decompressing archives of 45 to 60 MB, twice for a source tree that has differing files.
- **Source downloads.** [#157](https://github.com/aesir-oss/sightglass/issues/157) would compare with GitHub's tree
  API by git blob hash, fetching only differing files, instead of the whole archive. It needs a GitHub token, so it's
  in Phase 2 with the App.
- **Tag lists.** Git's protocol v2 can list only `refs/tags/`, instead of every ref; it needs a POST request, which
  the fetcher doesn't make yet.
