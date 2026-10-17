# Mockups

Static, single-file HTML mockups. Open them in a browser; they need no server. GitHub shows `.html` files as source,
so download or clone to view them.

| File | Phase | What it shows |
|---|---|---|
| [`release-diff.html`](release-diff.html) | 1 | Release diff page for `orbit-client` 2.4.1 → 2.5.0: release timeline, signals, file treemap, diffs against the previous release and the git tag, release facts |
| [`lockfile-lens.html`](lockfile-lens.html) | 2 | Pull request review page for a `pixi.lock` update with 10 changes: change queue, dependency graph, package detail, review decisions and a generated comment. Built under the working name Lockfile Lens |

## The data is invented

`kestrel-weather/stormfront-api`, `orbit-client`, `rapidcsv-x`, `zstd-shim`, `tidepool` and the other packages,
accounts and repositories are made up, and `telemetry.example.net` is a reserved example domain. Only `python`,
`openssl`, `libffi` and `zlib` are real, and the mockups claim nothing unusual about them. Keep it that way: never put
fabricated findings about real packages in a mockup.

## What is real logic

`release-diff.html` computes everything from the embedded file contents: the line diff (LCS), file pairing, the
treemap layout and every signal. Changing the version pair recomputes them. The first `<script>` is the engine and ends
at `//END-ENGINE`; it exports its functions under Node, so it can be checked with:

```bash
awk '/^<script>$/{n++} n==1' docs/mockups/release-diff.html | sed '1d' | sed '/^\/\/END-ENGINE/,$d' > /tmp/engine.js
```

```bash
node -e 'const E=require("/tmp/engine.js"); const pf=E.pairFiles("2.4.1","2.5.0"); console.log(E.computeSignals("2.4.1","2.5.0",pf))'
```

`lockfile-lens.html` uses hand-written signals and facts per package. Its review decisions are kept in the browser's
local storage.

## Published copies

Private claude.ai artifacts of the same pages, visible only to the owner until shared:

- Release diff: https://claude.ai/artifact/HcWQYYUKVezeZr1n9BTytP
- Pull request review: https://claude.ai/artifact/JK2ZXKYVwCtDKnSupvdVcd

The copies in this directory are the source of truth. The artifact of the release diff page still shows a generic
"Release diff" label instead of Sightglass.
