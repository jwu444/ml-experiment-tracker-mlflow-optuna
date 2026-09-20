"""rename experiments to runs

Revision ID: 019c2ddeec73
Revises: 9bb02e2c7392
Create Date: 2026-08-22 13:04:58.560385

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '019c2ddeec73'
down_revision: str | None = '9bb02e2c7392'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (old name, new name, indexed column). Renaming a table does NOT rename its
# indexes on either Postgres or SQLite, and index names live in the SCHEMA's
# namespace rather than the table's — so the indexes this table carries would
# still be called ix_app_experiments_* afterwards, and the new parent
# `experiments` table created by 747b57a1d7a5 collides with them on CREATE
# INDEX. Re-point them at the new table name here, in the same migration that
# renames the table.
_INDEXES = (
    ("ix_app_experiments_mlflow_run_id", "ix_app_runs_mlflow_run_id", "mlflow_run_id"),
    ("ix_app_experiments_dataset_id", "ix_app_runs_dataset_id", "dataset_id"),
)


def upgrade() -> None:
    # op.rename_table PRESERVES row ids, which is what keeps findings.source_id
    # (source_type='diagnostic') resolving with no data migration — see design
    # §5.2. A drop+create here would silently orphan them.
    op.rename_table("experiments", "runs", schema="app")
    for old, new, column in _INDEXES:
        op.drop_index(old, table_name="runs", schema="app")
        op.create_index(new, "runs", [column], schema="app")
    if op.get_bind().dialect.name == "postgresql":
        # The primary key's backing index is named too, and it is the one
        # object here that only Postgres exposes as renameable — SQLite's
        # implicit rowid PK has no index to collide with.
        op.execute("ALTER INDEX app.experiments_pkey RENAME TO runs_pkey")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER INDEX app.runs_pkey RENAME TO experiments_pkey")
    for old, new, column in _INDEXES:
        op.drop_index(new, table_name="runs", schema="app")
        op.create_index(old, "runs", [column], schema="app")
    op.rename_table("runs", "experiments", schema="app")
