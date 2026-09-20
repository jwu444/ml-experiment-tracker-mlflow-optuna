"""add the experiments parent and backfill it

Revision ID: 747b57a1d7a5
Revises: 019c2ddeec73
Create Date: 2026-08-22 00:00:00.000000

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "747b57a1d7a5"
down_revision: str | None = "019c2ddeec73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "experiments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False, server_default=""),
        sa.Column("dataset_id", sa.String(), nullable=True),
        sa.Column("dataset_version", sa.String(), nullable=True),
        sa.Column("target_column", sa.String(), nullable=False, server_default=""),
        sa.Column("task_type", sa.String(32), nullable=False, server_default="regression"),
        sa.Column("primary_metric", sa.String(32), nullable=False, server_default="rmse"),
        sa.Column("metric_direction", sa.String(16), nullable=False, server_default="minimize"),
        sa.Column("mlflow_experiment_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["dataset_id"], ["app.datasets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        schema="app",
    )
    op.create_index("ix_app_experiments_dataset_id", "experiments", ["dataset_id"], schema="app")

    op.add_column("runs", sa.Column("experiment_id", sa.String(), nullable=True), schema="app")
    op.create_index("ix_app_runs_experiment_id", "runs", ["experiment_id"], schema="app")
    # batch_alter_table rather than a bare op.create_foreign_key: SQLite has no
    # ALTER TABLE ADD CONSTRAINT, so adding a foreign key after the fact requires
    # its copy-and-move batch strategy. On Postgres (and everywhere batch mode
    # isn't required) this still emits a plain ALTER TABLE ADD CONSTRAINT — batch
    # mode is a single dialect-abstracting Alembic API, not a dialect branch.
    with op.batch_alter_table("runs", schema="app") as batch_op:
        batch_op.create_foreign_key(
            "fk_runs_experiment_id",
            "experiments",
            ["experiment_id"],
            ["id"],
            referent_schema="app",
            ondelete="CASCADE",
        )

    _backfill()


def _backfill() -> None:
    """One experiment per distinct (dataset_id, task_type) among existing runs.

    Grouping by dataset is not arbitrary: on the live database the 33 rows split
    exactly 25 / 8 into two coherent investigations (design §1.4). `objective`
    is left empty on purpose.

    The WHERE clauses below branch on whether `dataset_id` is `None` in Python,
    not in SQL text — `IS NOT DISTINCT FROM` is Postgres-only, and SQLite (the
    test backend) has no equivalent operator. Branching per group and using a
    plain `= :d` / `IS NULL` clause gets identical grouping semantics (NULL
    dataset_id rows still land in one shared group, since `groups` already
    de-duplicates on the paired value) without any dialect check in the SQL
    itself.
    """
    conn = op.get_bind()
    mlflow_present = _has_mlflow_schema(conn)
    groups = conn.execute(
        sa.text(
            "SELECT DISTINCT r.dataset_id, r.task_type FROM app.runs r "
            "WHERE r.experiment_id IS NULL"
        )
    ).all()
    # One dataset can yield several groups (a regression and a classification
    # over the same file). Naming both after the dataset alone would produce two
    # experiments called "a" — and since `name` is what MLflow resolves an
    # experiment by, both would file their runs into the SAME MLflow experiment
    # while looking like separate investigations here.
    split = {d for d, _ in groups if sum(1 for o, _ in groups if o == d) > 1}
    used: set[str] = set()
    for dataset_id, task_type in groups:
        name = (
            conn.execute(
                sa.text("SELECT name FROM app.datasets WHERE id = :d"), {"d": dataset_id}
            ).scalar()
            or "ungrouped"
        )
        name = name.removesuffix(".csv") + (f" ({task_type})" if dataset_id in split else "")
        # Two dataset rows can carry the same filename — dedup is on content
        # hash, so re-uploading a changed "a.csv" is a second, legal row. The
        # per-dataset suffix above does not separate those, and MLflow would
        # merge them just the same, so uniqueness is enforced globally here.
        if name in used:
            name = f"{name} ({len(used) + 1})"
        used.add(name)
        targets = (
            [
                t
                for (t,) in conn.execute(
                    sa.text(
                        "SELECT DISTINCT p.value FROM app.runs r "
                        "JOIN mlflow.params p ON p.run_uuid = r.mlflow_run_id "
                        "WHERE p.key = 'target_column' "
                        + (
                            "AND r.dataset_id IS NULL "
                            if dataset_id is None
                            else "AND r.dataset_id = :d "
                        )
                        + "AND r.task_type = :t"
                    ),
                    {"d": dataset_id, "t": task_type},
                ).all()
            ]
            if mlflow_present
            else []
        )
        if len(targets) > 1:
            # Disagreement means the grouping assumption is wrong for this data.
            # Picking one would produce an experiment whose runs are NOT
            # comparable — the exact failure this design prevents (§5.1).
            raise RuntimeError(
                f"runs for dataset {dataset_id!r} disagree on target_column: {sorted(targets)}; "
                "group them by hand before migrating"
            )
        if mlflow_present and not targets:
            # The params table is right there and has nothing to say about this
            # group. Falling through to "" would mint an investigation that can
            # neither launch a run (train/tune need a target) nor be repaired
            # without one, and nothing about the row would look wrong on the
            # leaderboard. Fail while the operator still has the runs in front of
            # them and the answer is still recoverable.
            raise RuntimeError(
                f"runs for dataset {dataset_id!r} ({task_type}) have no logged "
                "target_column; set it by hand before migrating"
            )
        # Promote the runs' content-hash pin to the parent before the contract
        # migration drops `runs.dataset_version`. Every run in this group is over
        # the same dataset row, and a dataset is immutable (deduplicated by
        # content hash, D5), so the group's values agree and picking any non-NULL
        # one is lossless. Omitting this looks harmless — the column is nullable
        # and nothing errors — but it silently discards the pin on 33 live runs
        # and the downgrade restores NULL, so the round trip is not reversible.
        version = conn.execute(
            sa.text(
                "SELECT r.dataset_version FROM app.runs r "
                "WHERE r.experiment_id IS NULL AND r.dataset_version IS NOT NULL "
                "AND r.task_type = :t "
                + ("AND r.dataset_id IS NULL" if dataset_id is None else "AND r.dataset_id = :d")
            ),
            {"d": dataset_id, "t": task_type},
        ).scalar()
        exp_id = str(uuid.uuid4())
        conn.execute(
            sa.text(
                "INSERT INTO app.experiments "
                "(id, name, objective, dataset_id, dataset_version, target_column, task_type, "
                " primary_metric, metric_direction) "
                "VALUES (:i, :n, '', :d, :dv, :tc, :t, :pm, :md)"
            ),
            {
                "i": exp_id,
                "n": name,
                "d": dataset_id,
                "dv": version,
                # Only reachable with no MLflow schema to read, where the target
                # is genuinely unknowable rather than merely unread. The empty
                # value is therefore honest — and PATCH /experiments/{id} accepts
                # `target_column` while it stays empty, so it is a gap to fill and
                # not a dead end.
                "tc": targets[0] if targets else "",
                "t": task_type,
                "pm": "rmse" if task_type == "regression" else "f1_macro",
                "md": "minimize" if task_type == "regression" else "maximize",
            },
        )
        where_dataset = "dataset_id IS NULL" if dataset_id is None else "dataset_id = :d"
        conn.execute(
            sa.text(
                "UPDATE app.runs SET experiment_id = :i "
                "WHERE experiment_id IS NULL AND task_type = :t "
                f"AND {where_dataset}"
            ),
            {"i": exp_id, "d": dataset_id, "t": task_type},
        )


def _has_mlflow_schema(conn: sa.Connection) -> bool:
    """Whether MLflow's params table is reachable — and so whether `target_column`
    is knowable at all.

    Probed through the inspector rather than `to_regclass`, which is Postgres-only.
    The dialect-agnostic form is what lets the migration test ATTACH an `mlflow`
    schema on SQLite and exercise the target backfill for real: under the old
    Postgres-gated probe this returned False on every test run, so the branch below
    it was executed by nothing, anywhere.
    """
    return sa.inspect(conn).has_table("params", schema="mlflow")


def downgrade() -> None:
    # Lossy: `objective` and any human-authored experiment metadata have nowhere
    # to go. Documented here rather than silently discarded.
    # batch_alter_table for the same reason as in upgrade(): dropping a foreign
    # key constraint is an ALTER TABLE SQLite cannot do directly.
    with op.batch_alter_table("runs", schema="app") as batch_op:
        batch_op.drop_constraint("fk_runs_experiment_id", type_="foreignkey")
        batch_op.drop_index("ix_app_runs_experiment_id")
        batch_op.drop_column("experiment_id")
    op.drop_index("ix_app_experiments_dataset_id", "experiments", schema="app")
    op.drop_table("experiments", schema="app")
