# Security policy

Sightglass downloads and unpacks packages that may be hostile, so the service itself is a target. Reports are welcome.

## Reporting a vulnerability

Report privately through GitHub:
[Report a vulnerability](https://github.com/aesir-oss/sightglass/security/advisories/new). Don't open a public issue or
pull request for a vulnerability.

Include what you found, how to reproduce it, and what an attacker could do with it. You'll get an acknowledgement within
7 days. We'll agree on a disclosure date with you and credit you in the advisory unless you'd rather not be named.

## In scope

- Archive handling: path traversal, links outside the unpack root, zip bombs, crashes or memory errors in the Rust core.
- Anything that makes a worker execute package code, or reach hosts other than package indexes and source hosts.
- Cross-site scripting through file contents, package metadata or signal messages shown on a page.
- GitHub App issues: webhook signature bypass, acting on repositories without access, leaking installation tokens.
- Denial of service that a single client can cause despite the rate limits.
- Our own supply chain: CI workflows, release artifacts, dependency pinning.

## Out of scope

- A signal that misses a malicious package, or fires on a benign one. That's a rule quality issue; open a normal issue
  without exploit details.
- Vulnerabilities in the packages Sightglass analyzes. Report those to the package's maintainers or the index.
- Findings that need a compromised maintainer machine or GitHub account.

## Supported versions

Only the latest code on `main` and the hosted service built from it.
