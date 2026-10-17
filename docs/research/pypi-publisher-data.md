# What PyPI exposes about uploads and publishers

Spike for [#10](https://github.com/aesir-oss/sightglass/issues/10), run 2026-10-17. Answers the design's open
question 1: how much upload information does PyPI expose per file beyond attestations?

## Short answer

- **No API names the account that uploaded a file.** The mockups' uploader name isn't available, so the page can't show
  one.
- **Attestations say much more than expected.** Besides the trusted publisher's repository, workflow and environment, the
  signing certificate records the exact commit the release was built from, the git ref, the runner type and the event
  that triggered the build. That commit is a better link to the source than guessing a tag.
- **44% of the top 500 packages attest their latest release.** Absence is the normal case, so only a change between
  releases is worth a signal, never absence by itself.
- **Project owners and maintainers are public** (account names and roles), but only as they are now, with no history.

## Sources

| API | What it gives per file | Upload identity |
|---|---|---|
| JSON API, `/pypi/<project>/json` | Filename, size, digests, upload time, `requires_python`, yanked state, core metadata hash | None |
| JSON API, top-level `ownership` | `organization`, and `roles`: a list of `{user, role}`, with `Owner` or `Maintainer` | Who *can* publish now, not who did |
| Simple API, `/simple/<project>/` with `application/vnd.pypi.simple.v1+json` (API 1.4) | Filename, hashes, size, `upload-time`, yanked state, and a `provenance` URL when the file is attested | Pointer to the attestation |
| Integrity API, `/integrity/<project>/<version>/<file>/provenance` (PEP 740) | Attestation bundles: the publisher, plus a DSSE envelope and a Sigstore certificate | Trusted publisher identity |

PyPI's web pages also show the upload client and whether a file was uploaded with Trusted Publishing, but no API
exposes them, and automated requests got a challenge page instead of the content. Sightglass won't scrape them.

### The attestation

The publisher object depends on the kind. For GitHub:

```json
{ "kind": "GitHub", "repository": "<owner>/<repo>", "workflow": "release.yml", "environment": "pypi" }
```

For Google it carries only a service account `email`, and GitLab has its own shape. The in-toto statement has the
predicate type `https://docs.pypi.org/attestations/publish/v1` and the file's sha256 as its subject.

The Sigstore (Fulcio) certificate carries these extensions for GitHub and GitLab builds:

| OID | Meaning | Example |
|---|---|---|
| `1.3.6.1.4.1.57264.1.9` | Build signer URI | `https://github.com/<owner>/<repo>/.github/workflows/release.yml@refs/heads/main` |
| `1.3.6.1.4.1.57264.1.11` | Runner environment | `github-hosted` or `self-hosted` |
| `1.3.6.1.4.1.57264.1.12` | Source repository URI | `https://github.com/<owner>/<repo>` |
| `1.3.6.1.4.1.57264.1.13` | Source repository digest | the commit SHA |
| `1.3.6.1.4.1.57264.1.14` | Source repository ref | `refs/tags/v1.2.3` or `refs/heads/main` |
| `1.3.6.1.4.1.57264.1.20` | Build trigger | `push`, `release`, `workflow_dispatch`, ... |
| `1.3.6.1.4.1.57264.1.21` | Run invocation URI | link to the workflow run |

These claims are only as trustworthy as the bundle's verification: the certificate chain to Sigstore's root, the
transparency log entry, and the signature over the statement. PyPI performs that verification against the trusted
publisher when a file is uploaded, before the Integrity API serves the attestation.

## Measurements

The top 500 packages by downloads over 30 days ([hugovk/top-pypi-packages](https://hugovk.dev/top-pypi-packages/),
list updated 2026-10-01), with the three most recent non-yanked releases of each. Attestation details come from the
first attested file of each release; certificate claims were read without verifying the bundle.

### Latest release

| | Packages |
|---|---|
| At least one file attested | 221 (44.2%) |
| Every file attested | 219 |
| Some files attested and some not | 2 |
| Publisher kind GitHub / Google / GitLab | 203 / 17 / 1 |
| Deployment environment set (Google publishers have no such field) | 162 of 221 |
| Built on a GitHub-hosted runner | 203 (no self-hosted runners seen) |
| Built from a tag ref / branch ref / pull request merge ref | 170 / 32 / 2 |
| Build trigger `push` / `release` / `workflow_dispatch` / other | 124 / 44 / 29 / 7 |
| `ownership.organization` set | 104 |
| `ownership.roles` lists at least one account | 474 |

### Consecutive releases

1,000 pairs of a release and the one uploaded before it.

| Change | Pairs |
|---|---|
| Attested in both | 381 |
| Attestation adopted (none before, present now) | 42 |
| Attestation dropped (present before, none now) | 3 |
| Publisher repository or workflow changed (both attested) | 3 |
| Deployment environment changed | 3, all from none (or another name) to `pypi` |
| Build trigger changed | 5 |
| Runner environment changed | 0 |

What was behind them:

- **Drops:** one of the three was a maintenance release on an older line (2.0.x) uploaded after the newer line's
  2.1.4. "Previous release" sorted by upload time compared two different release lines.
- **Publisher changes:** a renamed repository, a release workflow moved to a separate repository, and a renamed
  workflow file. All three look routine, and all three are exactly what an account takeover would also look like. The
  evidence has to show both identities side by side.
- **Environment changes:** all three added protection, which is the safe direction.
- **Trigger changes:** schedule, push and manual dispatch swap around in routine releases.

## Recommendations

1. **Drop the uploader name** from the page and the mockups' release facts. Show the attested publisher, or "not
   attested", never a guess.
2. **Source from the attested commit.** When a verified attestation names a source repository and commit, fetch that
   commit's archive for the source check, and use tag discovery only when there's no attestation. If both exist and
   the tag points somewhere else, that's a fact worth showing.
3. **"Previous release" means the previous version on the same release line**, by version order, not upload time. This
   matters for the release timeline and for every "changed since the previous release" signal.
4. **Store more of the attestation:** environment, source repository, commit, ref, runner environment, build trigger,
   run URL, the Google service account email, and whether the bundle verified.
5. **Signal levels**, all subject to tuning against the hand-checked sample (#55):

   | Signal | Level | Seen in the sample |
   |---|---|---|
   | Attestation present in the previous release, missing in this one | high | 3 of 1,000 pairs, one an ordering artifact |
   | Publisher repository or workflow changed | high | 3 of 381 attested pairs, all routine |
   | Some files attested and others not | check | 2 latest releases |
   | Runner changed to self-hosted | check | not seen |
   | Built from a pull request ref | check | 2 latest releases |
   | Deployment environment removed | check | not seen |
   | Deployment environment added | note | 3 pairs |
   | Build trigger changed | note | 5 pairs |
   | Not attested, and no earlier release was | clean | 56% of latest releases |

6. **Snapshot ownership.** PyPI shows owners and maintainers only as they are now. Recording `ownership` each time a
   release is analyzed would let a later rule report "account added as owner since the previous release". The account
   names are public, but the page should show only the change, not profile people.
7. **Trust PyPI's verification; verify independently later.** Revised 2026-10-17 while building #19: because PyPI
   verifies attestations on upload, reading them from the Integrity API over TLS is as trustworthy as the hashes
   Sightglass already takes from PyPI. Verifying the bundles again only guards against a compromised PyPI, which is
   outside the threat model, and would add Sigstore's dependency tree and a trust-root download to every worker. The
   client parses the claims with `cryptography` and stores `verified = false`, meaning "not verified by Sightglass";
   independent verification is #96.

## Caveats

- Popular packages adopt attestations earlier than the long tail.
- Only the first attested file of each release was decoded; files within a release could differ.
- Certificate claims for GitHub and GitLab builds come from Fulcio's extensions. Google-published files carry an email
  identity instead.
