"""The migrations must not lose rows. Every other test builds a fresh database,
so a drop+create migration would pass the whole suite while destroying the 33
production rows (design §5.3). This is the only test that would catch it."""

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.config import settings
from app.sqlite_schema import attach_app_schema

# Resolved from this file's own location, not the process cwd — Config("backend/alembic.ini")
# only works when pytest happens to be invoked from the repo root. Mirrors test_migrations.py.
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(db_url: str) -> Config:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "backend" / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _create_pre_hierarchy_schema(conn: sa.Connection) -> None:
    """Build the app-schema shape as of revision 9bb02e2c7392 (the last
    revision before the rename) directly, rather than by replaying the full
    migration history from base.

    Several ancestor migrations (from 5d48200b8d8a on) contain Postgres-only
    DDL — e.g. `ALTER COLUMN ... SET NOT NULL`, which SQLite's ALTER TABLE does
    not support at all — a pre-existing incompatibility that predates this
    task and is orthogonal to it (the app's own SQLite path never replays real
    migrations either; see conftest.py's Base.metadata.create_all()). Stamping
    straight to 9bb02e2c7392 below keeps the two migrations this test actually
    exists to check — the rename and this task's new one — running for real
    through Alembic, which is what the row-preservation assertions depend on.
    """
    conn.execute(
        sa.text(
            "CREATE TABLE app.datasets ("
            "id VARCHAR NOT NULL PRIMARY KEY, name VARCHAR NOT NULL, n_rows INTEGER NOT NULL, "
            "n_cols INTEGER NOT NULL, profile_json TEXT NOT NULL, data_csv TEXT NOT NULL, "
            "content_hash VARCHAR(64) NOT NULL UNIQUE, created_at DATETIME)"
        )
    )
    conn.execute(
        sa.text(
            "CREATE TABLE app.experiments ("
            "id VARCHAR NOT NULL PRIMARY KEY, mlflow_run_id VARCHAR NOT NULL, "
            "dataset_id VARCHAR, dataset_version VARCHAR, "
            "model_type VARCHAR NOT NULL, task_type VARCHAR(32) NOT NULL, "
            "notes TEXT NOT NULL, notes_status VARCHAR(16) NOT NULL, created_at DATETIME)"
        )
    )
    # The real chain gives this table these two indexes, and their names live in
    # the schema's namespace, not the table's. Omitting them here once hid a
    # migration bug that only broke on Postgres: renaming the table leaves the
    # indexes called ix_app_experiments_*, so the new parent `experiments` table
    # collided with them on CREATE INDEX. Keep them, or this guard stops
    # guarding that.
    # SQLite qualifies the INDEX name with the attached schema, not the table.
    conn.execute(
        sa.text("CREATE INDEX app.ix_app_experiments_mlflow_run_id ON experiments (mlflow_run_id)")
    )
    conn.execute(
        sa.text("CREATE INDEX app.ix_app_experiments_dataset_id ON experiments (dataset_id)")
    )
    conn.execute(
        sa.text(
            "CREATE TABLE app.findings ("
            "id VARCHAR NOT NULL PRIMARY KEY, source_type VARCHAR(16) NOT NULL, "
            "source_id VARCHAR NOT NULL, text TEXT NOT NULL, original_text TEXT NOT NULL, "
            "status VARCHAR(16) NOT NULL, created_at DATETIME)"
        )
    )


