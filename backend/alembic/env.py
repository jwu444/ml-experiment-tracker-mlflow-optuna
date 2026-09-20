"""Alembic environment — wired to the app's Settings and SQLAlchemy metadata.

The URL comes from ``app.config.settings.database_url`` (DATABASE_URL / .env), so
there is one source of truth. Models live in the ``app`` Postgres schema; on
SQLite that schema is a real ATTACHed database (see app/sqlite_schema.py),
using the exact same helper app/db.py and tests/conftest.py use for the same
URL — so a database migrated here and then opened by the app (or inspected by
a test) always sees the same tables, never a second, silently empty file.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from app.config import settings
from app.models import Base
from app.sqlite_schema import attach_app_schema
from sqlalchemy import engine_from_config, pool

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

# disable_existing_loggers=False so running migrations at app startup does not
# tear down uvicorn's already-configured loggers.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata
_is_sqlite = settings.database_url.startswith("sqlite")

# MLflow owns the `mlflow` schema and migrates it itself (design D4). With
# include_schemas=True, autogenerate would otherwise see MLflow's tables as
# tables we no longer declare and emit a drop for each one. Restrict comparison
# to our own schema.
_OWNED_SCHEMAS = {"app"}


def app_schema_only(object_, name, type_, reflected, compare_to) -> bool:  # type: ignore[no-untyped-def]
    if type_ == "table":
        return object_.schema in _OWNED_SCHEMAS
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_object=app_schema_only,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    if _is_sqlite:
        attach_app_schema(connectable)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_object=app_schema_only,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
