# Sightglass

See what a package release actually ships.

Sightglass compares the files people install from a package index with the previous release and with the project's
git tag, and shows the differences that matter for supply chain security: a dropped attestation, files that aren't in
the source, new code that runs on import. Later, a GitHub App brings the same view into pull requests that update a
lockfile.

Status: early development. The Python backend is scaffolded; nothing runs yet.

- [Design](docs/design.md)
- [Background](docs/background.md): why this project, and the ideas it was chosen over
- [Naming](docs/naming.md)
- [Mockups](docs/mockups/README.md) (open the HTML files in a browser):
  - [Release diff page](docs/mockups/release-diff.html), phase 1
  - [Pull request review page](docs/mockups/lockfile-lens.html), phase 2

## Installation

Install [pixi](https://pixi.sh), then:

```bash
pixi install
pixi run bootstrap   # installs the pre-commit hooks
```

## Development

| Command | What it runs |
|---|---|
| `pixi run test` | Backend unit tests |
| `pixi run test-integration` | Backend integration tests |
| `pixi run fmt` / `lint` / `check` | ruff format, ruff check, mypy (strict) |
| `pixi run cov` | Full backend test suite with the 90% coverage gate |
| `pixi run ci` | Everything above plus pre-commit and the build; must pass before a commit |

Layout: `backend/` holds the Python package (`backend/src/sightglass/`) and its tests; `frontend/` will hold the React
app.

## License

Not chosen yet. See the open questions in the design.