def test_hierarchy_migration_preserves_runs_and_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main_path = tmp_path / "m.db"
    db_url = f"sqlite:///{main_path}"
    cfg = _alembic_config(db_url)
    # NullPool: a fresh DBAPI connection per checkout. attach_app_schema's
    # `connect` listener re-ATTACHes "app" on each one automatically, so this
    # (unlike a manual per-connection ATTACH) never collides with a schema left
    # attached on a reused, pooled connection.
    engine = attach_app_schema(sa.create_engine(db_url, future=True, poolclass=sa.pool.NullPool))

    # backend/alembic/env.py ignores the ini's sqlalchemy.url and reads
    # app.config.settings.database_url instead (one source of truth for the real
    # app) — re-executed fresh on every alembic invocation, so this must point at
    # our tmp SQLite file before either upgrade call below.
    monkeypatch.setattr(settings, "database_url", db_url)

    # Land one revision before the rename, so the inserts below hit the OLD
    # table name ("experiments") — exercising the rename + backfill together,
    # exactly as they run against the real, pre-existing production rows.
    with engine.begin() as conn:
        _create_pre_hierarchy_schema(conn)
    command.stamp(cfg, "9bb02e2c7392")

    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO app.datasets (id, name, data_csv, n_rows, n_cols, profile_json, "
                "content_hash) "
                "VALUES ('d1', 'a.csv', 'x\n1\n', 1, 1, '{}', 'h1'), "
                "('d2', 'b.csv', 'x\n1\n', 1, 1, '{}', 'h2')"
            )
        )
        # r1/r2 share dataset d1, r3 is on d2, r4 has no dataset at all (NULL) —
        # the backfill's portability rewrite (avoiding Postgres-only
        # `IS NOT DISTINCT FROM`) touches exactly this NULL-dataset_id path, so
        # it needs its own row rather than relying on the by-hand check alone.
        # r5 shares d1 with r1/r2 but is a CLASSIFIER: the grouping key is
        # (dataset_id, task_type), not dataset alone. Without this row the
        # task_type half of that key is never exercised, and a backfill that
        # grouped on dataset only would pass — producing one experiment whose
        # runs are ranked on two incomparable metrics.
        # Every run carries the content hash of the dataset it was scored on.
        # The contract migration DROPS this column, so if the backfill does not
        # promote it to the parent first the pin is gone for good — and because
        # the column is nullable, nothing errors when that happens.
        rows = [
            ("r1", "'d1'", "regression", "'h1'"),
            ("r2", "'d1'", "regression", "'h1'"),
            ("r3", "'d2'", "regression", "'h2'"),
            ("r4", "NULL", "regression", "NULL"),
            ("r5", "'d1'", "classification", "'h1'"),
        ]
        for run_id, ds, task, version in rows:
            conn.execute(
                sa.text(
                    "INSERT INTO app.experiments "
                    "(id, mlflow_run_id, dataset_id, dataset_version, model_type, task_type, "
                    "notes, notes_status) "
                    f"VALUES ('{run_id}', 'mr-{run_id}', {ds}, {version}, 'ridge', '{task}', '', "
                    "'draft')"
                )
            )
        conn.execute(
            sa.text(
                "INSERT INTO app.findings (id, source_type, source_id, text, original_text, "
                "status) "
                "VALUES ('f1', 'diagnostic', 'r1', 't', 't', 'draft')"
            )
        )

    command.upgrade(cfg, "head")

    with engine.connect() as conn:
        run_ids = {r[0] for r in conn.execute(sa.text("SELECT id FROM app.runs"))}
        assert run_ids == {"r1", "r2", "r3", "r4", "r5"}, "the rename must preserve every row id"

        pairs = dict(conn.execute(sa.text("SELECT id, experiment_id FROM app.runs")).all())
        assert pairs["r1"] == pairs["r2"], "runs on one dataset share an experiment"
        assert pairs["r1"] != pairs["r3"], "runs on different datasets do not"
        assert pairs["r4"] not in (
            pairs["r1"],
            pairs["r3"],
        ), "NULL-dataset runs get their own group"
        assert pairs["r5"] != pairs["r1"], "same dataset, different task_type: a separate group"
        assert all(v is not None for v in pairs.values())

        source_id = conn.execute(sa.text("SELECT source_id FROM app.findings")).scalar_one()
        assert source_id in run_ids, "findings must still resolve after the rename"

        n = conn.execute(sa.text("SELECT count(*) FROM app.experiments")).scalar_one()
        assert n == 4, "one experiment per distinct (dataset_id, task_type), NULL included"

        # The dataset's filename names the experiment, minus the extension: the
        # name is read by humans on the leaderboard, and "a.csv" reads as a file
        # rather than as an investigation.
        named = dict(conn.execute(sa.text("SELECT id, name FROM app.experiments")).all())
        # d1 yields two groups, so the .csv-stripped dataset name alone is not
        # enough to tell them apart — and MLflow resolves an experiment BY name,
        # so a collision here would silently file both groups' runs together.
        assert named[pairs["r1"]] == "a (regression)"
        assert named[pairs["r5"]] == "a (classification)"
        assert named[pairs["r3"]] == "b", "a dataset with one group keeps the plain name"
        # A run with no dataset has no filename to borrow. It must not end up
        # named "" or "None" — either reads as a real name nobody chose.
        ungrouped = conn.execute(
            sa.text("SELECT name FROM app.experiments WHERE dataset_id IS NULL")
        ).scalar_one()
        assert ungrouped == "ungrouped"

        # Nothing may invent an objective (design §5.1) — an empty one is
        # honest, a plausible-sounding one reads as though someone stated it.
        objectives = {
            o for (o,) in conn.execute(sa.text("SELECT objective FROM app.experiments")).all()
        }
        assert objectives == {""}

        # Metric and direction follow the task_type, not a global default: a
        # classifier ranked on rmse-minimize would sort the leaderboard backwards.
        metric = dict(
            conn.execute(
                sa.text(
                    "SELECT primary_metric, metric_direction FROM app.experiments "
                    "WHERE task_type = 'classification'"
                )
            ).all()
        )
        assert metric == {"f1_macro": "maximize"}

        # The content-hash pin has to survive the trip up to the parent, because
        # the very next migration drops the column it came from.
        versions = dict(
            conn.execute(sa.text("SELECT id, dataset_version FROM app.experiments")).all()
        )
        assert versions[pairs["r1"]] == "h1", "the d1 regression group keeps its pin"
        assert versions[pairs["r3"]] == "h2", "a different dataset keeps a different pin"
        assert versions[pairs["r4"]] is None, "a run that never had one does not acquire one"


