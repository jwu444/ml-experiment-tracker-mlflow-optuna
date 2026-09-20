"""Shared SQLite "app"-schema wiring for env.py, app/db.py, and tests/conftest.py.

SQLite has no schemas. The ORM binds every table to Postgres's `app` schema
(`__table_args__ = {"schema": "app"}`), so something must give SQLite an `app`
schema for that to resolve. This project ATTACHes a second file,
"<main-db-path>-app", under the alias `app`, on every connection — a real
schema/catalog, not schema_translate_map's cosmetic *rewrite* of the schema
name. That matters because several things are not schema_translate_map-aware
at all: Alembic's op.add_column/op.rename_table/create_foreign_key (they
render the literal `schema=` argument via format_table_name, never consulting
the map), and any hand-written SQL text that names "app.<table>" literally
(translate_map only rewrites compiled SQLAlchemy DDL/DML, never text()) — both
of which existing and future migrations use.

All three of Alembic's env.py, app/db.py (the real app engine), and
tests/conftest.py (the test engine) call `attach_app_schema` on their engine
for a SQLite URL, so a database migrated by one of these three and then opened
by another sees the same tables — never a silently empty second file that
nobody attached.
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.engine import Engine


def attach_app_schema(engine: Engine) -> Engine:
    """Register a `connect` listener that ATTACHes "<db-path>-app" as the `app`
    schema on every new DBAPI connection this engine opens.

    Runs at the raw DBAPI level (before SQLAlchemy wraps the connection and
    before its 2.0 "autobegin" transaction semantics can kick in), so — unlike
    issuing `ATTACH` through a SQLAlchemy `Connection.execute()` — no explicit
    commit is needed to avoid colliding with Alembic's own
    `context.begin_transaction()`.

    In-memory SQLite (`:memory:`) is rejected rather than silently given a
    fresh, empty, per-connection `app` schema: with a pool that hands out more
    than one physical connection (e.g. NullPool), tables written through one
    connection would be invisible — not erroring, just gone — on the next.
    """
    db_path = engine.url.database
    if not db_path or db_path == ":memory:":
        raise ValueError(
            "attach_app_schema does not support in-memory SQLite: each new "
            "connection would ATTACH its own empty, anonymous `app` schema, so "
            "tables written on one connection are invisible on the next. Use a "
            "file-backed sqlite:/// URL instead."
        )
    # ATTACH takes no bound parameters, so the path is interpolated — doubling
    # any single quote is what keeps a directory named "justin's dev" from
    # producing a syntax error rather than an attached database. Not a security
    # boundary (the path comes from our own DATABASE_URL, not a request), just
    # correctness for paths a developer may plausibly have.
    app_path = f"{db_path}-app".replace("'", "''")
    # The `mlflow` schema is attached too, and unconditionally. On Postgres it is
    # a real schema owned by the tracking store (Project 2 D4) that migrations
    # read across — `747b57a1d7a5` joins `mlflow.params` to recover each run's
    # target column. Without an attachable `mlflow` on SQLite that join is not
    # merely untested, it is unnameable, so the branch guarding it was dead on
    # every SQLite run. ATTACH creates the file if absent, and an EMPTY mlflow
    # schema is indistinguishable from no tracking store to every caller, because
    # they all probe for the `params` TABLE rather than for the schema.
    mlflow_path = f"{db_path}-mlflow".replace("'", "''")

    @event.listens_for(engine, "connect")
    def _attach(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
        dbapi_connection.execute(f"ATTACH DATABASE '{app_path}' AS app")
        dbapi_connection.execute(f"ATTACH DATABASE '{mlflow_path}' AS mlflow")

    return engine
