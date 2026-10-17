"""Storing rule results: one analysis per artifact pair and rule-set version, with its signals."""

from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from sightglass.db import models
from sightglass.rules.base import Signal


def current_analysis(session: Session, from_id: int, to_id: int, ruleset_version: str) -> models.Analysis | None:
    """Return the finished analysis of a pair under ``ruleset_version``, or None if it must be (re)computed.

    Analyses under other rule-set versions are stale and are never returned, and so are analyses stored before
    reports existed, which the page can't show.
    """
    return session.scalar(
        select(models.Analysis).where(
            models.Analysis.from_artifact_id == from_id,
            models.Analysis.to_artifact_id == to_id,
            models.Analysis.ruleset_version == ruleset_version,
            models.Analysis.status == "done",
            models.Analysis.report.is_not(None),
        )
    )


def save_analysis(
    session: Session,
    from_id: int,
    to_id: int,
    ruleset_version: str,
    signals: list[Signal],
    report: dict[str, Any] | None = None,
) -> int:
    """Store a finished analysis and its signals, replacing any earlier result for the same key.

    Args:
        session: The session to write through; the caller commits.
        from_id: The earlier artifact.
        to_id: The later artifact.
        ruleset_version: :attr:`RuleSet.version` of the rules that ran.
        signals: What the rules reported.
        report: File pairs, source check and facts for the page.

    Returns:
        The analysis id.
    """
    stmt = (
        insert(models.Analysis)
        .values(
            from_artifact_id=from_id,
            to_artifact_id=to_id,
            ruleset_version=ruleset_version,
            status="done",
            finished_at=func.now(),
            report=report,
        )
        .on_conflict_do_update(
            index_elements=["from_artifact_id", "to_artifact_id", "ruleset_version"],
            set_={"status": "done", "error": None, "finished_at": func.now(), "report": report, "step": None},
        )
        .returning(models.Analysis.id)
    )
    analysis_id = int(session.execute(stmt).scalar_one())
    session.execute(delete(models.Signal).where(models.Signal.analysis_id == analysis_id))
    session.add_all(
        models.Signal(
            analysis_id=analysis_id,
            rule_id=s.rule_id,
            level=s.level,
            message=s.message,
            evidence=s.evidence_json(),
        )
        for s in signals
    )
    session.flush()
    return analysis_id


def fail_analysis(session: Session, from_id: int, to_id: int, ruleset_version: str, reason: str) -> int:
    """Record that analyzing a pair failed for a reason that retrying won't fix; returns the analysis id."""
    stmt = (
        insert(models.Analysis)
        .values(
            from_artifact_id=from_id,
            to_artifact_id=to_id,
            ruleset_version=ruleset_version,
            status="failed",
            error=reason,
            finished_at=func.now(),
        )
        .on_conflict_do_update(
            index_elements=["from_artifact_id", "to_artifact_id", "ruleset_version"],
            set_={"status": "failed", "error": reason, "finished_at": func.now(), "report": None, "step": None},
        )
        .returning(models.Analysis.id)
    )
    analysis_id = int(session.execute(stmt).scalar_one())
    session.execute(delete(models.Signal).where(models.Signal.analysis_id == analysis_id))
    return analysis_id


def mark_step(session: Session, from_id: int, to_id: int, ruleset_version: str, step: str) -> None:
    """Record that a pair's analysis is running and which step it is on, and commit so readers see it."""
    stmt = (
        insert(models.Analysis)
        .values(
            from_artifact_id=from_id, to_artifact_id=to_id, ruleset_version=ruleset_version, status="running", step=step
        )
        .on_conflict_do_update(
            index_elements=["from_artifact_id", "to_artifact_id", "ruleset_version"],
            set_={"status": "running", "step": step, "error": None},
            where=models.Analysis.status != "done",
        )
    )
    session.execute(stmt)
    session.commit()


def requeue_failed(session: Session, analysis_id: int) -> None:
    """Turn a failed analysis back into a pending one before it is queued again."""
    session.execute(
        update(models.Analysis)
        .where(models.Analysis.id == analysis_id, models.Analysis.status == "failed")
        .values(status="pending", error=None, step=None, finished_at=None)
    )
    session.commit()
