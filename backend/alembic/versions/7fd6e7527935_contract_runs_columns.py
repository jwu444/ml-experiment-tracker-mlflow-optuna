"""tighten experiment_id and drop the inherited run columns

Revision ID: 7fd6e7527935
Revises: 747b57a1d7a5
Create Date: 2026-08-22 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7fd6e7527935"
down_revision: str | None = "747b57a1d7a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Task 2's backfill (747b57a1d7a5) assigned every existing row, and
    # ADHOC_EXPERIMENT is gone from the route layer, so nothing can write a
    # NULL by the time this runs.
    orphans = op.get_bind().execute(
        sa.text("SELECT count(*) FROM app.runs WHERE experiment_id IS NULL")
    ).scalar_one()
    if orphans:
        raise RuntimeError(f"{orphans} runs have no experiment_id; migration 2 did not complete")
    # batch_alter_table: SQLite's ALTER TABLE supports neither tightening a
    # column's nullability nor dropping a column directly, so both go through
    # batch mode's copy-and-move strategy — the same precedent 747b57a1d7a5
    # used for adding the FK. On Postgres this still emits plain ALTER TABLE
    # statements; batch mode is a single dialect-abstracting Alembic API, not a
    # dialect branch.
    #
    # Drop this BEFORE the column it indexes. 019c2ddeec73 re-pointed it at the
    # renamed table, and batch mode recreates every index it reflects — so
    # leaving it here makes the rebuild try to index a column this migration is
    # dropping ("no such column: dataset_id").
    op.drop_index("ix_app_runs_dataset_id", table_name="runs", schema="app")
    with op.batch_alter_table("runs", schema="app") as batch_op:
        batch_op.alter_column("experiment_id", nullable=False, existing_type=sa.String())
        # These now live on the parent (D34). Dropped last so the orphan check
        # above could still read dataset_id if it needed to.
        batch_op.drop_column("dataset_id")
        batch_op.drop_column("dataset_version")
        batch_op.drop_column("task_type")


def downgrade() -> None:
    with op.batch_alter_table("runs", schema="app") as batch_op:
        batch_op.add_column(sa.Column("dataset_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("dataset_version", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("task_type", sa.String(32), nullable=False, server_default="regression")
        )
    # Lossy in one sense only: a run's dataset_id/task_type are recovered
    # exactly from its parent, since that is where they came from originally.
    op.execute(
        "UPDATE app.runs SET dataset_id = e.dataset_id, dataset_version = e.dataset_version, "
        "task_type = e.task_type FROM app.experiments e WHERE e.id = app.runs.experiment_id"
    )
    with op.batch_alter_table("runs", schema="app") as batch_op:
        batch_op.alter_column("experiment_id", nullable=True, existing_type=sa.String())
    # Restore the index upgrade() dropped, so downgrade lands on the same shape
    # 019c2ddeec73 left behind rather than one index short of it.
    op.create_index("ix_app_runs_dataset_id", "runs", ["dataset_id"], schema="app")
