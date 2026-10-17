"""Running the Alembic migrations from code, without ``alembic.ini``."""

from alembic import command
from alembic.config import Config


def alembic_config(url: str) -> Config:
    """An Alembic config for the packaged migrations, pointed at ``url``."""
    config = Config()
    config.set_main_option("script_location", "sightglass.db:migrations")
    config.set_main_option("path_separator", "os")
    config.set_main_option("sqlalchemy.url", url)
    return config


def upgrade(url: str, revision: str = "head") -> None:
    """Migrate the database at ``url`` to ``revision``."""
    command.upgrade(alembic_config(url), revision)
