"""The job queue: procrastinate on the application database, with the release-pair analysis task.

One job per release pair. Requests for a pair that is already queued are deduplicated by a queueing lock, and a
lock on the same key keeps two workers from analyzing one pair at once. Transient failures are retried with
exponential backoff; on the last attempt an unreachable source repository is stored as "couldn't compare".
"""

from functools import cache

import procrastinate
from procrastinate.exceptions import AlreadyEnqueued
from sqlalchemy import Engine, make_url
from sqlalchemy.orm import Session

from sightglass.db.engine import database_url, make_engine
from sightglass.db.names import normalize_name
from sightglass.log import get_logger
from sightglass.worker.pipeline import (
    PipelineError,
    Services,
    TransientError,
    analyze_release_pair,
    default_cache_dir,
)

log = get_logger(__name__)

TASK = "sightglass:analyze_pair"
# Retries after the first run; waits 4, 16, 64, 256 and 1024 seconds.
MAX_ATTEMPTS = 5
RETRY = procrastinate.RetryStrategy(max_attempts=MAX_ATTEMPTS, exponential_wait=4, retry_exceptions=[TransientError])


def conninfo(url: str | None = None) -> str:
    """The libpq connection string for a SQLAlchemy URL, or for ``SIGHTGLASS_DATABASE_URL``."""
    return make_url(url or database_url()).set(drivername="postgresql").render_as_string(hide_password=False)


def make_app(url: str | None = None) -> procrastinate.App:
    """A procrastinate app on the database at ``url`` (default: ``SIGHTGLASS_DATABASE_URL``) with Sightglass's tasks."""
    # A blueprint binds to one app, so each app gets its own.
    tasks = procrastinate.Blueprint()
    tasks.task(name="analyze_pair", retry=RETRY, pass_context=True)(analyze_pair)
    app = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=conninfo(url)))
    app.add_tasks_from(tasks, namespace="sightglass")
    return app


def pair_key(ecosystem: str, package: str, from_version: str, to_version: str, wheel: str | None = None) -> str:
    """The lock key for a release pair (and a chosen wheel), with the package name normalized."""
    key = f"{ecosystem}:{normalize_name(ecosystem, package)}:{from_version}...{to_version}"
    return f"{key}:{wheel}" if wheel else key


def enqueue_analysis(
    app: procrastinate.App,
    ecosystem: str,
    package: str,
    from_version: str,
    to_version: str,
    wheel: str | None = None,
) -> int | None:
    """Queue an analysis of a release pair; returns the job id, or None when the pair is already queued.

    With ``wheel``, only that wheel pair is analyzed instead of the default sdist and wheel pairs.
    """
    key = pair_key(ecosystem, package, from_version, to_version, wheel)
    deferrer = app.configure_task(TASK, lock=key, queueing_lock=key)
    kwargs = {"ecosystem": ecosystem, "package": package, "from_version": from_version, "to_version": to_version}
    if wheel:
        kwargs["wheel"] = wheel
    try:
        job_id = deferrer.defer(**kwargs)
    except AlreadyEnqueued:
        log.info("analysis_already_queued", key=key)
        return None
    log.info("analysis_queued", key=key, job_id=job_id)
    return job_id


@cache
def _services() -> Services:
    return Services.default(default_cache_dir())


@cache
def _engine() -> Engine:
    return make_engine()


def analyze_pair(
    context: procrastinate.JobContext,
    ecosystem: str,
    package: str,
    from_version: str,
    to_version: str,
    wheel: str | None = None,
) -> None:
    """Run the pipeline for a release pair; a pair that can't be analyzed at all fails without retrying."""
    if ecosystem != "pypi":
        raise PipelineError("unsupported_ecosystem", f"{ecosystem} isn't supported yet")
    job = context.job
    final = job.attempts >= MAX_ATTEMPTS
    with Session(_engine()) as session:
        try:
            results = analyze_release_pair(
                session, _services(), package, from_version, to_version, final_attempt=final, wheel=wheel
            )
        except PipelineError as exc:
            log.error("analysis_impossible", reason=exc.reason, error=str(exc), job_id=job.id)
            raise
    log.info(
        "analysis_finished",
        job_id=job.id,
        pairs=[(r.old_filename, r.new_filename, r.status, len(r.signals)) for r in results],
    )