def test_the_hierarchy_migration_can_be_undone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The chain's downgrade path is what a bad deploy is rolled back through,
    so it has to actually run. It is lossy by design (`objective` has nowhere to
    go), but it must land on the pre-rename shape rather than erroring halfway
    and leaving a half-renamed database nobody can upgrade OR downgrade.
    """
    db_url = f"sqlite:///{tmp_path / 'd.db'}"
    cfg = _alembic_config(db_url)
    engine = attach_app_schema(sa.create_engine(db_url, future=True, poolclass=sa.pool.NullPool))
    monkeypatch.setattr(settings, "database_url", db_url)

    with engine.begin() as conn:
        _create_pre_hierarchy_schema(conn)
    command.stamp(cfg, "9bb02e2c7392")
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "9bb02e2c7392")

    with engine.connect() as conn:
        inspector = sa.inspect(conn)
        tables = set(inspector.get_table_names(schema="app"))
        assert "experiments" in tables and "runs" not in tables, "the rename is undone"
        cols = {c["name"] for c in inspector.get_columns("experiments", schema="app")}
        # The contraction's columns come back and the parent link goes away.
        assert {"dataset_id", "dataset_version", "task_type"} <= cols
        assert "experiment_id" not in cols
        # Index names live in the SCHEMA's namespace, so a downgrade that left
        # them called ix_app_runs_* would collide on the next upgrade.
        names = {i["name"] for i in inspector.get_indexes("experiments", schema="app")}
        assert names == {"ix_app_experiments_mlflow_run_id", "ix_app_experiments_dataset_id"}

    # Asserting on the index names is a proxy; re-upgrading is the real thing.
    # A downgrade that leaves an index misnamed fails HERE, on the CREATE INDEX
    # that collides with it — which is exactly how the original bug surfaced.
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert "runs" in set(sa.inspect(conn).get_table_names(schema="app"))


def test_contract_migration_drops_the_inherited_columns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_url = f"sqlite:///{tmp_path / 'c.db'}"
    cfg = _alembic_config(db_url)
    engine = attach_app_schema(sa.create_engine(db_url, future=True, poolclass=sa.pool.NullPool))

    # See the comment on the sibling test above: env.py reads
    # app.config.settings.database_url directly, ignoring the ini's
    # sqlalchemy.url, so this must be patched before upgrade() runs or the
    # migration executes against whatever settings.database_url resolves to
    # for the current process (the real dev Postgres, per the repo's .env).
    monkeypatch.setattr(settings, "database_url", db_url)

    # Same reason as the sibling test: land one revision before the rename
    # (9bb02e2c7392) rather than replaying from base — several ancestor
    # migrations contain Postgres-only DDL that SQLite's ALTER TABLE cannot
    # run at all. From there, upgrade() replays the rename (019c2ddeec73),
    # the parent-add + backfill (747b57a1d7a5), and this task's own
    # contraction (7fd6e7527935) for real. An empty `runs` table means the
    # new migration's "no orphaned experiment_id" guard sees zero rows,
    # which is a pass (vacuously true), not a skip of that check.
    with engine.begin() as conn:
        _create_pre_hierarchy_schema(conn)
    command.stamp(cfg, "9bb02e2c7392")

    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        cols = {c["name"] for c in sa.inspect(conn).get_columns("runs", schema="app")}
    assert "experiment_id" in cols
    assert {"dataset_id", "dataset_version", "task_type"} & cols == set()


def _seed_mlflow_params(engine: sa.Engine, rows: list[tuple[str, str]]) -> None:
    """Stand up the slice of MLflow's schema the backfill reads: `params`, keyed
    by `run_uuid`, holding one `target_column` row per run.

    Only the three columns the migration's JOIN touches. Mirroring MLflow's real
    table would be a fixture that has to be maintained against a store this
    project deliberately never models (D4).
    """
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE mlflow.params (key TEXT, value TEXT, run_uuid TEXT)"))
        for run_id, target in rows:
            conn.execute(
                sa.text(
                    "INSERT INTO mlflow.params (key, value, run_uuid) "
                    "VALUES ('target_column', :v, :r)"
                ),
                {"v": target, "r": f"mr-{run_id}"},
            )


def _pre_hierarchy_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rows: list[tuple[str, str, str]]
) -> tuple[Config, sa.Engine]:
    """A stamped pre-rename database holding `rows` of (run_id, dataset_id, task_type)."""
    db_url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = _alembic_config(db_url)
    engine = attach_app_schema(sa.create_engine(db_url, future=True, poolclass=sa.pool.NullPool))
    monkeypatch.setattr(settings, "database_url", db_url)
    with engine.begin() as conn:
        _create_pre_hierarchy_schema(conn)
        conn.execute(
            sa.text(
                "INSERT INTO app.datasets (id, name, data_csv, n_rows, n_cols, profile_json, "
                "content_hash) VALUES ('d1', 'a.csv', 'x\n1\n', 1, 1, '{}', 'h1')"
            )
        )
        for run_id, dataset_id, task in rows:
            conn.execute(
                sa.text(
                    "INSERT INTO app.experiments "
                    "(id, mlflow_run_id, dataset_id, dataset_version, model_type, task_type, "
                    "notes, notes_status) "
                    f"VALUES ('{run_id}', 'mr-{run_id}', '{dataset_id}', 'h1', 'ridge', "
                    f"'{task}', '', 'draft')"
                )
            )
    command.stamp(cfg, "9bb02e2c7392")
    return cfg, engine


def test_the_backfill_recovers_target_column_from_mlflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The target backfill has to actually run somewhere.

    Its `mlflow.params` JOIN was previously gated on `dialect == "postgresql"`,
    which is False for every test in this suite — so the branch that recovers the
    single field an investigation cannot launch a run without was covered by
    nothing. Attaching an `mlflow` schema (see app/sqlite_schema.py) is what makes
    it reachable here.
    """
    cfg, engine = _pre_hierarchy_fixture(
        tmp_path, monkeypatch, [("r1", "d1", "regression"), ("r2", "d1", "regression")]
    )
    _seed_mlflow_params(engine, [("r1", "revenue"), ("r2", "revenue")])

    command.upgrade(cfg, "head")

    with engine.connect() as conn:
        target = conn.execute(sa.text("SELECT target_column FROM app.experiments")).scalar_one()
    assert target == "revenue", "the parent must inherit the target its runs were scored on"


