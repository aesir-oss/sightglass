"""Tables for phase 1: packages, releases, artifacts, provenance, files, sources, analyses and signals.

Every change here needs an Alembic migration in ``sightglass/db/migrations/versions``.
"""

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

ECOSYSTEMS = ("pypi", "conda", "npm")
ARTIFACT_KINDS = ("wheel", "sdist", "conda")
ANALYSIS_STATUSES = ("pending", "running", "done", "failed")
SIGNAL_LEVELS = ("high", "check", "note", "clean")
SOURCE_ORIGINS = ("attestation", "tag")
PROVENANCE_STATUSES = ("unknown", "absent", "present")

SHA256_RE = "^[0-9a-f]{64}$"
GIT_COMMIT_RE = "^[0-9a-f]{40}([0-9a-f]{24})?$"


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    """Declarative base with stable constraint names for migrations."""

    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
        datetime: DateTime(timezone=True),
    }


class Package(Base):
    """A package in one ecosystem, keyed by its normalized name."""

    __tablename__ = "package"
    __table_args__ = (
        UniqueConstraint("ecosystem", "name"),
        CheckConstraint(_one_of("ecosystem", ECOSYSTEMS), name="ecosystem"),
        CheckConstraint(
            "ecosystem <> 'pypi' OR name = lower(regexp_replace(name, '[-_.]+', '-', 'g'))", name="pep503_name"
        ),
        CheckConstraint("name = lower(name) AND name <> ''", name="lowercase_name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ecosystem: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    releases: Mapped[list[Release]] = relationship(back_populates="package")


class Release(Base):
    """One version of a package."""

    __tablename__ = "release"
    __table_args__ = (UniqueConstraint("package_id", "version"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    package_id: Mapped[int] = mapped_column(ForeignKey("package.id", ondelete="CASCADE"))
    version: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime | None]
    yanked: Mapped[bool] = mapped_column(server_default="false")
    yanked_reason: Mapped[str | None] = mapped_column(Text)

    package: Mapped[Package] = relationship(back_populates="releases")
    artifacts: Mapped[list[Artifact]] = relationship(back_populates="release")


class Artifact(Base):
    """A file published for a release: a wheel, an sdist or a conda package."""

    __tablename__ = "artifact"
    __table_args__ = (
        UniqueConstraint("release_id", "filename"),
        Index(None, "sha256"),
        CheckConstraint(_one_of("kind", ARTIFACT_KINDS), name="kind"),
        CheckConstraint(f"sha256 ~ '{SHA256_RE}'", name="sha256_hex"),
        CheckConstraint("size >= 0", name="size_nonnegative"),
        CheckConstraint(_one_of("provenance_status", PROVENANCE_STATUSES), name="provenance_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("release.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(BigInteger)
    uploaded_at: Mapped[datetime | None]
    requires_python: Mapped[str | None] = mapped_column(Text)
    # Whether PyPI has PEP 740 attestations for this file: unknown until checked, then absent or present.
    provenance_status: Mapped[str] = mapped_column(Text, server_default="unknown")

    release: Mapped[Release] = relationship(back_populates="artifacts")


class Attestation(Base):
    """A PEP 740 attestation for an artifact, with the claims from its signing certificate.

    ``verified`` means Sightglass verified the Sigstore bundle itself. PyPI already verifies attestations on upload.
    """

    __tablename__ = "attestation"
    __table_args__ = (
        Index(None, "artifact_id"),
        CheckConstraint(f"source_commit IS NULL OR source_commit ~ '{GIT_COMMIT_RE}'", name="source_commit_hex"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("artifact.id", ondelete="CASCADE"))
    publisher_kind: Mapped[str] = mapped_column(Text)
    repository: Mapped[str | None] = mapped_column(Text)
    workflow: Mapped[str | None] = mapped_column(Text)
    environment: Mapped[str | None] = mapped_column(Text)
    service_account_email: Mapped[str | None] = mapped_column(Text)
    source_commit: Mapped[str | None] = mapped_column(String(64))
    source_ref: Mapped[str | None] = mapped_column(Text)
    runner_environment: Mapped[str | None] = mapped_column(Text)
    build_trigger: Mapped[str | None] = mapped_column(Text)
    run_url: Mapped[str | None] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(server_default="false")
    bundle: Mapped[dict[str, Any]]
    fetched_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Blob(Base):
    """File content stored once by hash. ``storage_key`` is null for content too large to keep."""

    __tablename__ = "blob"
    __table_args__ = (
        CheckConstraint(f"sha256 ~ '{SHA256_RE}'", name="sha256_hex"),
        CheckConstraint("size >= 0", name="size_nonnegative"),
    )

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    size: Mapped[int] = mapped_column(BigInteger)
    storage_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class File(Base):
    """A file inside an artifact or a source snapshot archive."""

    __tablename__ = "file"
    __table_args__ = (
        UniqueConstraint("artifact_id", "path"),
        UniqueConstraint("source_snapshot_id", "path"),
        Index(None, "sha256"),
        CheckConstraint("num_nonnulls(artifact_id, source_snapshot_id) = 1", name="one_owner"),
        CheckConstraint("size >= 0", name="size_nonnegative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    artifact_id: Mapped[int | None] = mapped_column(ForeignKey("artifact.id", ondelete="CASCADE"))
    source_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("source_snapshot.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(ForeignKey("blob.sha256"))
    size: Mapped[int] = mapped_column(BigInteger)
    file_type: Mapped[str] = mapped_column(Text)


class SourceSnapshot(Base):
    """A repository archive at one commit, found through an attestation or a tag."""

    __tablename__ = "source_snapshot"
    __table_args__ = (
        UniqueConstraint("package_id", "repository", "commit"),
        CheckConstraint(f"commit ~ '{GIT_COMMIT_RE}'", name="commit_hex"),
        CheckConstraint(f"archive_sha256 ~ '{SHA256_RE}'", name="archive_sha256_hex"),
        CheckConstraint(_one_of("origin", SOURCE_ORIGINS), name="origin"),
        CheckConstraint("origin <> 'tag' OR (ref IS NOT NULL AND tag_pattern IS NOT NULL)", name="tag_details"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    package_id: Mapped[int] = mapped_column(ForeignKey("package.id", ondelete="CASCADE"))
    repository: Mapped[str] = mapped_column(Text)
    ref: Mapped[str | None] = mapped_column(Text)
    commit: Mapped[str] = mapped_column(String(64))
    archive_sha256: Mapped[str] = mapped_column(String(64))
    origin: Mapped[str] = mapped_column(Text)
    tag_pattern: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Analysis(Base):
    """A comparison of two artifacts under one rule-set version."""

    __tablename__ = "analysis"
    __table_args__ = (
        UniqueConstraint("from_artifact_id", "to_artifact_id", "ruleset_version"),
        Index(None, "to_artifact_id"),
        CheckConstraint(_one_of("status", ANALYSIS_STATUSES), name="status"),
        CheckConstraint("status <> 'failed' OR error IS NOT NULL", name="failed_has_error"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    from_artifact_id: Mapped[int] = mapped_column(ForeignKey("artifact.id", ondelete="CASCADE"))
    to_artifact_id: Mapped[int] = mapped_column(ForeignKey("artifact.id", ondelete="CASCADE"))
    ruleset_version: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]
    # What the page shows besides signals: file pairs, the source check and release facts (sightglass.worker.report).
    # SQL NULL when there is no report (not JSON null), so queries can tell.
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    # The pipeline step a running analysis is on (sightglass.worker.pipeline.STEPS), for the pending page.
    step: Mapped[str | None] = mapped_column(Text)

    signals: Mapped[list[Signal]] = relationship(back_populates="analysis", passive_deletes=True)


class Signal(Base):
    """One fact a rule reported for an analysis, with its evidence."""

    __tablename__ = "signal"
    __table_args__ = (
        Index(None, "analysis_id"),
        CheckConstraint(_one_of("level", SIGNAL_LEVELS), name="level"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analysis.id", ondelete="CASCADE"))
    rule_id: Mapped[str] = mapped_column(Text)
    level: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]]

    analysis: Mapped[Analysis] = relationship(back_populates="signals")


class OwnershipSnapshot(Base):
    """The owners and maintainers an index listed for a package at one point in time."""

    __tablename__ = "ownership_snapshot"
    __table_args__ = (Index(None, "package_id", "seen_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    package_id: Mapped[int] = mapped_column(ForeignKey("package.id", ondelete="CASCADE"))
    seen_at: Mapped[datetime] = mapped_column(server_default=func.now())
    organization: Mapped[str | None] = mapped_column(Text)
    roles: Mapped[list[Any]]
