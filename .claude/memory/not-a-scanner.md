---
name: not-a-scanner
description: Sightglass has no vulnerability database and never runs package code
metadata:
  type: project
---

Sightglass compares published files and metadata. It does no CVE matching, keeps no vulnerability database, and does no dynamic analysis: no installs, builds, imports or sandboxed runs, in any planned phase.

**Why:** OSV, Grype and dependency-review-action already cover known vulnerabilities, and executing hostile package code would make the service itself the target.
**How to apply:** Push back on features that need a vuln feed or code execution; suggest linking to the existing tools instead. Workers only read archives and text. See [[facts-not-verdicts]].
