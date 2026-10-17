"""Record the pipeline step a running analysis is on.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-17 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this revision."""
    op.add_column("analysis", sa.Column("step", sa.Text(), nullable=True))


def downgrade() -> None:
    """Revert this revision."""
    op.drop_column("analysis", "step")
