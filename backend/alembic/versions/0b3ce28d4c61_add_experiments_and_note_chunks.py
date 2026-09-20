"""add experiments and note chunks

Revision ID: 0b3ce28d4c61
Revises: 342d02b2a507
Create Date: 2026-08-09 18:21:50.104009

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = '0b3ce28d4c61'
down_revision: str | None = '342d02b2a507'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen snapshot of app.models.EMBEDDING_DIM at the time of this revision.
# Migrations must not import from the app, or a later model change would
# retroactively rewrite history.
EMBEDDING_DIM = 512


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    # pgvector ships as an extension; the VECTOR type does not exist until it is
    # created. No-op on SQLite, which uses the JSON variant of the column.
    if _is_postgres():
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "experiments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("mlflow_run_id", sa.String(), nullable=False),
        # D5: nullable FK. SET NULL rather than CASCADE — deleting a dataset must
        # not erase the experiment history that referenced it.
        sa.Column("dataset_id", sa.String(), nullable=True),
        sa.Column("dataset_version", sa.String(), nullable=True),
        sa.Column("model_type", sa.String(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["dataset_id"], ["app.datasets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        schema="app",
    )
    op.create_index(
        "ix_app_experiments_mlflow_run_id", "experiments", ["mlflow_run_id"], schema="app"
    )
    op.create_index("ix_app_experiments_dataset_id", "experiments", ["dataset_id"], schema="app")

    op.create_table(
        "experiment_note_chunks",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("experiment_id", sa.String(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column(
            "embedding",
            Vector(EMBEDDING_DIM).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id"], ["app.experiments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "experiment_id", "chunk_index", name="uq_note_chunks_experiment_id_chunk_index"
        ),
        schema="app",
    )
    op.create_index(
        "ix_app_experiment_note_chunks_experiment_id",
        "experiment_note_chunks",
        ["experiment_id"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_app_experiment_note_chunks_experiment_id",
        table_name="experiment_note_chunks",
        schema="app",
    )
    op.drop_table("experiment_note_chunks", schema="app")
    op.drop_index("ix_app_experiments_dataset_id", table_name="experiments", schema="app")
    op.drop_index("ix_app_experiments_mlflow_run_id", table_name="experiments", schema="app")
    op.drop_table("experiments", schema="app")
    # The vector extension is intentionally NOT dropped: other objects may use
    # it, and re-creating it is free.
