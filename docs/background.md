# How Sightglass was chosen

Recorded 2026-10-16, from the brainstorming that led to this project.

## What the project had to be

- **Visual and interactive.** The one firm requirement. A command-line tool alone wasn't enough.
- **Reachable by others.** A web service that people can open without installing anything.
- **Useful to the community**, in software supply chain security.
- **Stack:** a Python backend and a frontend built with Node are fine. Rust only where it earns its place.

## Ideas considered

| Idea | What it was | Outcome |
|---|---|---|
| Dependency History Explorer | Scrub through a project's dependency graph over time | Liked the visual side; not chosen |
| Ecosystem Atlas | A zoomable map of a whole package ecosystem | Liked; not chosen |
| Resolver Replay | Watch a dependency resolver search and backtrack, step by step (mockup built) | Not a fit: outside supply chain, didn't land |
| File X-ray | Explore the structure of binary files interactively | Not chosen |
| VEX authoring, provenance verifier, trust badges, SBOM exchange hub, SBOM inventory and blast radius | Tools that read or produce supply chain data after the fact | Didn't land: people look at that data only when forced to |
| Rebuild verifier, cooldown proxy, attack range, package heartbeat, org constellation, trust path explorer | Assorted supply chain services | Didn't land |
| Release diff viewer | What changed in the files a release actually ships | **Chosen, as phase 1** |
| Lockfile PR lens | A review page for pull requests that change a lockfile | **Chosen, as phase 2** |
| Workflow graph auditor | Map GitHub Actions workflows, pinning, permissions and secrets | Candidate for later |
| Publisher map | Who can push a release into your build, and when that changed | Folded into Sightglass's publisher signals |
| Lookalike watch | Lookalike package names across indexes | Folded in as a name signal |

## Why these two

Earlier ideas were about reading data after the fact. Sightglass is built around a moment when someone makes a
decision: merging a dependency update. Tools used at decision points get used every day.

The release diff is the engine and stands on its own as a public, linkable page. The pull request review is how people
find it in their daily work. Together they're visual throughout (release timeline, file treemap, dependency graph,
diffs), fit the Python and Node stack, and reuse lockfile knowledge from pixi.

## Mockups

Both mockups are in [`mockups/`](mockups/). Their packages, people and repositories are invented; see
[`mockups/README.md`](mockups/README.md).
