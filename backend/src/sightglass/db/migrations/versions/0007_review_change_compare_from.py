"""Record which release an added package is analyzed against.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-17 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this revision."""
    op.add_column("review_change", sa.Column("compare_from", sa.Text(), nullable=True))


def downgrade() -> None:
    """Revert this revision."""
    op.drop_column("review_change", "compare_from")
