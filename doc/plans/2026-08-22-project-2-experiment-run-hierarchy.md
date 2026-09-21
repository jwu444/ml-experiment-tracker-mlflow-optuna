# Experiment/Run Hierarchy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Design:** `doc/plans/2026-08-22-project-2-experiment-run-hierarchy-design.md` (decisions **D33–D40**). Read §2–§9 of that document before starting. **Origin:** [issue #54](https://github.com/jwu444/ml-experiment-tracker-mlflow-optuna/issues/54).

**Goal:** Give the app a real Experiment→Run hierarchy mirroring MLflow's own, so that a leaderboard ranks runs that actually share an objective.

**Architecture:** `app.experiments` is renamed in place to `app.runs`, and a new `app.experiments` above it means an investigation carrying the dataset, target, task type and ranking metric. Runs inherit those, which makes them structurally comparable. Schema work lands as three migrations — **rename, expand, contract** — so the dangerous rename is reviewable on its own and no step ever leaves the database in a state the code cannot serve.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2.0 (`Mapped`/`mapped_column`), Alembic, MLflow 3.15.1, pytest (backend); React + Vite + TypeScript, Vitest + React Testing Library (frontend).

## Global Constraints

- Line length **100** (ruff + black). mypy is **strict** on `backend/app`.
- Imports are absolute from `app` (e.g. `from app.ranking import rank_runs`).
- Backend app code in `backend/app/` only; backend tests in `backend/tests/` only.
- Backend tests run on **SQLite** via the `client` / `db_session` / `db_engine` fixtures in `backend/tests/conftest.py`. No API key, no network. Tests needing MLflow opt in with `pytestmark = pytest.mark.usefixtures("mlflow_store")`.
- Frontend tests run with `css: false`: assert on roles / accessible names / `data-*` / visible text, **never** CSS-module class names.
- All tables live in the **`app`** Postgres schema (`__table_args__ = {"schema": "app"}`). SQLite tests use `schema_translate_map={"app": None}` — already configured in `conftest.py`.
- **Never** model an MLflow table in `app/models.py`, and never write to the `mlflow` schema from a migration (D4).
- The CI gate is `make check` (lint + format-check + type-check + test) plus the frontend job (`npm run type-check`, `npm test`, `npm run build`).
- Alembic head at the start of this plan is **`9bb02e2c7392`**. Each migration task chains onto the previous one's revision id.
- Every task ends with a commit. Commit messages end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

## File Structure

**Created:**

| File | Responsibility |
|---|---|
| `backend/alembic/versions/<rev1>_rename_experiments_to_runs.py` | Migration 1 — rename only. |
| `backend/alembic/versions/<rev2>_add_experiments_parent.py` | Migration 2 — create parent, backfill, nullable FK. |
| `backend/alembic/versions/<rev3>_contract_runs_columns.py` | Migration 3 — FK `NOT NULL`, drop inherited columns. |
| `backend/app/ranking.py` | Pure ranking: metrics in, ranked order out. No DB, no MLflow, no HTTP. |
| `backend/app/routes/runs.py` | `GET`/`PATCH /runs/{id}`, `POST /runs/{id}/diagnostics`. |
| `backend/tests/test_ranking.py` | Unit tests for `rank_runs`. |
| `backend/tests/test_migration_hierarchy.py` | Proves the migrations preserve data. |
| `backend/tests/test_routes_runs.py` | Route tests for `routes/runs.py`. |
| `backend/tests/test_routes_experiments_crud.py` | Route tests for experiment CRUD + leaderboard. |
| `frontend/src/pages/ExperimentDetailPage.tsx` (+ `.module.css`, `.test.tsx`) | One investigation: objective + leaderboard. |

**Modified:**

| File | Change |
|---|---|
| `backend/app/models.py` | `Experiment` → `Run`; new `Experiment` parent. |
| `backend/app/schemas.py` | `ExperimentOut`/`ExperimentDetailOut`/`ExperimentPatchRequest` → `Run*`; new experiment schemas. |
| `backend/app/routes/experiments.py` | Rewritten: CRUD + leaderboard + launching under `/experiments/{id}`. |
| `backend/app/findings.py` | `source_type="diagnostic"` validates against `Run`. |
| `backend/app/main.py` | Register the `runs` router. |
| `scripts/seed_experiment_history.py` | Create an experiment, then launch runs inside it. |
| `frontend/src/types.ts`, `api.ts`, `App.tsx` | New types, endpoints, `/experiments/:id` route. |
| `frontend/src/pages/ExperimentsPage.tsx` | Becomes the investigation list. |
| `frontend/src/pages/ReviewPage.tsx` | Source labels say "run". |
| `README.md`, `CLAUDE.md`, `doc/architecture.md`, `doc/user-manual.md` | Doc sync (Task 9). |
| `doc/plans/2026-08-19-project-2-training-launch-ui.md` | D40 amendment (Task 9). |

**Unchanged, deliberately:** `backend/app/experiment_log.py`. `log_run`'s first parameter is already `experiment_name` and `_experiment_id` already creates-or-gets by name — the MLflow seam needs no work, only a caller that stops passing `"adhoc"`.

---

## Task 1: Rename the entity — `Experiment` → `Run`

Mechanical rename, its own commit, **no behaviour change**. HTTP paths stay `/experiments` (they start returning runs under a name that is now wrong; Task 4 fixes that). Doing this alone is what makes the later diffs readable.

**Files:**
- Modify: `backend/app/models.py:153-183` (the `Experiment` class)
- Modify: `backend/app/schemas.py:107,151,169`, `backend/app/routes/experiments.py`, `backend/app/findings.py`, `backend/app/routes/findings.py`
- Create: `backend/alembic/versions/<rev1>_rename_experiments_to_runs.py`
- Modify: `backend/tests/test_models.py`, `test_findings.py`, `test_routes_experiments_list.py`, `test_routes_experiments_train.py`, `test_routes_experiments_tune.py`, `test_diagnostics_route.py`, `test_alembic_env.py`

**Interfaces:**
- Produces: `app.models.Run` (was `Experiment`), `__tablename__ = "runs"`. `app.schemas.RunOut`, `RunDetailOut`, `RunPatchRequest`. Field names on all three are unchanged from their `Experiment*` originals.

- [x] **Step 1: Rename the model class and table**

In `backend/app/models.py`, rename the class and its table. Keep every column exactly as-is.

```python
class Run(Base):
    """One logged training run. Params/metrics live in MLflow, not here (D4) —
    this row carries only what MLflow can't: the link back to our dataset and
    the free-text notes that Phase 3 embeds.

    Named `Run` to match MLflow's own entity (D33). The investigation this run
    belongs to is `app.experiments`, added in Task 2.
    """

    __tablename__ = "runs"
    __table_args__ = {"schema": "app"}
```

- [x] **Step 2: Rename the schema classes**

In `backend/app/schemas.py`: `ExperimentOut` → `RunOut`, `ExperimentDetailOut` → `RunDetailOut`, `ExperimentPatchRequest` → `RunPatchRequest`. Field names inside them do not change. Note `ExperimentOut.experiment_id` and `TrialOut.experiment_id` both mean *our row id* — rename those fields to `run_id`, and `TuneOut.best_experiment_id` to `best_run_id`.

- [x] **Step 3: Update every call site**

`grep -rn 'Experiment' backend/app scripts` and update. `routes/experiments.py` uses `Experiment` in `_merge`, `list_experiments`, `get_experiment`, `update_experiment`, `train_experiment`, `tune_experiment`, `run_diagnostics`. `findings.py` imports it for `(source_type, source_id)` validation — its `"diagnostic"` branch now validates against `Run`, and its docstring must say so.

- [x] **Step 4: Write the rename migration**

```python
"""rename experiments to runs

Revision ID: <rev1>
Revises: 9bb02e2c7392
"""

revision: str = "<rev1>"
down_revision: str | None = "9bb02e2c7392"


def upgrade() -> None:
    # op.rename_table PRESERVES row ids, which is what keeps findings.source_id
    # (source_type='diagnostic') resolving with no data migration — see design
    # §5.2. A drop+create here would silently orphan them.
    op.rename_table("experiments", "runs", schema="app")


def downgrade() -> None:
    op.rename_table("runs", "experiments", schema="app")
```

- [x] **Step 5: Update the tests to the new names**

