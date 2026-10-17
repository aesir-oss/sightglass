"""Add the procrastinate job queue schema (3.10.0).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17 08:00:00.000000
"""

from collections.abc import Sequence
from importlib.resources import files

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "procrastinate_3_10_0.sql"


def _run(sql: str) -> None:
    # On the raw cursor with no parameters, so psycopg leaves `%` alone; it shares Alembic's transaction.
    dbapi = op.get_bind().connection.dbapi_connection
    assert dbapi is not None
    cursor = dbapi.cursor()
    try:
        cursor.execute(sql)
    finally:
        cursor.close()


def upgrade() -> None:
    """Apply this revision."""
    sql = files("sightglass.db.migrations").joinpath("sql", SCHEMA).read_text(encoding="utf-8")
    _run(sql)


def downgrade() -> None:
    """Revert this revision."""
    _run(
        """
        DROP TABLE IF EXISTS procrastinate_events, procrastinate_periodic_defers, procrastinate_jobs,
            procrastinate_workers CASCADE;
        DO $$
        DECLARE r record;
        BEGIN
            FOR r IN SELECT p.oid::regprocedure AS fn FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                     WHERE n.nspname = current_schema() AND p.proname LIKE 'procrastinate\\_%' LOOP
                EXECUTE 'DROP FUNCTION ' || r.fn || ' CASCADE';
            END LOOP;
            FOR r IN SELECT t.typname AS name FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
                     WHERE n.nspname = current_schema() AND t.typname LIKE 'procrastinate\\_%' AND t.typtype IN ('e', 'c')
            LOOP
                EXECUTE 'DROP TYPE ' || quote_ident(r.name) || ' CASCADE';
            END LOOP;
        END $$;
        """
    )
