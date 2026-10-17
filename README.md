# Sightglass

See what a package release actually ships.

Sightglass compares the files people install from a package index with the previous release and with the project's
git tag, and shows the differences that matter for supply chain security: a dropped attestation, files that aren't in
the source, new code that runs on import. Later, a GitHub App brings the same view into pull requests that update a
lockfile.

Status: design. No code yet.

- [Design](docs/design.md)
- Mockups (open the HTML files in a browser):
  - [Release diff page](docs/mockups/release-diff.html), phase 1
  - [Pull request review page](docs/mockups/lockfile-lens.html), phase 2

## License

Not chosen yet. See the open questions in the design.
