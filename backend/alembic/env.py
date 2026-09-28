from __future__ import annotations

import logging
import os
from logging.config import fileConfig

from alembic.script import ScriptDirectory
from sqlalchemy import (
    Column,
    Connection,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    engine_from_config,
    inspect,
    pool,
)

from alembic import context
from andromeda.infrastructure.config import Settings, redact_database_url
from andromeda.infrastructure.database import models as _models  # noqa: F401
from andromeda.infrastructure.database.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _restore_application_loggers() -> None:
    """Alembic's fileConfig must not silently disable application diagnostics."""
    for name, candidate in logging.Logger.manager.loggerDict.items():
        if (name == "andromeda" or name.startswith("andromeda.")) and isinstance(
            candidate, logging.Logger
        ):
            candidate.disabled = False


_restore_application_loggers()

target_metadata = Base.metadata
logger = logging.getLogger("andromeda.alembic")
_MIN_VERSION_COLUMN_LENGTH = 64


def _configured_database_url() -> str:
    environment_url = os.environ.get("ANDROMEDA_DATABASE_URL") or os.environ.get("BMSTU_DATABASE_URL")
    configured_url = environment_url or config.get_main_option("sqlalchemy.url") or None
    settings = Settings.from_environment(configured_url)
    database_url = settings.database_url
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    logger.info(
        "migration_target environment=%s dialect_target=%s",
        settings.environment,
        redact_database_url(database_url),
    )
    return database_url


def _required_revision_storage_length() -> int:
    """Size Alembic's bookkeeping column for every revision in this checkout."""
    revisions = ScriptDirectory.from_config(config).walk_revisions()
    longest_revision = max((len(revision.revision) for revision in revisions), default=0)
    return max(_MIN_VERSION_COLUMN_LENGTH, longest_revision)


def _prepare_alembic_version_table(connection: Connection) -> None:
    """Create/widen Alembic's internal table before long revision IDs are stored.

    Alembic defaults this column to VARCHAR(32). PostgreSQL enforces that limit,
    while SQLite does not, so descriptive revision IDs can otherwise pass the
    SQLite migration suite and fail on a real PostgreSQL upgrade.
    """
    required_length = _required_revision_storage_length()
    version_table = Table(
        "alembic_version",
        MetaData(),
        Column("version_num", String(required_length), nullable=False),
        PrimaryKeyConstraint("version_num", name="alembic_version_pkc"),
    )

    try:
        version_table.create(connection, checkfirst=True)
        logger.debug(
            "migration_version_table_checked dialect=%s required_length=%d",
            connection.dialect.name,
            required_length,
        )

        if connection.dialect.name == "postgresql":
            version_column = next(
                column
                for column in inspect(connection).get_columns("alembic_version")
                if column["name"] == "version_num"
            )
            existing_length = getattr(version_column["type"], "length", None)
            if existing_length is not None and existing_length < required_length:
                logger.info(
                    "migration_version_column_widen dialect=postgresql old_length=%d new_length=%d",
                    existing_length,
                    required_length,
                )
                connection.exec_driver_sql(
                    "ALTER TABLE alembic_version ALTER COLUMN version_num "
                    f"TYPE VARCHAR({required_length})"
                )

        # Keep this infrastructure bootstrap outside Alembic's migration
        # transaction so the configured migration context starts cleanly.
        connection.commit()
    except Exception:
        logger.exception(
            "migration_version_table_prepare_failed dialect=%s",
            connection.dialect.name,
        )
        raise


def run_migrations_offline() -> None:
    url = _configured_database_url()
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    _configured_database_url()
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _prepare_alembic_version_table(connection)
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