Rename references in the six test files listed above. No test *logic* changes — if a test's assertions need editing, the rename was not mechanical and something was missed.

- [x] **Step 6: Verify**

Run: `make check`
Expected: PASS, with no test-count change from before this task.

- [x] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: rename the Experiment entity to Run (D33)

Mechanical rename only — no behaviour change, no new table. app.experiments
becomes app.runs, which is what the row has always actually been: one
training attempt, MLflow's Run. The investigation level lands next.

op.rename_table preserves row ids, so the 3 findings whose source_id
addresses this table keep resolving with no data migration.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: Add the `Experiment` parent (expand)

Purely **additive**: the new table appears, every existing run is assigned to one, and nothing is dropped. Safe to deploy on its own.

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/<rev2>_add_experiments_parent.py`
- Create: `backend/tests/test_migration_hierarchy.py`

**Interfaces:**
- Consumes: `app.models.Run` (Task 1).
- Produces: `app.models.Experiment` with columns `id, name, objective, dataset_id, dataset_version, target_column, task_type, primary_metric, metric_direction, mlflow_experiment_id, created_at`; `Run.experiment_id: Mapped[str | None]` and the relationship `Run.experiment` / `Experiment.runs`.

- [x] **Step 1: Write the failing migration test**

Create `backend/tests/test_migration_hierarchy.py`:

```python
"""The migrations must not lose rows. Every other test builds a fresh database,
so a drop+create migration would pass the whole suite while destroying the 33
production rows (design §5.3). This is the only test that would catch it."""

import sqlalchemy as sa
from alembic import command
from alembic.config import Config


def _alembic_config(db_url: str) -> Config:
    cfg = Config("backend/alembic.ini")
    cfg.set_main_option("script_location", "backend/alembic")
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def test_hierarchy_migration_preserves_runs_and_findings(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = _alembic_config(db_url)
    engine = sa.create_engine(db_url, future=True)

    command.upgrade(cfg, "9bb02e2c7392")

    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO datasets (id, name, data_csv, n_rows, n_cols) "
                "VALUES ('d1', 'a.csv', 'x\\n1\\n', 1, 1), ('d2', 'b.csv', 'x\\n1\\n', 1, 1)"
            )
        )
        for run_id, ds in [("r1", "d1"), ("r2", "d1"), ("r3", "d2")]:
            conn.execute(
                sa.text(
                    "INSERT INTO experiments "
                    "(id, mlflow_run_id, dataset_id, model_type, task_type, notes, notes_status) "
                    f"VALUES ('{run_id}', 'mr-{run_id}', '{ds}', 'ridge', 'regression', '', 'draft')"
                )
            )
        conn.execute(
            sa.text(
                "INSERT INTO findings (id, source_type, source_id, text, original_text, status) "
                "VALUES ('f1', 'diagnostic', 'r1', 't', 't', 'draft')"
            )
        )

    command.upgrade(cfg, "head")

    with engine.connect() as conn:
        run_ids = {r[0] for r in conn.execute(sa.text("SELECT id FROM runs"))}
        assert run_ids == {"r1", "r2", "r3"}, "the rename must preserve every row id"

        pairs = dict(conn.execute(sa.text("SELECT id, experiment_id FROM runs")).all())
        assert pairs["r1"] == pairs["r2"], "runs on one dataset share an experiment"
        assert pairs["r1"] != pairs["r3"], "runs on different datasets do not"
        assert all(v is not None for v in pairs.values())

        source_id = conn.execute(sa.text("SELECT source_id FROM findings")).scalar_one()
        assert source_id in run_ids, "findings must still resolve after the rename"

        n = conn.execute(sa.text("SELECT count(*) FROM experiments")).scalar_one()
        assert n == 2, "one experiment per distinct dataset"
