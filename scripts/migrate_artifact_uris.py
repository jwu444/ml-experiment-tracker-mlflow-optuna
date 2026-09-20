"""Re-point MLflow's absolute artifact URIs at object storage (§7.3, D48).

MLflow stores ABSOLUTE artifact URIs in three columns —
mlflow.experiments.artifact_location, mlflow.runs.artifact_uri, and (MLflow
3.x's logged-models layout) mlflow.logged_models.artifact_location — so
syncing mlruns/ to R2 is not sufficient. Those columns still name a local path
that does not exist on Render, and mlflow.sklearn.load_model then fails with a
file-not-found for a file that uploaded successfully. The models themselves
live under logged_models, not under a run's own artifact_uri: routes/runs.py
loads them via `runs:/{run_id}/model`, which MLflow resolves through that
table, so omitting it leaves every trained model unreachable even though the
run's own row rewrote clean.

Raw SQL against MLflow's own schema, deliberately: D4 says never model MLflow
tables in app/models.py. This is a one-shot script, not an ORM change.

Re-running it is safe — rows already under the new root are skipped.
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import create_engine, text


def _under_root(candidate: str, root: str) -> bool:
    # A bare str.startswith would let "./mlruns-backup/..." match root
    # "./mlruns" — a string-prefix match, not a path-prefix match. Require
    # the next character to be a path separator, or an exact match.
    return candidate == root or candidate.startswith(root + "/")


def rewrite_uri(old: str, *, old_root: str, new_root: str) -> str:
    old_root, new_root = old_root.rstrip("/"), new_root.rstrip("/")
    if _under_root(old, new_root):
        return old  # already migrated; the script must be re-runnable
    if _under_root(old, old_root):
        return new_root + old[len(old_root) :]
    # Neither leaving it nor rewriting it is honest: leaving it makes the run
    # unloadable with no error, rewriting it invents a path.
    raise ValueError(f"unexpected artifact root in {old!r}; expected {old_root!r}")


def plan_rewrites(
    rows: list[tuple[str, str]], *, old_root: str, new_root: str
) -> list[tuple[str, str]]:
    plan: list[tuple[str, str]] = []
    for key, uri in rows:
        new = rewrite_uri(uri, old_root=old_root, new_root=new_root)
        if new != uri:
            plan.append((key, new))
    return plan


_TABLES = (
    ("mlflow.experiments", "experiment_id", "artifact_location"),
    ("mlflow.runs", "run_uuid", "artifact_uri"),
    # MLflow 3.x's logged-models layout: this is where the models themselves
    # live (mlruns/models/m-<id>/artifacts). runs.artifact_uri covers a run's
    # other artifacts, but routes/runs.py loads models via `runs:/{run_id}/model`,
    # which MLflow resolves through this table — omitting it leaves every
    # trained model unreachable after the rewrite even though the run rewrote
    # clean.
    ("mlflow.logged_models", "model_id", "artifact_location"),
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-point MLflow artifact URIs")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--old-root", required=True, help="e.g. file:///app/mlruns or ./mlruns")
    parser.add_argument("--new-root", required=True, help="e.g. s3://wavepoint-artifacts/mlruns")
    parser.add_argument("--apply", action="store_true", help="write; otherwise print the plan")
    args = parser.parse_args()

    engine = create_engine(args.database_url)
    with engine.begin() as conn:
        for table, key_col, uri_col in _TABLES:
            rows = [
                (str(k), str(u))
                for k, u in conn.execute(text(f"SELECT {key_col}, {uri_col} FROM {table}"))
                if u is not None
            ]
            plan = plan_rewrites(rows, old_root=args.old_root, new_root=args.new_root)
            print(f"{table}: {len(plan)} of {len(rows)} row(s) to rewrite")
            for key, new in plan:
                print(f"  {key} -> {new}")
                if args.apply:
                    conn.execute(
                        text(f"UPDATE {table} SET {uri_col} = :uri WHERE {key_col} = :key"),
                        {"uri": new, "key": key},
                    )
    print("applied." if args.apply else "dry run; re-run with --apply to write.")


if __name__ == "__main__":
    main()
