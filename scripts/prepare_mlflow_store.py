"""Prepare the MLflow tracking store, then print the URI the app should use.

Locally this is `make mlflow-init`: CREATE SCHEMA mlflow, then `mlflow db
upgrade` against a URI carrying `?options=-csearch_path=mlflow`. On Render
neither half happens by itself — `fromDatabase` hands the service a bare
connection string, and free-tier services do not support a pre-deploy command,
so there is nowhere but container start to do it.

Both halves matter and they fail differently. Without the schema, `mlflow db
upgrade` errors outright. With the schema but without the search_path, MLflow
succeeds and quietly builds its ~59 tables in `public` — a working deploy that
contradicts D4 and does not match any local database, discoverable only by
going looking.

Printing the normalized URI rather than exporting it keeps one definition of
the convention: the entrypoint evaluates this script's stdout into the
environment uvicorn inherits, so preparation and use cannot disagree.

Idempotent by construction — CREATE SCHEMA IF NOT EXISTS, and `mlflow db
upgrade` is Alembic, so a redeploy against a current store is a no-op. It is
safe to run on every container start, which on free tier is also every wake
from idle.
"""

from __future__ import annotations

import os
import subprocess
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MLFLOW_SCHEMA = "mlflow"
_SEARCH_PATH = f"-csearch_path={MLFLOW_SCHEMA}"


def normalize_uri(raw: str) -> str:
    """Attach the MLflow search_path to a bare Postgres URI, preserving the rest.

    An `options` value already present is left alone: an operator who set one
    deliberately knows something this script does not, and silently overwriting
    it would be the same class of failure as not setting it at all.
    """
    parts = urlsplit(raw)
    if not parts.scheme.startswith("postgres"):
        return raw
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.setdefault("options", _SEARCH_PATH)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def main() -> int:
    raw = os.environ.get("MLFLOW_TRACKING_URI", "").strip()
    if not raw:
        # No tracking store configured — MLflow falls back to its local default.
        # Nothing to prepare, and nothing to print.
        return 0

    uri = normalize_uri(raw)

    if uri.startswith("postgres"):
        import sqlalchemy as sa

        # CREATE SCHEMA needs a connection that is NOT already pinned to the
        # schema it is creating, so this one deliberately uses the raw URI.
        engine = sa.create_engine(raw)
        with engine.begin() as conn:
            conn.execute(sa.text(f"CREATE SCHEMA IF NOT EXISTS {MLFLOW_SCHEMA}"))
        engine.dispose()

    result = subprocess.run(
        ["mlflow", "db", "upgrade", uri],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # stderr, not stdout: stdout is the URI contract with the entrypoint.
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return result.returncode

    print(uri)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
