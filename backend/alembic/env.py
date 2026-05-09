"""
Alembic Environment Configuration — PrescpHealth Backend.

This file configures how Alembic runs migrations. It supports both:
- Online mode: Connects to a live database and runs migrations directly
- Offline mode: Generates SQL scripts without a database connection

Key design decisions:
- Uses SYNC database URL (Alembic's runner is synchronous)
- Imports all models via Base.metadata so autogenerate works
- Overrides sqlalchemy.url from app settings (not hardcoded in alembic.ini)
"""

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# ---------------------------------------------------------------------------
# Add the backend directory to Python path so we can import app modules.
# This is necessary because Alembic runs from the backend/ directory.
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.core.base_model import Base  # noqa: E402

# ---------------------------------------------------------------------------
# Alembic Config object — provides access to alembic.ini values
# ---------------------------------------------------------------------------
config = context.config

# Set the database URL from our app settings (overrides alembic.ini placeholder)
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url_sync)

# Set up Python logging from alembic.ini [loggers] section
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Target metadata for autogenerate support.
# Import all models here so Alembic can detect schema changes.
# As new modules are added, their models should be imported here.
# ---------------------------------------------------------------------------
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode — generates SQL without DB connection.

    Useful for:
    - Generating migration SQL for review before applying
    - Environments where direct DB access isn't available
    - CI/CD pipelines that need to validate migration scripts
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode — connects to DB and applies directly.

    Creates a connection from the engine config, then runs each migration
    within a transaction. If any migration fails, the transaction is rolled
    back (no partial migrations).
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


# ---------------------------------------------------------------------------
# Entry point — Alembic calls this to determine which mode to run
# ---------------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
