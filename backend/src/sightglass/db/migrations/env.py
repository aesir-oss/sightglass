"""Alembic environment: runs migrations online against SIGHTGLASS_DATABASE_URL or the configured URL."""

from alembic import context

from sightglass.db.engine import make_engine
from sightglass.db.models import Base


def run_migrations_online() -> None:
    """Run migrations on a live connection."""
    url = context.config.get_main_option("sqlalchemy.url")
    engine = make_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_server_default=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("offline migrations aren't supported; run against a database")
run_migrations_online()
