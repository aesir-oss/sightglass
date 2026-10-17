"""Record whether each artifact's provenance was checked.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17 01:06:07.783011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this revision."""
    op.add_column("artifact", sa.Column("provenance_status", sa.Text(), server_default="unknown", nullable=False))
    # Autogenerate doesn't detect CHECK constraints.
    op.create_check_constraint(
        op.f("ck_artifact_provenance_status"),
        "artifact",
        "provenance_status IN ('unknown', 'absent', 'present')",
    )


def downgrade() -> None:
    """Revert this revision."""
    op.drop_constraint(op.f("ck_artifact_provenance_status"), "artifact", type_="check")
    op.drop_column("artifact", "provenance_status")
