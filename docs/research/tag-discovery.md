# Tag discovery across popular PyPI packages

Spike for [#9](https://github.com/aesir-oss/sightglass/issues/9), run 2026-10-17. Answers the design's open
question 3: how often do `v{version}` or `{version}` find the right git tag?

## Short answer

For the latest stable release of popular packages, `v{version}` or `{version}` finds the tag **87%** of the time. A
longer ordered list of patterns brings that to **94%**. 97% of packages use one pattern consistently across
releases, so remembering the pattern that matched the previous release is the strongest heuristic after the basic
list. Pre-releases are tagged much less often (65%), and 7% of packages don't link a GitHub repository at all.

## Method

- **Sample:** the top 500 packages by downloads over 30 days, from
  [hugovk/top-pypi-packages](https://hugovk.dev/top-pypi-packages/) (list updated 2026-10-01).
- **Releases:** the three most recent non-yanked releases of each package, from the PyPI JSON API.
- **Repository:** the first GitHub URL in `project_urls` (then `home_page`), preferring keys that start with *source*,
  *source code*, *repository*, *code*, *github* or *homepage*. Keys for documentation, issue trackers, funding and
  codes of conduct are skipped, as is any organization's `.github` repository.
- **Tags:** `git ls-remote --tags` against the repository, without the GitHub API, so rate limits didn't matter.
- **Match:** the first pattern from the list below whose expansion is a tag. `{name}` is tried as the PyPI name, its
  PEP 503 normalized form and that form with underscores. If none matches, any tag that contains the version as a
  whole token is recorded as "other pattern". A release is "pre-release" if its version has an `a`, `b`, `rc`, `dev` or
  similar segment.
- **Not checked:** whether the tagged commit is the one the wheel was built from. A tag existing is necessary for the
  source check, not proof that it matches.

Every checked release is in [`tag-discovery-2026-10-17.csv`](tag-discovery-2026-10-17.csv).

## Results

### Repositories

| Outcome | Packages |
|---|---|
| GitHub repository found and reachable | 467 (93.4%) |
| No GitHub URL in the metadata | 33 (6.6%) |

Of the 33 without a GitHub URL: 6 list no project URL at all, 10 point to another forge (SourceForge 3, Codeberg 3,
Heptapod 2, GitLab 1, Launchpad 1), 3 point only to their documentation, and 14 to project websites. None of the GitHub repositories found was
unreachable.

The key that supplied the URL: *homepage* 143, *source* 142, *repository* 109, *source code* 31, *github* 19,
*code* 11, others 12. Nearly a third come from *homepage*, so it can't be skipped.

### Latest stable release per package

456 of the 467 packages had a stable release among their last three.

| Patterns tried | Tag found | Rate |
|---|---|---|
| `v{version}`, `{version}` | 398 | 87.3% |
| The full ordered list below | 430 | 94.3% |
| Same pattern for every checked stable release of the package | 443 | 97.1% |

### All checked releases

| | Releases | Named pattern | Other pattern | No tag |
|---|---|---|---|---|
| Stable | 1,305 | 1,236 (94.7%) | 18 (1.4%) | 51 (3.9%) |
| Pre-release | 96 | 62 (64.6%) | 1 (1.0%) | 33 (34.4%) |

Stable releases by the pattern that matched:

| Pattern | Releases |
|---|---|
| `v{version}` | 596 |
| `{version}` | 550 |
| `{name}-v{version}` | 52 |
| `{name}_{version}` | 11 |
| `{name}=={version}` | 9 |
| `{name}-{version}` | 7 |
| `rel_{version with underscores}` | 6 |
| `{repo}-{version}` | 3 |
| `{name}/{version}` | 1 |
| `{version}` padded with `.0` (`3.11` tagged `3.11.0`) | 1 |

No tag matched only when compared case-insensitively.

### Where no named pattern matched

- **Project-specific prefixes (18 stable releases):** `py-{version}` in a Rust-first monorepo, `apache-arrow-{version}`,
  `release_{version}`, `RELEASE_{version}`, `version-{version}`, and a short name (`checkpoint=={version}`) in a monorepo.
  Each is consistent within its project, so a per-project pattern covers it.
- **Type stub packages (18 stable releases):** `types-*` packages from typeshed are released from a monorepo with no
  per-package tags, by design.
- **No tag for the release (33 stable releases):** some projects tag only some releases, tag after a delay, or don't
  tag at all (two repositories have no tags).
- **URL points to an umbrella repository:** a few packages link a monorepo or an organization-wide repository whose
  tags belong to a different package.

## Recommendations for the source fetcher (#19)

1. **Ordered pattern list.** Try, in order: `v{version}`, `{version}`, `{name}-v{version}`, `{name}_{version}`,
   `{name}=={version}`, `{name}-{version}`, `{name}/v{version}`, `{name}/{version}`, `{repo}-{version}`,
   `{repo}-v{version}`, `release-{version}`, `rel_{version with underscores}`, then `v{version}.0` and `{version}.0`
   for two-part versions. Match case-sensitively.
2. **Remember what worked.** Store the matched pattern per package and try it first for the next release. With 97% of
   packages consistent, this also makes a sudden pattern change visible.
3. **Per-project overrides** for the prefixes above (`py-`, `apache-arrow-`, `release_`, `RELEASE_`), kept in a small
   reviewed file rather than guessed.
4. **No loose fallback.** Matching any tag that contains the version would compare against the wrong tag in
   monorepos. The source match signals are high level, so a wrong tag means false positives. When nothing matches,
   show "couldn't compare" with the patterns tried.
5. **Repository URL selection.** Prefer *source*, *repository* and *source code* keys over *homepage*, skip
   documentation, issue tracker, funding and code of conduct links, and skip `.github` repositories. Show which URL was
   used, since it can point to an umbrella repository.
6. **Known no-tag packages.** Treat typeshed `types-*` stubs as a known "couldn't compare" case with that reason,
   instead of a failed search.
7. **Pre-releases.** Expect "couldn't compare" for about a third of them; that's how projects tag, not a signal.
8. **Other forges.** SourceForge, Codeberg, Heptapod, GitLab and Launchpad together cover 2% of this sample. They can
   wait until after phase 1.

## Caveats

- Popular packages are better maintained than the long tail, so these rates are likely an upper bound.
- Tags were read once, at one time. A tag created after a release, or moved later, looks the same as one created at
  release time.
- The check is by name only; whether the tagged tree matches the wheel is the source check's job.
