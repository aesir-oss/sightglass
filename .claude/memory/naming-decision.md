---
name: naming-decision
description: Name is Sightglass; registry names don't matter for a hosted service; avoid sightglas/sight-glass
metadata:
  type: project
---

Decided 2026-10-16 after many rounds (shipping, instruments, Norse, myth). The plain name is taken on PyPI, npm and crates.io by unrelated projects, which doesn't matter for a hosted service and GitHub App. The GitHub App slug `sightglass` looked free.

**Why:** The maintainer asked why registry availability mattered for a web service; it doesn't, only the App slug, domain and repo do.
**How to apply:** Don't reopen the name. If a CLI is ever published, use a qualified name like `sightglass-cli`, never a one-character variant. Full record in docs/naming.md.
