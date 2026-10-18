"""Add the review and review_change tables for pull request lockfile reviews.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-17 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this revision."""
    op.create_table(
        "review",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("repository", sa.Text(), nullable=False),
        sa.Column("pull_number", sa.Integer(), nullable=False),
        sa.Column("base_sha", sa.String(length=64), nullable=False),
        sa.Column("head_sha", sa.String(length=64), nullable=False),
        sa.Column("lockfile_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("base_sha ~ '^[0-9a-f]{40}([0-9a-f]{24})?$'", name=op.f("ck_review_base_sha_hex")),
        sa.CheckConstraint("head_sha ~ '^[0-9a-f]{40}([0-9a-f]{24})?$'", name=op.f("ck_review_head_sha_hex")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review")),
        sa.UniqueConstraint(
            "repository",
            "pull_number",
            "head_sha",
            "lockfile_path",
            name=op.f("uq_review_repository_pull_number_head_sha_lockfile_path"),
        ),
    )
    op.create_table(
        "review_change",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("review_id", sa.BigInteger(), nullable=False),
        sa.Column("ecosystem", sa.Text(), nullable=False),
        sa.Column("package", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("from_version", sa.Text(), nullable=True),
        sa.Column("to_version", sa.Text(), nullable=True),
        sa.Column("environments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("platforms", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("only_some_platforms", sa.Boolean(), nullable=False),
        sa.Column("path", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("ecosystem IN ('conda', 'pypi')", name=op.f("ck_review_change_ecosystem")),
        sa.CheckConstraint("kind IN ('added', 'removed', 'changed')", name=op.f("ck_review_change_kind")),
        sa.CheckConstraint(
            "(kind = 'added' AND from_version IS NULL AND to_version IS NOT NULL)"
            " OR (kind = 'removed' AND from_version IS NOT NULL AND to_version IS NULL)"
            " OR (kind = 'changed' AND from_version IS NOT NULL AND to_version IS NOT NULL)",
            name=op.f("ck_review_change_versions_match_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["review_id"], ["review.id"], name=op.f("fk_review_change_review_id_review"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_change")),
    )
    op.create_index(op.f("ix_review_change_review_id"), "review_change", ["review_id"], unique=False)


def downgrade() -> None:
    """Revert this revision."""
    op.drop_index(op.f("ix_review_change_review_id"), table_name="review_change")
    op.drop_table("review_change")
    op.drop_table("review")
