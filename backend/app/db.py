from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import Base
from app.sqlite_schema import attach_app_schema

engine = create_engine(settings.database_url, future=True)
if engine.dialect.name == "sqlite":
    # SQLite has no schemas, but the models bind their tables to the Postgres
    # `app` schema. attach_app_schema gives SQLite a real "app" schema (a
    # second file next to the main one) rather than rewriting the schema name
    # away, so this engine, Alembic's (env.py), and the test engine
    # (conftest.py) all agree on where "app" tables live for a given
    # database_url — see app/sqlite_schema.py for why.
    engine = attach_app_schema(engine)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

# repo root = .../backend/app/db.py -> parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_migrations() -> None:
    """Bring the database up to the latest Alembic revision."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    # Make script_location absolute so it resolves regardless of the CWD the
    # app was launched from (uvicorn, tests, a cron job, ...).
    cfg.set_main_option("script_location", str(_REPO_ROOT / "backend" / "alembic"))
    command.upgrade(cfg, "head")


def init_db() -> None:
    # Postgres (dev/prod) is managed by Alembic migrations. SQLite — the local
    # default and the test backend — has no schemas and needs no migration
    # history, so create tables directly from the ORM metadata.
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(engine)
    else:
        _run_migrations()


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
