"""Review a pull request's lockfile change: diff the two lockfiles, record the review, queue the analyses.

The same steps serve the local ``pixi run review`` command and, later, the GitHub App's webhook (#62); only where the
files come from differs.
"""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from sightglass.ecosystems.http import HttpError
from sightglass.ecosystems.pypi import PypiClient
from sightglass.ecosystems.versions import predecessor
from sightglass.lockfiles.diff import Change, diff_lockfiles
from sightglass.lockfiles.manifest import Manifest, parse_manifest
from sightglass.lockfiles.model import Ecosystem, Lockfile
from sightglass.lockfiles.pixi import LockfileError, parse_pixi_lock
from sightglass.lockfiles.store import record_review
from sightglass.lockfiles.uv import parse_uv_lock
from sightglass.log import get_logger

log = get_logger(__name__)

# Queues an analysis of (ecosystem, package, from version, to version).
Enqueue = Callable[[str, str, str, str], object]


@dataclass(frozen=True)
class Snapshot:
    """A lockfile as one commit has it, with the workspace manifest beside it when there is one."""

    lockfile: bytes
    manifest: tuple[str, bytes] | None = None


def parse_lockfile(path: str, content: bytes) -> Lockfile:
    """Parse a lockfile by its name.

    Raises:
        LockfileError: If the format isn't supported or the file can't be read.
    """
    name = path.rsplit("/", 1)[-1]
    if name == "pixi.lock":
        return parse_pixi_lock(content)
    if name == "uv.lock":
        return parse_uv_lock(content)
    raise LockfileError(f"{name} isn't a supported lockfile (pixi.lock, uv.lock)")


def manifest_names(lockfile_path: str) -> list[str]:
    """Where a lockfile's workspace manifest may be, in the order to try; uv lockfiles name their members instead."""
    directory, _, name = lockfile_path.rpartition("/")
    prefix = f"{directory}/" if directory else ""
    return [f"{prefix}pixi.toml", f"{prefix}pyproject.toml"] if name == "pixi.lock" else []


def _compared_against(pypi: PypiClient, change: Change) -> str | None:
    """The release a change's new version is analyzed against: its from version, or an added package's predecessor."""
    if change.kind != "added" or change.to_version is None:
        return change.from_version
    try:
        project = pypi.project(change.name)
    except HttpError as exc:
        log.warning("review_predecessor_unavailable", package=change.name, error=str(exc))
        return None
    before = (
        predecessor(project, change.to_version) if change.to_version in {r.version for r in project.releases} else None
    )
    return before.version if before else None


def review_lockfile(
    session: Session,
    *,
    pypi: PypiClient,
    enqueue: Enqueue,
    repository: str,
    pull_number: int,
    base_sha: str,
    head_sha: str,
    lockfile_path: str,
    base: Snapshot,
    head: Snapshot,
) -> int:
    """Diff a lockfile between two commits, record the review, and queue an analysis for each PyPI package that changed.

    Args:
        session: The session to write through; the caller commits.
        pypi: Index client, for an added package's predecessor.
        enqueue: Queues one release pair analysis.
        repository: ``owner/name``.
        pull_number: The pull request's number.
        base_sha: The base commit.
        head_sha: The head commit.
        lockfile_path: The lockfile's path in the repository.
        base: The lockfile and manifest at the base commit.
        head: The lockfile and manifest at the head commit.

    Returns:
        The review's id.

    Raises:
        LockfileError: If either lockfile can't be read.
    """
    old, new = parse_lockfile(lockfile_path, base.lockfile), parse_lockfile(lockfile_path, head.lockfile)
    manifests = [m for s in (base, head) if s.manifest and (m := parse_manifest(*s.manifest)) is not None]

    def direct(environment: str) -> set[tuple[Ecosystem, str]]:
        return {key for m in manifests for key in Manifest.direct(m, environment)}

    changes = diff_lockfiles(old, new, direct)
    compare_from: dict[tuple[str, str], str] = {}
    for change in changes:
        if change.ecosystem != "pypi" or change.to_version is None:
            continue
        against = _compared_against(pypi, change)
        if change.kind == "added" and against is not None:
            compare_from[("pypi", change.name)] = against
        if against is not None:
            enqueue("pypi", change.name, against, change.to_version)
    review_id = record_review(
        session,
        repository=repository,
        pull_number=pull_number,
        base_sha=base_sha,
        head_sha=head_sha,
        lockfile_path=lockfile_path,
        changes=changes,
        compare_from=compare_from,
    )
    log.info(
        "review_recorded", review_id=review_id, repository=repository, pull_number=pull_number, changes=len(changes)
    )
    return review_id
