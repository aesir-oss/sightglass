# Where pattern rules come from

Spike and decision for [#11](https://github.com/aesir-oss/sightglass/issues/11), 2026-10-17. Answers the design's
open question 2: reuse GuardDog's rules, write our own, or both?

## Decision

Both, with different jobs:

1. **Sightglass's own rules** produce the high-level behavior signals: new import-time code (#27); network,
   subprocess, `exec` and encoded payloads in added code (#28); new install-time hooks (#29). They parse Python with
   `ast`, so they can tell a call from a string, which these signals need.
2. **GuardDog's YARA rules** add breadth. They are vendored at a pinned GuardDog release under
   `backend/rules/guarddog/`, with GuardDog's `LICENSE` and `NOTICE`, and run in `sightglass-core` with the
   [YARA-X](https://github.com/VirusTotal/yara-x) crate over added lines only. The vendored tag is part of the
   rule-set version, so updating it recomputes analyses.
3. **Levels.** GuardDog `threat-*` rules at high or medium severity become **check**. Its `capability-*` rules become
   **note**, or are hidden. A GuardDog match never produces **high**.
4. **Wording.** Every match is reported as an observation, with the added lines as evidence and the GuardDog rule
   named. For example: "Added lines in `logging.py` run `pip install` (GuardDog rule `threat.process.download-exec`)."

Adding the `yara-x` crate is a new runtime dependency, approved when #28 is implemented.

## What GuardDog provides

- [GuardDog](https://github.com/DataDog/guarddog), v3.2.0 (2026-08-12), Apache-2.0, with a `NOTICE` file that
  redistributions must keep. Sightglass is also Apache-2.0, so no separate terms are needed.
- Since v3, its source-code rules are 54 YARA files covering Python, JavaScript, Go and Ruby. Each has metadata:
  `severity` (low, medium, high), `specificity`, `sophistication`, `max_hits` and a GuardDog-specific `path_include`
  file glob.
- Rule names split into `capability-*` (what code can do: read files, open sockets, spawn processes) and `threat-*`
  (combinations that look like attacks: download and execute, exfiltration, obfuscated `exec`).
- Its PyPI metadata checks (typosquatting, deceptive author, compromised or unclaimed email domains, repository
  mismatch, bundled binaries) are Python code, not rules. They overlap Sightglass's own name, binary and source
  signals, and are a source of ideas rather than something to vendor.
- No YARA engine is on conda-forge. YARA-X is a Rust crate (BSD-3-Clause), so it fits in `sightglass-core` without
  one.

## Measurement

**Sample:** the top 300 packages by downloads, taking each package's two most recent stable releases that both ship a
pure-Python wheel. That gave 248 release pairs (52 packages had no such pair); routine releases, assumed benign.
**Method:**
- Wheels were read as zip archives in memory, never extracted or imported.
- For each `.py`, `.pyi` and `.pth` file, the added lines were the lines inserted or replaced since the previous
  release, or the whole file for a new one.
- Each GuardDog rule was compiled on its own with YARA-X and scanned (a) the added lines and (b) the whole file in the
  new release.
- 51 of 54 rules compiled as they are. The other 3 `include` shared `.meta` files, which the spike didn't fetch.

Scale: 4,814 changed Python files, 188,171 added lines.

| Scanned | Any rule fires | A high-severity rule fires |
|---|---|---|
| Whole files of the new release | 188 of 248 packages (76%) | 34 (14%) |
| Added lines only | 45 of 248 pairs (18%) | 3 (1.2%) |

Rules that fired most, with the release pairs where they fired on added lines and the packages where they fired on
whole files:

| Rule | Severity | Pairs (added lines) | Packages (whole files) |
|---|---|---|---|
| `capability-filesystem-read` | low | 31 | 151 |
| `capability-network-outbound` | low | 19 | 103 |
| `capability-process-spawn` | low | 14 | 107 |
| `capability-network-download` | low | 6 | 46 |
| `capability-filesystem-delete` | low | 4 | 74 |
| `threat-filesystem-read` | high | 3 | 20 |
| `capability-filesystem-write-executable` | medium | 2 | 45 |
| `threat-network-exfiltration` | high | 1 | 8 |
| `threat-process-download-exec` | high | 1 | 7 |
| `capability-process-schedule` | medium | 1 | 25 |

The five high-severity file hits on added lines, by what they matched:

| Match | Assessment |
|---|---|
| A Node environment tool writes `.npmrc` paths into the shell scripts it generates | Accurate, legitimate |
| A cloud CLI writes the user's `~/.npmrc` for a registry login | Accurate, legitimate |
| A library calls `subprocess.check_call([sys.executable, "-m", "pip", "install", ...])` at runtime | Accurate; worth a reviewer's glance |
| `.env` inside an error message string | Noise |
| A `.xyz` domain in a hardcoded API URL | Noise |

## Why this split

- **Added lines matter more than the rule source.** Restricting to added lines removed most of the matches,
  whichever rules ran.
- **The `capability-*` rules describe normal code.** They still fire on 18% of routine pairs even with added lines
  only. At check level they would drown the page, and at note level they give useful context ("this release adds
  outbound network code").
- **The `threat-*` rules are selective but string-blind.** Two of five high-severity hits matched text inside string
  literals. That precision is fine for "worth a glance", but not for "look before merging". High-level behavior
  signals need to know whether a match is a call, an import or a string, which an AST rule can tell.
- **Vendoring beats re-implementing.** GuardDog's rules are maintained against real malware campaigns; copying them at
  a pinned tag gets that coverage, with a reviewable diff on every update.

## Follow-ups

- Fetch the shared `.meta` include files when vendoring, so all 54 rules compile.
- GuardDog's `path_include` and `max_hits` are GuardDog's own metadata, not YARA. The Rust wrapper has to apply them.
- Tune the level mapping against the hand-checked sample (#55), rule by rule.
