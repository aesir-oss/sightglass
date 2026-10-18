"""Release history: every release of a package with its publish time, attestation state and publisher.

The first request records the package's releases and artifacts. Which files are attested comes from one Simple API
request. Publisher details need an Integrity API request per file, so they are fetched for the most recent attested
releases only and kept in Postgres; older releases show their publisher once a pair including them is analyzed.
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from sightglass.api.deps import Index, get_index, get_session
from sightglass.db import models
from sightglass.ecosystems.http import HttpError, NotFoundError, UnavailableError
from sightglass.ecosystems.provenance import record_provenance
from sightglass.ecosystems.pypi import PypiProject
from sightglass.ecosystems.versions import latest, predecessor
from sightglass.log import get_logger
from sightglass.worker.catalog import record_artifact, record_package, record_release

log = get_logger(__name__)

# Attested releases, newest first, whose publisher details are fetched on a request.
RECENT_PUBLISHERS = 10
RETRY_AFTER_SECONDS = 30

AttestationState = Literal["all", "some", "none", "unknown"]
router = APIRouter()


class Publisher(BaseModel):
    """Who published a release, from its attestation."""

    kind: str
    repository: str | None
    workflow: str | None
    environment: str | None


class ReleaseSummary(BaseModel):
    """One release in the history."""

    version: str
    published_at: datetime | None
    yanked: bool
    attestation: AttestationState
    publisher: Publisher | None
    # The release this one is compared with by default: the version before it, not the one published before it.
    previous: str | None


class ReleaseHistory(BaseModel):
    """A package's releases, oldest first."""

    ecosystem: Literal["pypi"]
    package: str
    display_name: str
    releases: list[ReleaseSummary]
    # The highest stable version, which the package page opens; None for a project with no releases.
    latest: str | None


def _record(session: Session, index: Index, project: PypiProject) -> dict[str, list[int]]:
    """Record releases and artifacts, and each artifact's attestation state; returns artifact ids by version."""
    package_id = record_package(session, project)
    try:
        attested = index.integrity.provenance_urls(project.name)
    except HttpError as exc:
        # The history still renders; attestation states stay as recorded, or unknown.
        log.warning("attestation_states_unavailable", package=project.name, error=str(exc))
        attested = {}
    ids: dict[str, list[int]] = {}
    for release in project.releases:
        release_id = record_release(session, package_id, release)
        for file in release.files:
            if file.kind not in ("wheel", "sdist"):
                continue
            artifact_id = record_artifact(session, release_id, file)
            ids.setdefault(release.version, []).append(artifact_id)
            if file.filename in attested:
                status = "present" if attested[file.filename] else "absent"
                session.execute(
                    update(models.Artifact)
                    .where(models.Artifact.id == artifact_id, models.Artifact.provenance_status != status)
                    .values(provenance_status=status)
                )
    return ids


def _fetch_recent_publishers(session: Session, index: Index, project: PypiProject, ids: dict[str, list[int]]) -> None:
    """Fetch attestations for the newest attested releases that have none stored yet."""
    fetched = 0
    for release in reversed(project.releases):
        if fetched >= RECENT_PUBLISHERS:
            break
        rows = session.scalars(select(models.Artifact).where(models.Artifact.id.in_(ids.get(release.version, []))))
        artifact = next((a for a in rows if a.provenance_status == "present"), None)
        if artifact is None:
            continue
        fetched += 1
        stored = session.scalar(select(models.Attestation.id).where(models.Attestation.artifact_id == artifact.id))
        if stored is not None:
            continue
        try:
            provenance = index.integrity.provenance(project.name, release.version, artifact.filename)
        except UnavailableError:
            raise
        except HttpError as exc:
            log.warning("publisher_unreadable", filename=artifact.filename, error=str(exc))
            continue
        record_provenance(session, artifact.id, provenance)


def _state(statuses: list[str]) -> AttestationState:
    if not statuses or "unknown" in statuses:
        return "unknown"
    present = statuses.count("present")
    return "all" if present == len(statuses) else "some" if present else "none"


def release_history(session: Session, index: Index, package: str) -> ReleaseHistory:
    """Build the history of a PyPI package, recording what the index says along the way.

    Raises:
        sightglass.ecosystems.http.NotFoundError: If the index has no such package.
        sightglass.ecosystems.http.HttpError: For other index failures.
    """
    project = index.pypi.project(package)
    ids = _record(session, index, project)
    _fetch_recent_publishers(session, index, project, ids)
    session.commit()

    releases = []
    for release in project.releases:
        artifacts = list(
            session.scalars(select(models.Artifact).where(models.Artifact.id.in_(ids.get(release.version, []))))
        )
        attestation = session.scalars(
            select(models.Attestation)
            .where(models.Attestation.artifact_id.in_([a.id for a in artifacts]))
            .order_by(models.Attestation.id)
        ).first()
        publisher = (
            Publisher(
                kind=attestation.publisher_kind,
                repository=attestation.repository,
                workflow=attestation.workflow,
                environment=attestation.environment,
            )
            if attestation
            else None
        )
        releases.append(
            ReleaseSummary(
                version=release.version,
                published_at=release.published_at,
                yanked=release.yanked,
                attestation=_state([a.provenance_status for a in artifacts]),
                publisher=publisher,
                previous=before.version if (before := predecessor(project, release.version)) else None,
            )
        )
    newest = latest(project)
    return ReleaseHistory(
        ecosystem="pypi",
        package=project.normalized_name,
        display_name=project.name,
        releases=releases,
        latest=newest.version if newest else None,
    )


@router.get(
    "/api/{ecosystem}/{package}/releases",
    operation_id="getReleaseHistory",
    responses={404: {"description": "Unknown ecosystem or package"}, 503: {"description": "The index is unavailable"}},
)
def get_release_history(
    ecosystem: Annotated[str, Path(description="Package ecosystem; only pypi for now")],
    package: Annotated[str, Path(description="Package name, in any spelling")],
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    index: Annotated[Index, Depends(get_index)],
) -> ReleaseHistory:
    """Every release of a package, oldest first, with its attestation state and publisher."""
    if ecosystem != "pypi":
        raise HTTPException(404, f"unsupported ecosystem {ecosystem!r}")
    try:
        history = release_history(session, index, package)
    except NotFoundError as exc:
        raise HTTPException(404, f"{package} isn't on PyPI") from exc
    except HttpError as exc:
        log.warning("index_unavailable", package=package, error=str(exc))
        raise HTTPException(
            503, "PyPI is unavailable; try again shortly", headers={"Retry-After": str(RETRY_AFTER_SECONDS)}
        ) from exc
    response.headers["Cache-Control"] = "public, max-age=60"
    return history
