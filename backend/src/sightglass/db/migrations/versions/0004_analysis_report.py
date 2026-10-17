"""Store each analysis's report: file pairs, source check and release facts.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-17 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this revision."""
    op.add_column("analysis", sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    """Revert this revision."""
    op.drop_column("analysis", "report")