def test_the_backfill_refuses_to_invent_a_target_it_could_have_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty `target_column` is a dead investigation: `/train` and `/tune` both
    need a target, so it can launch nothing. When the params table is reachable and
    simply has no answer for this group, the honest move is to stop — writing ""
    produces a row that looks entirely normal on the leaderboard and fails only
    later, at a point where the runs that knew the answer are no longer in front of
    anyone.
    """
    cfg, engine = _pre_hierarchy_fixture(tmp_path, monkeypatch, [("r1", "d1", "regression")])
    _seed_mlflow_params(engine, [])  # the table exists; it says nothing about r1

    with pytest.raises(RuntimeError, match="no logged target_column"):
        command.upgrade(cfg, "head")


def test_an_absent_tracking_store_still_migrates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal above must not become a hard dependency on MLflow. With no
    `params` table at all the target is unknowable rather than unread, so the
    migration completes and leaves the gap for `PATCH /experiments/{id}` to fill.
    """
    cfg, engine = _pre_hierarchy_fixture(tmp_path, monkeypatch, [("r1", "d1", "regression")])

    command.upgrade(cfg, "head")

    with engine.connect() as conn:
        target = conn.execute(sa.text("SELECT target_column FROM app.experiments")).scalar_one()
    assert target == ""