```

- [x] **Step 2: Run it to confirm it fails**

Run: `poetry run pytest backend/tests/test_migration_hierarchy.py -v`
Expected: FAIL — `no such table: runs` (the parent migration does not exist yet).

- [x] **Step 3: Add the `Experiment` model**

In `backend/app/models.py`, above `Run`:

```python
class Experiment(Base):
    """An investigation: one question, many attempts at it (D33).

    Mirrors MLflow's own Experiment-groups-Runs shape rather than inventing a
    parallel one. The dataset, target and task live HERE and not on the run
    (D34) — that is what makes the runs inside one experiment comparable, which
    is the precondition ranking needs.
    """

    __tablename__ = "experiments"
    __table_args__ = {"schema": "app"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # May be empty. A migration must never invent an objective nobody stated —
    # a fabricated one reads as though someone meant it (design §5.1).
    objective: Mapped[str] = mapped_column(Text, nullable=False, default="")
    dataset_id: Mapped[str | None] = mapped_column(
        ForeignKey("app.datasets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    dataset_version: Mapped[str | None] = mapped_column(String, nullable=True)
    # Promoted out of MLflow params, where it was recovered with a ""-fallback
    # behind a network call (design §1.5).
    target_column: Mapped[str] = mapped_column(String, nullable=False)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False, default="regression")
    # Lifted from ModelSpec.objective_metric / .direction, not invented (§3.1).
    primary_metric: Mapped[str] = mapped_column(String(32), nullable=False, default="rmse")
    metric_direction: Mapped[str] = mapped_column(String(16), nullable=False, default="minimize")
    mlflow_experiment_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    runs: Mapped[list["Run"]] = relationship(back_populates="experiment")
```

On `Run`, add (nullable for now — Task 5 tightens it):

```python
    experiment_id: Mapped[str | None] = mapped_column(
        ForeignKey("app.experiments.id", ondelete="CASCADE"), nullable=True, index=True
    )
    experiment: Mapped["Experiment | None"] = relationship(back_populates="runs")
```

Add `relationship` to the `sqlalchemy.orm` import if it is not already there.

- [x] **Step 4: Write the expand migration**

```python
"""add the experiments parent and backfill it

Revision ID: <rev2>
Revises: <rev1>
"""

revision: str = "<rev2>"
down_revision: str | None = "<rev1>"


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
    op.create_foreign_key(
        "fk_runs_experiment_id", "runs", "experiments",
        ["experiment_id"], ["id"],
        source_schema="app", referent_schema="app", ondelete="CASCADE",
    )

    _backfill()


def _backfill() -> None:
    """One experiment per distinct (dataset_id, task_type) among existing runs.

    Grouping by dataset is not arbitrary: on the live database the 33 rows split
    exactly 25 / 8 into two coherent investigations (design §1.4). `objective`
    is left empty on purpose.
    """
    conn = op.get_bind()
    groups = conn.execute(
        sa.text(
            "SELECT DISTINCT r.dataset_id, r.task_type FROM app.runs r "
            "WHERE r.experiment_id IS NULL"
        )
    ).all()
    for dataset_id, task_type in groups:
        name = conn.execute(
            sa.text("SELECT name FROM app.datasets WHERE id = :d"), {"d": dataset_id}
        ).scalar() or "ungrouped"
        targets = [
            t for (t,) in conn.execute(
                sa.text(
                    "SELECT DISTINCT p.value FROM app.runs r "
                    "JOIN mlflow.params p ON p.run_uuid = r.mlflow_run_id "
                    "WHERE p.key = 'target_column' AND r.dataset_id IS NOT DISTINCT FROM :d "
                    "AND r.task_type = :t"
                ),
                {"d": dataset_id, "t": task_type},
            ).all()
        ] if _has_mlflow_schema(conn) else []
        if len(targets) > 1:
            # Disagreement means the grouping assumption is wrong for this data.
            # Picking one would produce an experiment whose runs are NOT
            # comparable — the exact failure this design prevents (§5.1).
            raise RuntimeError(
                f"runs for dataset {dataset_id!r} disagree on target_column: {sorted(targets)}; "
                "group them by hand before migrating"
            )
        exp_id = str(uuid.uuid4())
        conn.execute(
            sa.text(
                "INSERT INTO app.experiments "
                "(id, name, objective, dataset_id, target_column, task_type, "
                " primary_metric, metric_direction) "
                "VALUES (:i, :n, '', :d, :tc, :t, :pm, :md)"
            ),
            {
                "i": exp_id,
                "n": name.removesuffix(".csv"),
                "d": dataset_id,
                "tc": targets[0] if targets else "",
                "t": task_type,
                "pm": "rmse" if task_type == "regression" else "f1_macro",
                "md": "minimize" if task_type == "regression" else "maximize",
            },
        )
        conn.execute(
            sa.text(
                "UPDATE app.runs SET experiment_id = :i "
                "WHERE experiment_id IS NULL AND task_type = :t "
                "AND dataset_id IS NOT DISTINCT FROM :d"
            ),
            {"i": exp_id, "d": dataset_id, "t": task_type},
        )


def _has_mlflow_schema(conn) -> bool:
    """The target backfill reads MLflow's params table. It exists on the dev/prod
    Postgres but never in the SQLite migration test, so its absence is normal and
    means only that target_column starts empty."""
    return conn.dialect.name == "postgresql" and conn.execute(
        sa.text("SELECT to_regclass('mlflow.params')")
    ).scalar() is not None


def downgrade() -> None:
    # Lossy: `objective` and any human-authored experiment metadata have nowhere
    # to go. Documented here rather than silently discarded.
    op.drop_constraint("fk_runs_experiment_id", "runs", schema="app", type_="foreignkey")
    op.drop_index("ix_app_runs_experiment_id", "runs", schema="app")
    op.drop_column("runs", "experiment_id", schema="app")
    op.drop_index("ix_app_experiments_dataset_id", "experiments", schema="app")
    op.drop_table("experiments", schema="app")
```

Add `import uuid` and `import sqlalchemy as sa` at the top.

- [x] **Step 5: Run the migration test**

Run: `poetry run pytest backend/tests/test_migration_hierarchy.py -v`
Expected: PASS.

- [x] **Step 6: Run the full check**

Run: `make check`
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: add the Experiment parent and backfill it (D34, D36)

Additive only: the new app.experiments appears, every existing run is
assigned to one, nothing is dropped yet. Runs are grouped by
(dataset_id, task_type) — on the live database that is exactly the 25/8
split into two coherent investigations.

The backfill REFUSES to guess: a group whose runs disagree on
target_column raises rather than picking one, because the result would be
an experiment whose runs are not comparable. objective is left empty for a
human, not invented.

test_migration_hierarchy.py is the only test that would catch a
drop-and-create rename — every other test builds a fresh database.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: The ranking module

Pure function, no DB and no MLflow, so the subtle rules are testable in isolation.

**Files:**
- Create: `backend/app/ranking.py`, `backend/tests/test_ranking.py`

**Interfaces:**
- Produces: `app.ranking.RankedRun` (frozen dataclass) and
  `rank_runs(rows: Sequence[tuple[str, dict[str, float]]], primary_metric: str, direction: str) -> list[RankedRun]`.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_ranking.py`. Values are hand-chosen and deliberately ordered — random vectors would assert nothing.

```python
import pytest
from app.ranking import rank_runs


def test_minimize_orders_ascending_and_marks_the_best():
    ranked = rank_runs(
        [("a", {"rmse": 5.0}), ("b", {"rmse": 2.0}), ("c", {"rmse": 9.0})],
        "rmse",
        "minimize",
    )
    assert [r.run_id for r in ranked] == ["b", "a", "c"]
    assert [r.rank for r in ranked] == [1, 2, 3]
    assert [r.is_best for r in ranked] == [True, False, False]


def test_maximize_orders_descending():
    ranked = rank_runs(
        [("a", {"f1_macro": 0.7}), ("b", {"f1_macro": 0.9})], "f1_macro", "maximize"
    )
    assert [r.run_id for r in ranked] == ["b", "a"]
    assert ranked[0].is_best


def test_a_run_missing_the_metric_sorts_last_and_is_not_ranked():
    """Never dropped and never coerced to 0/inf: a FAILED run is history worth
    seeing, and a silently omitted row is how a leaderboard starts lying."""
    ranked = rank_runs(
        [("missing", {"mae": 1.0}), ("present", {"rmse": 4.0})], "rmse", "minimize"
    )
    assert [r.run_id for r in ranked] == ["present", "missing"]
    assert ranked[1].rank is None
    assert ranked[1].value is None
    assert ranked[1].is_best is False


def test_a_win_smaller_than_the_leaders_cv_std_is_within_noise():
    """On a ~224-row panel a difference smaller than the fold spread is noise."""
    ranked = rank_runs(
        [
            ("winner", {"rmse": 10.0, "cv_rmse": 10.5, "cv_std": 2.0}),
            ("second", {"rmse": 11.0, "cv_rmse": 11.2, "cv_std": 1.8}),
        ],
        "rmse",
        "minimize",
    )
    assert ranked[0].run_id == "winner"
    assert ranked[0].within_noise is True, "margin 1.0 < cv_std 2.0"
    assert ranked[0].cv_value == 10.5
    assert ranked[0].cv_std == 2.0


def test_a_win_larger_than_the_cv_std_is_a_real_win():
    ranked = rank_runs(
        [
            ("winner", {"rmse": 10.0, "cv_rmse": 10.5, "cv_std": 0.2}),
            ("second", {"rmse": 14.0, "cv_rmse": 14.1, "cv_std": 0.3}),
        ],
        "rmse",
        "minimize",
    )
    assert ranked[0].within_noise is False, "margin 4.0 > cv_std 0.2"


def test_the_leader_without_cv_std_is_never_within_noise():
    """The persistence baseline is one of three runs with no cv_std at all
    (design §7.1). Absent spread must not read as zero spread."""
    ranked = rank_runs(
        [("baseline", {"rmse": 10.0}), ("other", {"rmse": 10.1})], "rmse", "minimize"
    )
    assert ranked[0].run_id == "baseline"
    assert ranked[0].cv_std is None
    assert ranked[0].within_noise is False


def test_a_single_run_is_best_but_not_within_noise():
    ranked = rank_runs([("only", {"rmse": 3.0, "cv_std": 9.0})], "rmse", "minimize")
    assert ranked[0].is_best is True
    assert ranked[0].within_noise is False, "nothing to be within noise OF"


def test_no_runs_returns_empty():
    assert rank_runs([], "rmse", "minimize") == []


def test_an_unknown_direction_raises():
    with pytest.raises(ValueError, match="direction"):
        rank_runs([("a", {"rmse": 1.0})], "rmse", "sideways")
```

- [x] **Step 2: Run them to confirm they fail**

Run: `poetry run pytest backend/tests/test_ranking.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ranking'`.

- [x] **Step 3: Implement `app/ranking.py`**

```python
"""Rank the runs inside one experiment (D38).

Deliberately pure: metrics in, ranked order out. The route supplies the
metrics it already fetched from MLflow, so this module has no DB session, no
tracking-store call, and no HTTP — which is what lets the three subtle rules
(missing metric, noise band, absent spread) be tested exactly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

_DIRECTIONS = {"minimize", "maximize"}


@dataclass(frozen=True)
class RankedRun:
    run_id: str
    rank: int | None  # 1-based; None when the ranking metric is absent
    value: float | None
    cv_value: float | None
    cv_std: float | None
    is_best: bool
    within_noise: bool


def rank_runs(
    rows: Sequence[tuple[str, dict[str, float]]],
    primary_metric: str,
    direction: str,
) -> list[RankedRun]:
    """Order `rows` (run id, MLflow metrics) by `primary_metric`.

    Runs missing the metric keep their incoming order and are appended
    unranked. The leader is flagged `within_noise` when its margin over second
    place is smaller than its own cross-validated spread — see §7.3.
    """
    if direction not in _DIRECTIONS:
        raise ValueError(f"direction must be one of {sorted(_DIRECTIONS)}, got {direction!r}")

    scored = [(rid, m) for rid, m in rows if primary_metric in m]
    unscored = [(rid, m) for rid, m in rows if primary_metric not in m]
    scored.sort(key=lambda pair: pair[1][primary_metric], reverse=direction == "maximize")

    # cv_rmse is named f"cv_{objective_metric}" by the training path, so the
    # noise-band key is derived rather than stored as a second column (§3.1).
    cv_key = f"cv_{primary_metric}"

    within_noise = False
    if len(scored) >= 2:
        leader_std = scored[0][1].get("cv_std")
        if leader_std is not None:
            margin = abs(scored[0][1][primary_metric] - scored[1][1][primary_metric])
            within_noise = margin < leader_std

    out = [
        RankedRun(
            run_id=rid,
            rank=i + 1,
            value=metrics[primary_metric],
            cv_value=metrics.get(cv_key),
            cv_std=metrics.get("cv_std"),
            is_best=i == 0,
            within_noise=within_noise if i == 0 else False,
        )
        for i, (rid, metrics) in enumerate(scored)
    ]
    out.extend(
        RankedRun(
            run_id=rid,
            rank=None,
            value=None,
            cv_value=metrics.get(cv_key),
            cv_std=metrics.get("cv_std"),
            is_best=False,
            within_noise=False,
        )
        for rid, metrics in unscored
    )
    return out
```

- [x] **Step 4: Run the tests**

Run: `poetry run pytest backend/tests/test_ranking.py -v`
Expected: PASS (9 tests).

- [x] **Step 5: Commit**

```bash
git add backend/app/ranking.py backend/tests/test_ranking.py
git commit -m "feat: rank_runs — experiment-scoped ranking with a noise band (D38)

Ranks on the holdout metric, not the cross-validated one: cv_rmse is absent
on 3 of 35 live runs including the persistence baseline, so ranking on it
would drop the baseline off the leaderboard it exists to anchor.

Three rules the tests pin exactly: a run missing the metric sorts last and
stays unranked rather than being dropped or coerced; a leader whose margin
is smaller than its own cv_std is reported within-noise; a leader with no
cv_std at all is never within-noise, because absent spread is not zero
spread.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: Experiment CRUD and the leaderboard

**Files:**
- Modify: `backend/app/schemas.py`, `backend/app/routes/experiments.py`
- Create: `backend/tests/test_routes_experiments_crud.py`

**Interfaces:**
- Consumes: `app.models.Experiment`/`Run` (Task 2), `app.ranking.rank_runs` (Task 3), `app.experiment_log.fetch_runs`.
- Produces: `ExperimentOut`, `ExperimentCreateRequest`, `ExperimentPatchRequest`, `LeaderboardRowOut`; routes `POST/GET /experiments`, `GET/PATCH /experiments/{id}`, `GET /experiments/{id}/runs`.

- [x] **Step 1: Add the schemas**

In `backend/app/schemas.py`:

```python
class ExperimentCreateRequest(BaseModel):
    model_config = _ML

    name: str
    target_column: str
    objective: str = ""
    dataset_id: str | None = None
    dataset_version: str | None = None
    task_type: Literal["regression", "classification"] = "regression"


class ExperimentOut(BaseModel):
    model_config = _ML

    id: str
    name: str
    objective: str
    dataset_id: str | None
    dataset_version: str | None
    target_column: str
    task_type: str
    primary_metric: str
    metric_direction: str
    n_runs: int
    created_at: dt.datetime


class ExperimentPatchRequest(BaseModel):
    """`None` means "leave it alone", matching RunPatchRequest's convention."""

    name: str | None = None
    objective: str | None = None


class LeaderboardRowOut(BaseModel):
    model_config = _ML

    run: RunDetailOut
    rank: int | None
    value: float | None
    cv_value: float | None
    cv_std: float | None
    is_best: bool
    within_noise: bool


class LeaderboardOut(BaseModel):
    model_config = _ML

    primary_metric: str
    metric_direction: str
    # False when the tracking store is unreachable: rows fall back to
    # created_at order and every metric field is None (§7.4).
    ranked: bool
    mlflow_available: bool
    rows: list[LeaderboardRowOut]
```

- [x] **Step 2: Write the failing route tests**

Create `backend/tests/test_routes_experiments_crud.py`:

```python
import pytest
from app.models import Experiment, Run

pytestmark = pytest.mark.usefixtures("mlflow_store")


def _make_experiment(client, dataset_id, **over):
    body = {"name": "nowcast", "target_column": "price", "dataset_id": dataset_id}
    body.update(over)
    resp = client.post("/experiments", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_defaults_the_metric_from_the_task_type(client, dataset_id):
    body = _make_experiment(client, dataset_id)
    assert body["primary_metric"] == "rmse"
    assert body["metric_direction"] == "minimize"
    assert body["n_runs"] == 0


def test_create_classification_defaults_to_f1_macro(client, dataset_id):
    body = _make_experiment(client, dataset_id, task_type="classification")
    assert body["primary_metric"] == "f1_macro"
    assert body["metric_direction"] == "maximize"


def test_create_rejects_an_unknown_dataset(client):
    resp = client.post(
        "/experiments",
        json={"name": "x", "target_column": "price", "dataset_id": "nope"},
    )
    assert resp.status_code == 404


def test_list_and_get_round_trip(client, dataset_id):
    created = _make_experiment(client, dataset_id)
    assert client.get("/experiments").json()[0]["id"] == created["id"]
    assert client.get(f"/experiments/{created['id']}").json()["name"] == "nowcast"


def test_get_unknown_experiment_is_404(client):
    assert client.get("/experiments/nope").status_code == 404


def test_patch_edits_name_and_objective(client, dataset_id):
    created = _make_experiment(client, dataset_id)
    resp = client.patch(f"/experiments/{created['id']}", json={"objective": "beat persistence"})
    assert resp.status_code == 200
    assert resp.json()["objective"] == "beat persistence"
    assert resp.json()["name"] == "nowcast", "an omitted field is left alone"


def test_leaderboard_ranks_and_flags_the_best(client, db_session, dataset_id, monkeypatch):
    from app import experiment_log
    from app.routes import experiments as routes

    created = _make_experiment(client, dataset_id)
    for run_id, mlflow_id in [("r1", "m1"), ("r2", "m2")]:
        db_session.add(
            Run(
                id=run_id,
                mlflow_run_id=mlflow_id,
                model_type="ridge",
                experiment_id=created["id"],
                notes="",
                notes_status="draft",
            )
        )
    db_session.commit()

    monkeypatch.setattr(
        routes.experiment_log,
        "fetch_runs",
        lambda ids: {
            "m1": experiment_log.RunData("m1", "FINISHED", {}, {"rmse": 9.0}),
            "m2": experiment_log.RunData("m2", "FINISHED", {}, {"rmse": 3.0}),
        },
    )
    body = client.get(f"/experiments/{created['id']}/runs").json()
    assert body["ranked"] is True
    assert [row["run"]["id"] for row in body["rows"]] == ["r2", "r1"]
    assert body["rows"][0]["is_best"] is True


def test_leaderboard_degrades_when_mlflow_is_down(client, db_session, dataset_id, monkeypatch):
    """A read must not 500 on a down tracking store (§7.4)."""
    from app.routes import experiments as routes

    created = _make_experiment(client, dataset_id)
    db_session.add(
        Run(
            id="r1", mlflow_run_id="m1", model_type="ridge",
            experiment_id=created["id"], notes="", notes_status="draft",
        )
    )
    db_session.commit()

    def boom(ids):
        raise RuntimeError("store down")

    monkeypatch.setattr(routes.experiment_log, "fetch_runs", boom)
    resp = client.get(f"/experiments/{created['id']}/runs")
    assert resp.status_code == 200
    assert resp.json()["ranked"] is False
    assert resp.json()["mlflow_available"] is False
    assert resp.json()["rows"][0]["rank"] is None
```

- [x] **Step 3: Run them to confirm they fail**

Run: `poetry run pytest backend/tests/test_routes_experiments_crud.py -v`
Expected: FAIL — 404 on `POST /experiments` (the route does not exist).

- [x] **Step 4: Implement the routes**

In `backend/app/routes/experiments.py`, replace `list_experiments` / `get_experiment` / `update_experiment` (which now belong to runs — Task 6 moves them) with:

```python
_METRIC_DEFAULTS = {"regression": ("rmse", "minimize"), "classification": ("f1_macro", "maximize")}


@router.post("", status_code=201, response_model=ExperimentOut)
def create_experiment(
    request: ExperimentCreateRequest, session: Session = Depends(get_session)
) -> ExperimentOut:
    if request.dataset_id is not None and session.get(Dataset, request.dataset_id) is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    metric, direction = _METRIC_DEFAULTS[request.task_type]
    row = Experiment(
        name=request.name,
        objective=request.objective,
        dataset_id=request.dataset_id,
        dataset_version=request.dataset_version,
        target_column=request.target_column,
        task_type=request.task_type,
        primary_metric=metric,
        metric_direction=direction,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _experiment_out(session, row)


@router.get("", response_model=list[ExperimentOut])
def list_experiments(
    dataset_id: str | None = None,
    task_type: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> list[ExperimentOut]:
    query = select(Experiment).order_by(Experiment.created_at.desc())
    if dataset_id:
        query = query.where(Experiment.dataset_id == dataset_id)
    if task_type:
        query = query.where(Experiment.task_type == task_type)
    rows = list(session.execute(query.limit(limit).offset(offset)).scalars())
    return [_experiment_out(session, row) for row in rows]


@router.get("/{experiment_id}", response_model=ExperimentOut)
def get_experiment(experiment_id: str, session: Session = Depends(get_session)) -> ExperimentOut:
    row = _require_experiment(session, experiment_id)
    return _experiment_out(session, row)


@router.patch("/{experiment_id}", response_model=ExperimentOut)
def update_experiment(
    experiment_id: str,
    request: ExperimentPatchRequest,
    session: Session = Depends(get_session),
) -> ExperimentOut:
    row = _require_experiment(session, experiment_id)
    if request.name is not None:
        row.name = request.name
    if request.objective is not None:
        row.objective = request.objective
    session.commit()
    session.refresh(row)
    return _experiment_out(session, row)


@router.get("/{experiment_id}/runs", response_model=LeaderboardOut)
def leaderboard(experiment_id: str, session: Session = Depends(get_session)) -> LeaderboardOut:
    """The leaderboard: runs ranked WITHIN one investigation (D38).

    Ranking the whole table would compare a revenue rmse against a GPU-price
    rmse — two numbers on unrelated scales. An experiment is what defines the
    comparable set.
    """
    experiment = _require_experiment(session, experiment_id)
    runs = list(
        session.execute(
            select(Run)
            .where(Run.experiment_id == experiment_id)
            .order_by(Run.created_at.desc())
        ).scalars()
    )
    details = _merge(runs, experiment)
    available = all(d.mlflow_available for d in details) and bool(details)
    if not details or not available:
        return LeaderboardOut(
            primary_metric=experiment.primary_metric,
            metric_direction=experiment.metric_direction,
            ranked=False,
            mlflow_available=available if details else True,
            rows=[
                LeaderboardRowOut(
                    run=d, rank=None, value=None, cv_value=None, cv_std=None,
                    is_best=False, within_noise=False,
                )
                for d in details
            ],
        )

    by_id = {d.id: d for d in details}
    ranked = rank_runs(
        [(d.id, d.metrics) for d in details],
        experiment.primary_metric,
        experiment.metric_direction,
    )
    return LeaderboardOut(
        primary_metric=experiment.primary_metric,
        metric_direction=experiment.metric_direction,
        ranked=True,
        mlflow_available=True,
        rows=[
            LeaderboardRowOut(
                run=by_id[r.run_id], rank=r.rank, value=r.value, cv_value=r.cv_value,
                cv_std=r.cv_std, is_best=r.is_best, within_noise=r.within_noise,
            )
            for r in ranked
        ],
    )


def _require_experiment(session: Session, experiment_id: str) -> Experiment:
    row = session.get(Experiment, experiment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return row


def _experiment_out(session: Session, row: Experiment) -> ExperimentOut:
    n = session.execute(
        select(func.count()).select_from(Run).where(Run.experiment_id == row.id)
    ).scalar_one()
    return ExperimentOut(
        id=row.id, name=row.name, objective=row.objective, dataset_id=row.dataset_id,
        dataset_version=row.dataset_version, target_column=row.target_column,
        task_type=row.task_type, primary_metric=row.primary_metric,
        metric_direction=row.metric_direction, n_runs=n, created_at=row.created_at,
    )
```

`_merge` gains a second parameter so `RunDetailOut`'s inherited fields come from the parent:

```python
def _merge(rows: list[Run], experiment: Experiment) -> list[RunDetailOut]:
```

and inside it, `dataset_id=experiment.dataset_id`, `dataset_version=experiment.dataset_version`, `task_type=experiment.task_type`. Import `func` from `sqlalchemy` and `rank_runs` from `app.ranking`.

- [x] **Step 5: Run the tests**

Run: `poetry run pytest backend/tests/test_routes_experiments_crud.py -v`
Expected: PASS (9 tests).

- [x] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: experiment CRUD and the experiment-scoped leaderboard (D37, D38)

GET /experiments/{id}/runs ranks runs within one investigation, which is the
only scope in which a ranking means anything — the flat table mixes a revenue
rmse with a GPU-price rmse.

primary_metric/metric_direction default from task_type using the same values
ModelSpec.objective_metric already declares, rather than a second spelling.

A down tracking store returns 200 with ranked=false and created_at order, not
a 500.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: Move launching under `/experiments/{id}` (contract)

**Files:**
- Modify: `backend/app/schemas.py` (`TrainRequest`, `TuneRequest`), `backend/app/routes/experiments.py`, `backend/app/models.py`
- Create: `backend/alembic/versions/<rev3>_contract_runs_columns.py`
- Modify: `backend/tests/test_routes_experiments_train.py`, `test_routes_experiments_tune.py`

**Interfaces:**
- Consumes: `_require_experiment` (Task 4).
- Produces: `POST /experiments/{experiment_id}/train`, `POST /experiments/{experiment_id}/tune`. `Run.experiment_id` becomes `Mapped[str]` (non-optional).

- [x] **Step 1: Shrink the request schemas**

`TrainRequest` and `TuneRequest` both drop `dataset_id`, `target_column` and `task_type` — inherited from the experiment. `TrainRequest` keeps `model_type`, `hyperparams`, `feature_columns`, `time_column`, `notes`; `TuneRequest` keeps `model_type`, `n_trials`, `feature_columns`, `time_column`, `notes`.

- [x] **Step 2: Write the failing tests**

Add to `backend/tests/test_routes_experiments_train.py`:

```python
def test_train_rejects_a_model_whose_metric_disagrees_with_the_experiment(client, dataset_id):
    """A leaderboard mixing an rmse with an f1_macro ranks nothing, and the
    resulting table looks completely normal — so this is checked, not assumed."""
    exp = client.post(
        "/experiments",
        json={
            "name": "clf", "target_column": "chipset",
            "dataset_id": dataset_id, "task_type": "classification",
        },
    ).json()
    resp = client.post(
        f"/experiments/{exp['id']}/train",
        json={"model_type": "ridge", "hyperparams": {}},
    )
    assert resp.status_code == 422
    assert "f1_macro" in resp.json()["detail"]


def test_train_inside_an_unknown_experiment_is_404(client):
    resp = client.post("/experiments/nope/train", json={"model_type": "ridge"})
    assert resp.status_code == 404


def test_a_trained_run_belongs_to_its_experiment(client, db_session, dataset_id):
    from app.models import Run

    exp = client.post(
        "/experiments",
        json={"name": "n", "target_column": "price", "dataset_id": dataset_id},
    ).json()
    resp = client.post(
        f"/experiments/{exp['id']}/train",
        json={"model_type": "ridge", "hyperparams": {"alpha": 1.0}},
    )
    assert resp.status_code == 200
    run = db_session.get(Run, resp.json()["run_id"])
    assert run.experiment_id == exp["id"]
```

Update every existing train/tune test to POST to `/experiments/{id}/train` with the shrunken body, creating an experiment first.

- [x] **Step 3: Run them to confirm they fail**

Run: `poetry run pytest backend/tests/test_routes_experiments_train.py -v`
Expected: FAIL — 404, the nested route does not exist.

- [x] **Step 4: Rewrite the launch routes**

```python
@router.post("/{experiment_id}/train", response_model=RunOut)
def train_run(
    experiment_id: str, request: TrainRequest, session: Session = Depends(get_session)
) -> RunOut:
    experiment = _require_experiment(session, experiment_id)
    spec = _require_model(request.model_type)
    _require_metric_agreement(spec, experiment)
    if experiment.dataset_id is None:
        raise HTTPException(
            status_code=409, detail="this experiment has no dataset_id; runs cannot be trained"
        )
    df, dataset = _load_training_frame(session, experiment.dataset_id)
    _validate_columns(df, experiment.target_column, request.time_column)
    features = _resolve_features(
        request.feature_columns, df, experiment.target_column, request.time_column
    )
    ...
    run_id = experiment_log.log_run(
        experiment.name,          # D35: the parent's name, never "adhoc"
        request.model_type,
        experiment.task_type,
        request.hyperparams,
        result,
        experiment.dataset_id,
        experiment.dataset_version,
        experiment.target_column,
        features,
        request.time_column,
    )
    row = Run(
        mlflow_run_id=run_id,
        experiment_id=experiment.id,
        model_type=request.model_type,
        notes=request.notes,
    )
    ...


def _require_model(model_type: str) -> training.ModelSpec:
    if model_type not in training.MODEL_REGISTRY:
        raise HTTPException(status_code=422, detail=f"unknown model_type {model_type!r}")
    return training.MODEL_REGISTRY[model_type]


def _require_metric_agreement(spec: training.ModelSpec, experiment: Experiment) -> None:
    """A leaderboard is coherent only if every run on it was ranked on the same
    metric. task_type on the experiment already forces agreement in practice, so
    this rejects a genuine mismatch — but it is checked rather than assumed,
    because the failure renders as a perfectly normal-looking table (§3.1)."""
    if spec.objective_metric != experiment.primary_metric:
        raise HTTPException(
            status_code=422,
            detail=(
                f"model {spec.objective_metric!r} is ranked on "
                f"{spec.objective_metric!r}, but this experiment ranks on "
                f"{experiment.primary_metric!r}"
            ),
        )
```

Apply the same shape to `tune_run`. In the tune route, **delete** `study_name` as the MLflow experiment name — pass `experiment.name` to `log_run` and set the study name as a tag instead:

```python
    # D35: an Optuna study is one hyperparameter search WITHIN an
    # investigation, not an investigation. It is a tag, not a grouping level.
    mlflow.set_tag("optuna_study", study_name)
```

Delete the module-level `ADHOC_EXPERIMENT = "adhoc"` constant entirely — no default, so a run cannot exist outside an experiment.

- [x] **Step 5: Make `experiment_id` non-optional**

In `models.py`, `Run.experiment_id` becomes `Mapped[str]` with `nullable=False`, and `Run.experiment` becomes `Mapped["Experiment"]`. Remove `dataset_id`, `dataset_version` and `task_type` from `Run`.

- [x] **Step 6: Write the contract migration**

```python
"""tighten experiment_id and drop the inherited run columns

Revision ID: <rev3>
Revises: <rev2>
"""

revision: str = "<rev3>"
down_revision: str | None = "<rev2>"


def upgrade() -> None:
    # Task 2's backfill assigned every existing row, and ADHOC_EXPERIMENT is
    # gone, so nothing can write a NULL by the time this runs.
    orphans = op.get_bind().execute(
        sa.text("SELECT count(*) FROM app.runs WHERE experiment_id IS NULL")
    ).scalar_one()
    if orphans:
        raise RuntimeError(f"{orphans} runs have no experiment_id; migration 2 did not complete")
    op.alter_column("runs", "experiment_id", nullable=False, existing_type=sa.String(), schema="app")
    # These now live on the parent (D34). Dropped last so the backfill above
    # could still read dataset_id.
    op.drop_column("runs", "dataset_id", schema="app")
    op.drop_column("runs", "dataset_version", schema="app")
    op.drop_column("runs", "task_type", schema="app")


def downgrade() -> None:
    op.add_column("runs", sa.Column("dataset_id", sa.String(), nullable=True), schema="app")
    op.add_column("runs", sa.Column("dataset_version", sa.String(), nullable=True), schema="app")
    op.add_column(
        "runs",
        sa.Column("task_type", sa.String(32), nullable=False, server_default="regression"),
        schema="app",
    )
    op.execute(
        "UPDATE app.runs SET dataset_id = e.dataset_id, dataset_version = e.dataset_version, "
        "task_type = e.task_type FROM app.experiments e WHERE e.id = app.runs.experiment_id"
    )
    op.alter_column("runs", "experiment_id", nullable=True, existing_type=sa.String(), schema="app")
```

- [x] **Step 7: Extend the migration test**

Add to `backend/tests/test_migration_hierarchy.py`:

```python
def test_contract_migration_drops_the_inherited_columns(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'c.db'}"
    cfg = _alembic_config(db_url)
    command.upgrade(cfg, "head")
    engine = sa.create_engine(db_url, future=True)
    cols = {c["name"] for c in sa.inspect(engine).get_columns("runs")}
    assert "experiment_id" in cols
    assert {"dataset_id", "dataset_version", "task_type"} & cols == set()
```

- [x] **Step 8: Verify**

Run: `make check`
Expected: PASS.

- [x] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: launch runs inside an experiment; delete ADHOC_EXPERIMENT (D35, D37)

POST /experiments/{id}/train and /tune. The request body SHRINKS —
dataset_id, target_column and task_type are inherited — and it becomes
structurally impossible to launch a run outside an experiment. No default
experiment is provided: that is adhoc under a new name.

/tune stops creating a tune-<model>-<timestamp> MLflow experiment per call.
An Optuna study is one search within an investigation, not an investigation;
the study name is now a run tag.

A model whose objective_metric disagrees with the experiment's
primary_metric is a 422 — a mixed-metric leaderboard renders as a normal
table, so it is checked rather than assumed.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: The runs router

**Files:**
- Create: `backend/app/routes/runs.py`, `backend/tests/test_routes_runs.py`
- Modify: `backend/app/main.py`, `backend/app/routes/experiments.py` (move code out), `backend/tests/test_routes_experiments_list.py` → `test_routes_runs_list.py`, `backend/tests/test_diagnostics_route.py`

**Interfaces:**
- Produces: `GET /runs`, `GET /runs/{run_id}`, `PATCH /runs/{run_id}`, `POST /runs/{run_id}/diagnostics`.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_routes_runs.py`:

```python
import pytest
from app.models import Experiment, Run

pytestmark = pytest.mark.usefixtures("mlflow_store")


@pytest.fixture
def run_id(db_session, dataset_id):
    exp = Experiment(
        id="e1", name="n", target_column="price", dataset_id=dataset_id,
        task_type="regression", primary_metric="rmse", metric_direction="minimize",
    )
    db_session.add(exp)
    db_session.add(
        Run(id="r1", mlflow_run_id="m1", experiment_id="e1", model_type="ridge",
            notes="", notes_status="draft")
    )
    db_session.commit()
    return "r1"


def test_get_run_inherits_the_experiments_fields(client, run_id, dataset_id):
    body = client.get(f"/runs/{run_id}").json()
    assert body["dataset_id"] == dataset_id, "inherited from the parent (D34)"
    assert body["task_type"] == "regression"


def test_patch_writes_a_note_without_approving_it(client, run_id):
    """Writing a note is NOT approving it (D20) — the seeding script goes
    through this route, and an implicit approval would pre-bless every draft."""
    body = client.patch(f"/runs/{run_id}", json={"notes": "looks fine"}).json()
    assert body["notes"] == "looks fine"
    assert body["notes_status"] == "draft"


def test_an_empty_note_cannot_be_approved(client, run_id):
    resp = client.patch(f"/runs/{run_id}", json={"notes_status": "approved"})
    assert resp.status_code == 422


def test_an_empty_note_can_be_rejected(client, run_id):
    resp = client.patch(f"/runs/{run_id}", json={"notes_status": "rejected"})
    assert resp.status_code == 200


def test_list_filters_by_experiment(client, db_session, run_id):
    db_session.add(
        Experiment(id="e2", name="other", target_column="price", task_type="regression",
                   primary_metric="rmse", metric_direction="minimize")
    )
    db_session.add(
        Run(id="r2", mlflow_run_id="m2", experiment_id="e2", model_type="ridge",
            notes="", notes_status="draft")
    )
    db_session.commit()
    body = client.get("/runs", params={"experiment_id": "e1"}).json()
    assert [r["id"] for r in body] == ["r1"]


def test_unknown_run_is_404(client):
    assert client.get("/runs/nope").status_code == 404
```

- [x] **Step 2: Run them to confirm they fail**

Run: `poetry run pytest backend/tests/test_routes_runs.py -v`
Expected: FAIL — 404, `/runs` is not registered.

- [x] **Step 3: Create the router**

Create `backend/app/routes/runs.py` with `router = APIRouter(prefix="/runs", tags=["runs"])`. Move `list_experiments`' filtering body (renamed `list_runs`, gaining an `experiment_id` filter and joining `Experiment` for `task_type`/`dataset_id`), the old `get_experiment`/`update_experiment` bodies (as `get_run`/`update_run`), `_merge`, `run_diagnostics`, `load_logged_model` and `DIAGNOSTICS_QUESTION` out of `routes/experiments.py`.

In `run_diagnostics`, the inherited reads change:

```python
    run = _require_run(session, run_id)
    experiment = run.experiment
    if experiment.task_type != "regression":
        raise HTTPException(
            status_code=409,
            detail="diagnostics are regression-only; residuals are undefined for a "
            f"{experiment.task_type} run",
        )
    if experiment.dataset_id is None:
        raise HTTPException(
            status_code=409, detail="this run has no dataset_id; its rows cannot be reloaded"
        )
    ...
    # D34: the target is a column now, not an MLflow param behind a ""-fallback.
    target = experiment.target_column
```

`features` and `time_column` still come from MLflow params — they are per-run, not per-experiment.

- [x] **Step 4: Register the router**

In `backend/app/main.py`:

```python
    app.include_router(runs.router)
```

- [x] **Step 5: Update `findings.py`**

Its `"diagnostic"` branch validates `source_id` against `Run`. Update the docstring: `source_id` addresses `datasets.id` for `"eda"` and **`runs.id`** for `"diagnostic"`.

- [x] **Step 6: Run the tests**

Run: `make check`
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: routes/runs.py — run detail, note review, diagnostics (D37)

Splits the 510-line routes/experiments.py along the new entity boundary.
Diagnostics reads the target from experiments.target_column instead of
recovering it from an MLflow param with an \"\"-fallback, which removes a
path where a missing param fed \"\" into residual_frame.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: Frontend types and API client

**Files:**
- Modify: `frontend/src/types.ts`, `frontend/src/api.ts`

**Interfaces:**
- Produces: `ExperimentRow`, `RunRow`, `Leaderboard`, `LeaderboardRow`; `listExperiments`, `createExperiment`, `getExperiment`, `updateExperiment`, `getLeaderboard`, `listRuns`, `getRun`, `updateRun`, `runDiagnostics`.

- [x] **Step 1: Replace the types**

In `frontend/src/types.ts`, rename the existing `ExperimentRow` to `RunRow` (its fields are unchanged) and add:

```typescript
export interface ExperimentRow {
  id: string;
  name: string;
  objective: string;
  dataset_id: string | null;
  dataset_version: string | null;
  target_column: string;
  task_type: string;
  primary_metric: string;
  metric_direction: string;
  n_runs: number;
  created_at: string;
}

export interface LeaderboardRow {
  run: RunRow;
  /** null when this run has no value for the ranking metric — it sorts last
   *  and is shown unranked rather than dropped. */
  rank: number | null;
  value: number | null;
  cv_value: number | null;
  cv_std: number | null;
  is_best: boolean;
  /** The leader's margin over second place is smaller than its own cv_std. */
  within_noise: boolean;
}

export interface Leaderboard {
  primary_metric: string;
  metric_direction: string;
  ranked: boolean;
  mlflow_available: boolean;
  rows: LeaderboardRow[];
}
```

- [x] **Step 2: Add the API functions**

In `frontend/src/api.ts`, following the existing `listExperiments` shape:

```typescript
export async function createExperiment(body: {
  name: string;
  target_column: string;
  objective?: string;
  dataset_id?: string | null;
  task_type?: string;
}): Promise<ExperimentRow> {
  return request<ExperimentRow>("/experiments", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function getLeaderboard(experimentId: string): Promise<Leaderboard> {
  return request<Leaderboard>(`/experiments/${experimentId}/runs`);
}
```

`listExperiments` now returns `ExperimentRow[]` and takes `{ dataset_id?, task_type? }`. `getExperiment`/`updateExperiment` target `/experiments/{id}`; `getRun`/`updateRun`/`runDiagnostics` target `/runs/{id}`.

- [x] **Step 3: Type-check**

Run: `cd frontend && npm run type-check`
Expected: FAIL — `ExperimentsPage.tsx` still uses the old shapes. That is Task 8; do not fix it here.

- [x] **Step 4: Commit**

```bash
git add frontend/src/types.ts frontend/src/api.ts
git commit -m "feat(frontend): types and API client for the experiment hierarchy

The old ExperimentRow becomes RunRow unchanged; ExperimentRow now describes
an investigation. Type-check fails until the pages are updated in the next
commit — the split is deliberate, so the page rewrite reviews on its own.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 8: The pages — investigation list and leaderboard

**Files:**
- Modify: `frontend/src/pages/ExperimentsPage.tsx` (+ `.test.tsx`), `frontend/src/App.tsx`, `frontend/src/pages/ReviewPage.tsx`
- Create: `frontend/src/pages/ExperimentDetailPage.tsx`, `.module.css`, `.test.tsx`

**Interfaces:**
- Consumes: Task 7's types and API functions.

- [x] **Step 1: Write the failing detail-page test**

Create `frontend/src/pages/ExperimentDetailPage.test.tsx`:

```typescript
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";
import ExperimentDetailPage from "./ExperimentDetailPage";
import * as api from "../api";

function renderAt(id: string) {
  return render(
    <MemoryRouter initialEntries={[`/experiments/${id}`]}>
      <Routes>
        <Route path="/experiments/:experimentId" element={<ExperimentDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

const run = (id: string) => ({
  id, mlflow_run_id: `m-${id}`, dataset_id: "d1", dataset_version: null,
  model_type: "ridge", task_type: "regression", notes: "", notes_status: "draft",
  created_at: "2026-08-22T00:00:00Z", status: "FINISHED", params: {},
  metrics: {}, mlflow_available: true,
});

beforeEach(() => {
  vi.spyOn(api, "getExperiment").mockResolvedValue({
    id: "e1", name: "nowcast", objective: "beat persistence", dataset_id: "d1",
    dataset_version: null, target_column: "revenue", task_type: "regression",
    primary_metric: "rmse", metric_direction: "minimize", n_runs: 2,
    created_at: "2026-08-22T00:00:00Z",
  });
});

test("shows the objective and marks the best run", async () => {
  vi.spyOn(api, "getLeaderboard").mockResolvedValue({
    primary_metric: "rmse", metric_direction: "minimize", ranked: true,
    mlflow_available: true,
    rows: [
      { run: run("a"), rank: 1, value: 3, cv_value: 3.1, cv_std: 0.1,
        is_best: true, within_noise: false },
      { run: run("b"), rank: 2, value: 9, cv_value: 9.2, cv_std: 0.2,
        is_best: false, within_noise: false },
    ],
  });
  renderAt("e1");
  expect(await screen.findByText("beat persistence")).toBeInTheDocument();
  expect(await screen.findByText(/best/i)).toBeInTheDocument();
});

test("says a within-noise win is not a real win", async () => {
  vi.spyOn(api, "getLeaderboard").mockResolvedValue({
    primary_metric: "rmse", metric_direction: "minimize", ranked: true,
    mlflow_available: true,
    rows: [
      { run: run("a"), rank: 1, value: 10, cv_value: 10.5, cv_std: 2,
        is_best: true, within_noise: true },
      { run: run("b"), rank: 2, value: 11, cv_value: 11.2, cv_std: 1.8,
        is_best: false, within_noise: false },
    ],
  });
  renderAt("e1");
  expect(await screen.findByText(/within noise/i)).toBeInTheDocument();
});

test("an unranked run is still listed", async () => {
  vi.spyOn(api, "getLeaderboard").mockResolvedValue({
    primary_metric: "rmse", metric_direction: "minimize", ranked: true,
    mlflow_available: true,
    rows: [
      { run: run("a"), rank: 1, value: 3, cv_value: null, cv_std: null,
        is_best: true, within_noise: false },
      { run: run("nometric"), rank: null, value: null, cv_value: null,
        cv_std: null, is_best: false, within_noise: false },
    ],
  });
  renderAt("e1");
  expect(await screen.findByText("nometric")).toBeInTheDocument();
});

test("warns instead of ranking when the tracking store is down", async () => {
  vi.spyOn(api, "getLeaderboard").mockResolvedValue({
    primary_metric: "rmse", metric_direction: "minimize", ranked: false,
    mlflow_available: false,
    rows: [{ run: run("a"), rank: null, value: null, cv_value: null,
             cv_std: null, is_best: false, within_noise: false }],
  });
  renderAt("e1");
  expect(await screen.findByText(/tracking store/i)).toBeInTheDocument();
});
```

- [x] **Step 2: Run it to confirm it fails**

Run: `cd frontend && npm test -- ExperimentDetailPage`
Expected: FAIL — cannot resolve `./ExperimentDetailPage`.

- [x] **Step 3: Build `ExperimentDetailPage.tsx`**

Loads the experiment and its leaderboard on mount from the `:experimentId` route param. Renders the name and objective as a header; then the leaderboard table with columns rank / model / the primary metric / `cv_<metric> ± cv_std` / status / notes. Rules:

- `is_best` rows carry a visible "Best" badge and `data-best="true"`.
- `within_noise` on the leader renders the text **"within noise"** next to the badge — the margin is smaller than the fold spread, so the win is not a win.
- `rank === null` rows render "—" in the rank cell and stay in the table.
- `mlflow_available === false` renders a banner containing "tracking store" above an unranked, `created_at`-ordered table.
- Reuse `CompareTable` (moved from `ExperimentsPage.tsx`) for multi-select comparison, adding a per-metric winner marker; drop its `mixedTasks` guard, which D34 makes unrepresentable inside an experiment.
- Reuse the existing `ReviewDialog` for note review, retargeted at `updateRun`.

- [x] **Step 4: Rewrite `ExperimentsPage.tsx` as the list**

A table of investigations: name, objective, dataset, `n_runs`, `created_at`, each row linking to `/experiments/:id`. Delete the hardcoded `MODEL_TYPES` array (which resolves #51 incidentally — the drifting copy is gone). Update `ExperimentsPage.test.tsx` to assert on investigation rows.

- [x] **Step 5: Add the route**

In `frontend/src/App.tsx`:

```tsx
<Route path="/experiments/:experimentId" element={<ExperimentDetailPage />} />
```

- [x] **Step 6: Update `ReviewPage.tsx`**

Its `diagnostic` findings now describe a **run**: update the source label text and any link to point at `/runs/{id}`'s parent experiment.

- [x] **Step 7: Verify**

Run: `cd frontend && npm run type-check && npm test && npm run build`
Expected: PASS.

- [x] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(frontend): investigation list and the experiment leaderboard (D39)

/experiments lists investigations; /experiments/:id shows one, with its runs
ranked. The leader is badged Best, and a leader whose margin is smaller than
its own cv_std is labelled 'within noise' rather than crowned — which is the
difference between sorting a column and ranking.

Runs with no value for the ranking metric are listed unranked, not dropped.
Deletes the hardcoded MODEL_TYPES copy, resolving #51 incidentally.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 9: Seeding, docs, and the #52 amendment

**Files:**
- Modify: `scripts/seed_experiment_history.py`, `README.md`, `CLAUDE.md`, `doc/architecture.md`, `doc/user-manual.md`, `doc/plans/2026-08-19-project-2-training-launch-ui.md`

- [x] **Step 1: Update the seeding script**

`seed_experiment_history.py` goes through the API (never the DB directly — D13). It now `POST /experiments` once per investigation, then POSTs runs to `/experiments/{id}/train` and `/tune`, then PATCHes notes to `/runs/{id}`. It must still write `{"notes": ...}` only, never `notes_status` — D20's rule that the seeder cannot approve its own output is unchanged.

- [ ] **Step 2: Run the seed end to end** *(not run: needs a live backend and an
  `ANTHROPIC_API_KEY`, and costs real tokens — left for a human to run)*

```bash
make db-up && make migrate && make dev &   # separate terminal
make data-fetch && make seed-history
```
Expected: runs appear under a named experiment; `make mlflow-ui` shows a real experiment name rather than `adhoc`.

- [x] **Step 3: Sync `CLAUDE.md`**

Update the code-layout map (`ranking.py`, `routes/runs.py`, the model rename). Add to the design-decisions section:

```markdown
**"Experiment" changed meaning on 2026-08-22 (D33).** Before that date, in code,
comments and commit messages, `app.experiments` meant ONE TRAINING RUN. It now
means an investigation containing many runs, and the old rows live in
`app.runs`. Text written before that date uses the old sense — this is
signposting, not something that can be retroactively fixed.

**A run cannot exist outside an experiment (D34/D37).** `runs.experiment_id` is
`NOT NULL`, launching is nested under `POST /experiments/{id}/train`, and there
is deliberately no default experiment — a fallback bucket is `adhoc` under a new
name. `dataset_id`, `dataset_version` and `target_column` live on the parent, so
runs in one experiment are comparable by construction.

**The leaderboard ranks on the holdout metric, not the cross-validated one
(D38).** `cv_rmse` is absent on the persistence baseline, so ranking on it drops
the baseline off the leaderboard it exists to anchor. `cv_<metric> ± cv_std` is
shown alongside, and a win smaller than the leader's `cv_std` is reported as
"within noise".
```

- [x] **Step 4: Sync `doc/architecture.md`**

Update §5's entity list. **In §7, fix the MLflow callout that D33 makes wrong**: it currently says MLflow's `Experiment`/`Run` are *not* this project's `app.experiments` row. They now correspond directly — `app.experiments` ↔ `mlflow.experiments`, `app.runs` ↔ `mlflow.runs`. If the `docs/mlflow-entity-model` branch (#47) has not merged yet, coordinate so whichever lands second carries this fix.

- [x] **Step 5: Sync `README.md` and `doc/user-manual.md`**

README: the feature list and any `curl` example now nests training under an experiment. User manual: the experiments walkthrough gains "create an experiment first", and the leaderboard section explains the "within noise" label.

- [x] **Step 6: Amend the #52 plan (D40)**

In `doc/plans/2026-08-19-project-2-training-launch-ui.md`: `NewRunDialog`'s dataset picker becomes an experiment picker; target/time/feature dropdowns resolve through the experiment's dataset; a "New experiment" form is added for `POST /experiments`. Add a note at the top recording that D40 amended it and why. Leave `GET /models`, `DatasetDetailOut` and the `persistence`/`prior_column` special case untouched.

- [x] **Step 7: Tick the design doc's traceability**

Nothing to change in the design document itself — it is the spec. Confirm every decision D33–D40 has a landed task.

- [x] **Step 8: Final verification**

Run: `make check && cd frontend && npm run type-check && npm test && npm run build`
Expected: PASS.

- [x] **Step 9: Commit**

```bash
git add -A
git commit -m "docs: sync docs and amend the #52 plan for the hierarchy (D40)

Records in CLAUDE.md that 'experiment' changed meaning on this date, since
every earlier doc, comment and commit uses the old sense and that cannot be
fixed retroactively.

Fixes the architecture.md §7 callout that D33 invalidates: MLflow's
Experiment/Run now correspond directly to app.experiments/app.runs.

Amends #52's NewRunDialog to launch inside an experiment — a markdown edit
now, a rebuild if it had shipped first.

Closes #54

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage.** D33 → Tasks 1–2. D34 → Tasks 2, 5. D35 → Task 5. D36 → Task 2. D37 → Tasks 4, 6. D38 → Tasks 3, 4, 8. D39 → Task 8. D40 → Task 9. Design §1.5 (the `""`-fallback target) → Task 6 Step 3. Design §3.1 (metric agreement) → Task 5 Step 4. Design §10 (Phase 3 amendment) is **deliberately excluded**: `phase3/design` is unmerged, so the note is added there when it merges, not from this branch.

**Type consistency.** `Run`/`Experiment` (models), `RunOut`/`RunDetailOut`/`RunPatchRequest` and `ExperimentOut`/`ExperimentCreateRequest`/`ExperimentPatchRequest`/`LeaderboardOut`/`LeaderboardRowOut` (schemas), `RankedRun`/`rank_runs` (ranking), `RunRow`/`ExperimentRow`/`Leaderboard`/`LeaderboardRow` (frontend). `_merge(rows, experiment)` takes the parent in every call site from Task 4 on. `rank_runs` is called only in Task 4.

**Known ordering constraint.** Task 7 leaves `npm run type-check` failing on purpose; Task 8 restores it. A reviewer gating Task 7 on a green frontend build will wrongly reject it — the split exists so the page rewrite reviews independently.
