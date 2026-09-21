# Project 2 — The Experiment/Run Hierarchy: Design

**Origin:** [issue #54](https://github.com/jwu444/ml-experiment-tracker-mlflow-optuna/issues/54) — surfaced while
running the Phase 2a/2b acceptance checklist ([#48](https://github.com/jwu444/ml-experiment-tracker-mlflow-optuna/issues/48),
item 5). What the app presents as a "leaderboard" is a flat, unordered list of every training run
ever made, with nothing recording which runs pursue the same question.

**Status:** approved design. Decisions **D33–D40** continue the numbering used by
`doc/plans/2026-08-10-project-2-phases-2-4-design.md` (D1–D27) and
`doc/plans/2026-08-19-project-2-phase-3-retrieval-agent-tracing-design.md` (D28–D32).

**Scope:** the entity refactor, MLflow-native grouping, the backfill migration, experiment-scoped
ranking, the frontend split, and an amendment to the not-yet-built #52 plan. Chosen over two
narrower options — see §12.

---

## 1. The problem, with evidence

Three claims, each checked against `main` and against the live dev database rather than inferred.

**1.1 `app.experiments` has no grouping field.** `backend/app/models.py`'s `Experiment` carries
`mlflow_run_id`, `dataset_id`, `dataset_version`, `model_type`, `task_type`, `notes`,
`notes_status`, `created_at`. Nothing says "this run and that run are attempts at the same
question." Every row floats free.

**1.2 Grouping in MLflow is inconsistent, not absent.** `routes/experiments.py:32` defines
`ADHOC_EXPERIMENT = "adhoc"` and passes it to every `log_run(...)` from `/train`. But
`/tune` does something different: line 195 builds `study_name = f"tune-{model_type}-{stamp}"`
and files that study's runs under an MLflow experiment of that name. The live store shows exactly
this split — 6 MLflow experiments over 35 runs:

```
Default
adhoc                                    ← every /train run, forever
tune-ridge-2026-08-13T20:03:24+00:00     ← one tuning invocation
tune-random_forest-2026-08-13T20:04:23+00:00
tune-gradient_boosting-2026-08-13T20:05:22+00:00
tune-ridge-2026-08-13T20:06:14+00:00
```

So the app is *already* using MLflow's Experiment→Run hierarchy, accidentally and inconsistently.
The groups it creates are timestamped throwaways — one per tuning call — which is not what an
investigation is. This is worth stating precisely because it changes the work from "adopt a
concept the app lacks" to "use correctly a concept the app is already using by accident."

**1.3 This is why the leaderboard does not rank.** `GET /experiments` orders by
`created_at DESC` only. `ExperimentsPage.tsx` has no sort control and no best-run highlight, and
`CompareTable` renders a side-by-side matrix with no notion of which column won. Adding a sort
button would not fix it: the pile currently mixes 25 runs predicting **company revenue** with 8
predicting **graphics-card prices**, and both report `rmse`. Sorting that by `rmse` would rank a
marathon time against a bench-press weight because both are numbers. **A ranking is only
meaningful within a set of runs that share an objective, and nothing currently defines that set.**

### 1.4 Live state this design must migrate

| | Count |
|---|---|
| `app.experiments` rows | **33** |
| `app.findings` rows | **5** (3 `diagnostic` → `experiments.id`, 2 `eda` → `datasets.id`) |
| `app.datasets` rows | 3 |
| `app.experiment_note_chunks` rows | **0** |
| `mlflow.runs` | 35 (2 with no `app` row — manual-testing orphans) |

All 33 notes are still `notes_status='draft'`; none are approved. The 33 rows split by
`dataset_id` into exactly two coherent investigations, both regression:

| Dataset | Runs | Models |
|---|---|---|
| `revenue-nowcast.csv` | 25 | ridge ×16, gradient_boosting ×8, persistence ×1 |
| `pc-part-video-card.csv` | 8 | random_forest ×8 |

### 1.5 A latent bug the hierarchy fixes

`routes/experiments.py:470` recovers the target column from MLflow params:

```python
target = run.params.get("target_column", "")
```

The target of a training run is not stored in our schema at all — it survives only as an MLflow
param, behind a network call, with an empty-string fallback. If that param is ever missing or the
store is unreachable mid-request, `""` flows into `diagnostics.residual_frame` and fails
obscurely. Promoting `target_column` to a real column (D34) removes the fallback path entirely.

---

## 2. D33 — Full MLflow mirror: `Experiment` groups `Run`

`app.experiments` is **renamed in place** to `app.runs`, and a new `app.experiments` is created
above it, meaning an investigation.

```
app.experiments  ── an investigation ──────────────  mlflow.experiments
      │  "can a nowcast beat persistence?"                 (same concept)
      │  objective, dataset, target, primary metric
      │
      └──< app.runs  ── one attempt ─────────────────  mlflow.runs
             "ridge, alpha=0.3"                            (same concept)
             model_type, notes, mlflow_run_id
```

**Rejected: `Project` + `Run`** (the issue's own proposal). It avoids reusing a word, but leaves
the top-level vocabulary diverging from MLflow — a mapping every reader has to learn — and
"Project" collides with "Project 2", this repo's own name.

**Rejected: add `Project`, rename nothing.** Smallest diff, no data migration, but it preserves the
exact collision #54 was filed about: `app.Experiment` would still mean `mlflow.Run`.

**The cost of D33, stated plainly:** the word "experiment" changes meaning as of this commit.
Every earlier design doc, code comment, and commit message uses it to mean one run. This cannot be
retroactively fixed, only signposted — see §11.

Note that this does **not** introduce a third "Experiment". Before: `app.experiments` (a run) vs
`mlflow.experiments` (a group) — two names, two meanings, colliding. After: both mean a group.
The `app_schema_only` Alembic filter (D4) still discriminates on schema exactly as it does today;
what changes is that the collision stops being semantic.

---

## 3. D34 — The question's invariants live on the experiment

This is the substantive half of the refactor. Today `dataset_id`, `dataset_version` and
`task_type` are repeated on every run, and nothing prevents two runs in the same presented
"leaderboard" from disagreeing on all three.

### `app.experiments` (new table)

| Column | Notes |
|---|---|
| `id` | uuid pk |
| `name` | required, human-facing |
| `objective` | free text, may be empty — the question being asked |
| `dataset_id` | FK → `app.datasets.id`, **nullable** (D5: a run against an external snapshot sets `dataset_version` instead) |
| `dataset_version` | nullable |
| `target_column` | **promoted out of MLflow params** (§1.5) |
| `task_type` | `regression` \| `classification` |
| `primary_metric` | the metric ranking uses |
| `metric_direction` | `minimize` \| `maximize` |
| `mlflow_experiment_id` | the MLflow experiment new runs are filed into |
| `created_at` | |

### `app.runs` (renamed from `app.experiments`)

| Column | Change |
|---|---|
| `id` | unchanged — **ids are preserved by the rename** (§5.2) |
| `experiment_id` | **new**, FK → `app.experiments.id`, `NOT NULL` |
| `mlflow_run_id` | unchanged |
| `model_type` | unchanged |
| `notes`, `notes_status` | unchanged — D20 holds exactly as written |
| `created_at` | unchanged |
| ~~`dataset_id`~~, ~~`dataset_version`~~, ~~`task_type`~~ | **removed** — inherited from the parent |

Runs in one experiment are now **structurally comparable**, which is the precondition ranking
needs. `notes`/`notes_status` stay per-run: a note is about one attempt, and D20's approval gate is
unchanged by this design.

### 3.1 `primary_metric` is not a new idea — it is `ModelSpec.objective_metric`, lifted

`ModelSpec` already carries `objective_metric: str  # the key in metrics this model is ranked on`
(`training.py:48`) alongside `direction` (`:49`). Its values across the registry:

| Models | `objective_metric` | `direction` |
|---|---|---|
| `ridge`, `random_forest`, `gradient_boosting`, `persistence` | `rmse` | `minimize` |
| `logistic_regression`, `random_forest_clf` | `f1_macro` | `maximize` |

So the experiment's `primary_metric` / `metric_direction` defaults are not invented: they are what
the registry already declares, defaulted from `task_type` at creation
(`regression` → `rmse`/`minimize`, `classification` → `f1_macro`/`maximize`), reusing the same
`minimize`/`maximize` spelling rather than a second one.

**The consistency rule this creates.** A leaderboard is only coherent if every run on it was ranked
on the same metric. Launching a model whose `objective_metric` differs from the experiment's
`primary_metric` is therefore a **422**, not a silently mixed ranking. In practice `task_type` on
the experiment (D34) already forces agreement, so this rejects only a genuine mismatch — but it is
an explicit check rather than an emergent property, because the failure it prevents produces a
table that looks completely normal.

**The noise-band metric is derived, not stored.** `cv_rmse` gets its name from
`f"cv_{spec.objective_metric}"` (`routes/experiments.py:214`, `:272`). D38's noise check reads
`cv_{primary_metric}` by the same rule, so there is no second column to keep in sync.

---

## 4. D35 — MLflow-side grouping applies to new runs only

`ADHOC_EXPERIMENT` is **deleted**, not defaulted. `log_run`'s first parameter — which already takes
an experiment name and already creates-or-gets by name — receives the parent experiment's name.

`/tune`'s `tune-{model}-{timestamp}` MLflow experiment is also removed. **An Optuna study is not an
investigation**; it is one hyperparameter search within one. The study name moves to a run tag, so
it stays queryable without masquerading as a grouping level. This also resolves the naming
collision the issue flagged around Optuna's "study."

**Historical MLflow runs stay where they are.** Re-filing them means a raw
`UPDATE mlflow.runs SET experiment_id = …`, and **D4 forbids our migrations touching MLflow's
schema** — that constraint is what keeps `--autogenerate` from proposing to drop 59 tables, and it
is not worth weakening for cosmetics. `experiment_log.fetch_runs` looks runs up by `run_id`, never
by experiment, so nothing functional depends on where they sit.

**Accepted cost:** `make mlflow-ui` will show the original 35 runs under `adhoc` and the four
`tune-*` experiments forever, while the app's own leaderboard groups them correctly. `app.runs` is
the authority for everything this app renders; MLflow's grouping is a convenience for its own UI.

---

## 5. D36 — Backfill by dataset; nothing is discarded

### 5.1 What the migration creates

Two experiments, from the natural split in §1.4:

| Name | Runs | `target_column` | `task_type` |
|---|---|---|---|
| `revenue-nowcast` | 25 | from the group's MLflow params | `regression` |
| `pc-part-video-card` | 8 | from the group's MLflow params | `regression` |

`objective` is left **empty** for a human to fill in. The migration must not invent a hypothesis
nobody stated — an objective fabricated by a data migration is worse than a blank one, because it
reads as though someone meant it.

`target_column` is backfilled per group from MLflow params. If a group's runs **disagree** on the
target, the migration **fails loudly** rather than picking one: disagreement means the grouping
assumption is wrong for that data, and silently choosing a value would produce an experiment whose
runs are not actually comparable — the precise failure this design exists to prevent.

The 2 orphan MLflow runs with no `app` row stay orphaned. `app.runs` is not reconstructed from
MLflow; the app database is the authority for what this app knows about.

### 5.2 Why `findings` needs no data migration

`findings.source_id` addresses `experiments.id` when `source_type='diagnostic'` (D22, no FK because
the column addresses two tables). A rename via `op.rename_table` **preserves every row id**, so all
3 diagnostic findings keep resolving with no data change at all. What changes is documentation and
the write-time validation in `app/findings.py`: `source_type='diagnostic'` now validates against
`app.runs`. This is a strong argument for rename-in-place over create-new-and-copy, and it is why
D33 is cheaper than it first appears.

### 5.3 Migration hazard — stated because it silently destroys data

**Alembic autogenerate does not detect table renames.** Pointed at this model change it will
propose `drop_table('experiments')` + `create_table('runs')`, which discards all 33 rows and orphans
the 3 findings that reference them. The generated file *looks* correct and the test suite — which
runs on a fresh SQLite database per test — would stay green.

This migration is therefore **hand-written**, using `op.rename_table`, with this ordering:

1. `rename_table('experiments' → 'runs')` in schema `app`
2. `create_table('experiments')` (the new parent)
3. Insert the two backfilled parent rows
4. `add_column('runs.experiment_id')`, populate it by `dataset_id`, then set `NOT NULL` and add
   the FK
5. `drop_column` on `runs`: `dataset_id`, `dataset_version`, `task_type`

Step 4 is deliberately three statements: adding a `NOT NULL` FK to a populated table in one step
fails on Postgres. Step 5 runs last so step 4's backfill can still read `dataset_id`.

A downgrade path is provided but is lossy in one specific way that must be documented in the
migration itself: `objective` and any human-authored experiment metadata have nowhere to go.

---

## 6. D37 — Two routers, split on the entity

`routes/experiments.py` is 510 lines and 6 routes today, and owns both "the investigation" and "one
attempt." It splits along the new boundary:

| `routes/experiments.py` — the investigation | `routes/runs.py` — one attempt |
|---|---|
| `POST /experiments` — create | `GET /runs/{id}` — detail |
| `GET /experiments` — list | `PATCH /runs/{id}` — notes review (D20) |
| `GET /experiments/{id}` — detail | `POST /runs/{id}/diagnostics` (D24) |
| `PATCH /experiments/{id}` — name/objective | |
| `GET /experiments/{id}/runs` — **the leaderboard** | |
| `POST /experiments/{id}/train` · `POST /experiments/{id}/tune` | |

The column-validation helpers (`_load_training_frame`, `_resolve_features`, `_validate_features`,
`_validate_columns`) are launching concerns and stay with `experiments.py`.

**Launching moves under the experiment, which shrinks the request rather than growing it.**
`TrainRequest` loses `dataset_id`, `target_column` and `task_type` — all inherited — leaving
`model_type`, `feature_columns`, `time_column`, `hyperparams`. It becomes **structurally impossible
to launch a run outside an experiment**, which is the invariant this whole design exists to create.
A default "unassigned" experiment is deliberately *not* provided: that is `adhoc` under a new name.

Every 404/422 guarantee the current routes make is preserved, including D18's rule that a typo'd
`time_column` is a 422 rather than a silent fallback to a random split.

---

## 7. D38 — Ranking is declared, and honest about noise

`GET /experiments/{id}/runs` orders runs by the experiment's `primary_metric` in its
`metric_direction` and marks the best. Three rules, each grounded in the live data:

**7.1 Rank on the holdout metric; show the cross-validated one beside it.** Metric coverage across
the 35 logged runs:

| Metric | Present on |
|---|---|
| `rmse`, `mae`, `r2` | **35 / 35** |
| `cv_rmse`, `cv_std` | **32 / 35** |

The three runs missing `cv_rmse` are the **persistence baseline** and the two orphans. Ranking on
`cv_rmse` would silently drop the baseline — the single run the leaderboard exists to measure
everything else against (D25) — off its own leaderboard. So ranking uses `rmse`, and `cv_rmse ±
cv_std` is displayed alongside as the noise check.

**7.2 A run missing the ranking metric sorts last and is labelled** — never dropped, never coerced
to `0` or infinity. A `FAILED` run is history worth seeing, and a silently-omitted row is how a
leaderboard starts lying.

**7.3 A win inside the fold spread is reported as a tie.** `CLAUDE.md` already establishes that on
the ~224-row revenue panel "a difference smaller than the fold spread is noise." The leaderboard
enforces it rather than restating it: when the leader's margin over second place is smaller than
its own `cv_std`, the UI reads **"within noise"** instead of crowning a winner. This is the
difference between sorting a column and producing a ranking that means something, and it is the
part of this design most directly aimed at #54's actual complaint.

**7.4 Degradation.** When the tracking store is unreachable, metrics come back empty with
`mlflow_available: false` — already the contract, and already handled by `ExperimentsPage`'s
`degraded` flag. Ranking then falls back to `created_at` with a visible banner. A read must not
500 on a down store.

---

## 8. D39 — The page splits the way the entities do

```
/experiments              list of investigations
                          name · objective · dataset · N runs · best score
        │
        └── /experiments/:id      objective, then the leaderboard
                                  ranked runs, best highlighted, "within noise" badge
                                  CompareTable with a per-metric winner column
                                  note-review dialog (unchanged)
```

`ExperimentsPage.tsx` (386 lines) splits into a list page and a detail page. Two things already
point this way: `CompareTable`'s prop is already named `runs`, and the page already computes
`mixedTasks` to detect incomparable rows — a guard that becomes unnecessary *inside* an experiment,
because D34 makes mixed tasks unrepresentable there.

`ReviewPage` and its D26 opened-rows gate are unaffected beyond source labelling. The `AppShell`
nav label stays "Experiments" and now points at something that is genuinely a list of experiments.

---

## 9. D40 — #52 is amended as a plan, before it becomes code

`doc/plans/2026-08-19-project-2-training-launch-ui.md` designs `NewRunDialog` to launch a run
against a bare dataset, with no experiment context — correctly, since experiments did not exist
when it was written. **It is written but unbuilt**, which makes this the one moment when the
amendment costs an hour of markdown instead of a rebuild.

Amended: the dataset picker becomes an experiment picker, with target/time/feature dropdowns
resolving through the experiment's dataset; a "New experiment" form is added for `POST /experiments`.
Untouched: `GET /models`, `DatasetDetailOut`, and the `persistence` / `prior_column` special case,
which are orthogonal to grouping.

**Sequencing:** this design lands **before** #52 is implemented. The alternative — ship #52
project-agnostic and retrofit — requires a fallback experiment for its runs to land in, which is
`adhoc` reintroduced one step after being removed, plus a rebuild of the dialog.

**Deliberately not folded in**, despite touching the same files: **#51** (persistence missing from
the model-type filter — the rewrite deletes that hardcoded `MODEL_TYPES` list, so it resolves
incidentally) and **#53** (review dialog too narrow). They stay their own issues.

---

## 10. Phase 3 impact

**One amendment.** `experiment_note_chunks.source_type='note'` will address `runs.id` rather than
`experiments.id`. **The table has 0 rows**, so this is free now and expensive after Phase 3 ships.
Retrieval also gains a natural `experiment_id` filter — scoping a search to one investigation is
the same argument that scopes ranking to one. The Phase 3 design on branch `phase3/design` gets an
amendment note; it is not yet merged.

**One dependency.** Phase 3 deliverable 3.0 makes `POST /experiments/train` log `cv_rmse`/`cv_std`
as `/tune` already does, and re-runs the persistence baseline. D38's noise check needs that data,
so 3.0 is promoted from a Phase 3 nice-to-have to a **prerequisite of this design's ranking being
meaningful for new runs**. Until it lands, `/train` runs show a ranking without a noise band —
which the UI must render as absent, not as zero spread.

---

## 11. Testing, weighted to the risk

**The migration is the dangerous part and gets a real test**, not a smoke test: build the
pre-migration schema, insert runs plus findings referencing them, run `upgrade`, then assert all 33
rows survive with **ids intact**, `experiment_id` is populated for every row, and all 3 findings
still resolve. Without this, §5.3's drop-and-create failure passes CI silently, because every other
test builds a fresh database.

**Ranking** gets unit tests over hand-constructed metric dictionaries with deliberately ordered
values — a missing-metric run, a within-noise pair, a clear win, and a `maximize` experiment.
Random vectors would assert nothing.

**Degradation** gets a test that ranking falls back to `created_at` and returns 200 when the store
is down.

**Frontend** tests assert on roles, accessible names and visible text — never CSS-module class
names, since Vitest runs with `css: false`.

**Doc sync** is required before merge per `CLAUDE.md`: `README.md`, `CLAUDE.md` (the code-layout
map and the MLflow decision notes), `doc/architecture.md` (§5 and §7, including the entity diagram
added in #47), and `doc/user-manual.md`.

---

## 12. Risks

**The rename touches ~30 files** across `backend/app`, `backend/tests`, `scripts/` and
`frontend/src`. A large mechanical diff is exactly the kind that hides one real change. Mitigation:
the rename lands as its own commit, separate from every behavioural change, so review can read the
two independently.

**"Experiment" changes meaning as of this commit.** Prior docs, comments and commit messages use it
to mean one run. Mitigation: a dated callout in `CLAUDE.md` stating the change and its date. This
is signposting, not a fix — the ambiguity in historical text is permanent and was accepted
knowingly when D33 was chosen over `Project`.

**Scope.** This is a schema migration, a 30-file rename, two new API surfaces, a page split and a
plan amendment in one project. It was chosen over two smaller alternatives — "entity + ranking,
leave #52 alone" (pays rework to keep the efforts decoupled) and "entity only, ranking later"
(finishes with #54's motivating bug still open) — on the grounds that #52 is still a document and
that the data here is regenerable via `make seed-history`.

---

## 13. Traceability

| Claim | Verified against |
|---|---|
| `ADHOC_EXPERIMENT = "adhoc"` on every `/train` log | `backend/app/routes/experiments.py:32,139-140` |
| `/tune` files runs under `tune-{model}-{ts}` | `backend/app/routes/experiments.py:195,217` |
| 6 MLflow experiments over 35 runs | `mlflow.experiments`, `mlflow.runs` (live dev DB) |
| Target recovered from MLflow params with `""` fallback | `backend/app/routes/experiments.py:470` |
| 33 rows splitting 25 / 8 by dataset | `app.experiments` ⋈ `app.datasets` (live dev DB) |
| `cv_rmse` on 32/35; absent on the persistence baseline | `mlflow.latest_metrics` (live dev DB) |
| 5 findings — 3 `diagnostic`, 2 `eda` | `app.findings` (live dev DB) |
| `experiment_note_chunks` empty | `app.experiment_note_chunks` (live dev DB) |
| `ModelSpec.objective_metric` is `rmse`/`f1_macro`; `direction` is `minimize`/`maximize` | `backend/app/training.py:45,48,49` and the six registry entries (`:102,114,126,134,146,157`) |
| `cv_rmse` is named `f"cv_{objective_metric}"` | `backend/app/routes/experiments.py:214,272` |
| `CompareTable` already names its prop `runs`; `mixedTasks` guard | `frontend/src/pages/ExperimentsPage.tsx:84,347` |
| `GET /experiments` orders by `created_at DESC` only | `backend/app/routes/experiments.py:298` |
| #52 is written but unbuilt | `doc/plans/2026-08-19-project-2-training-launch-ui.md`; no `NewRunDialog.tsx` on `main` |

---

## 14. Amendments to earlier documents

| Document | Amendment |
|---|---|
| `CLAUDE.md` | Code-layout map; a dated note that "experiment" changed meaning; `app.runs` added to the D4/MLflow notes; D22's `source_type='diagnostic'` now addresses `app.runs` |
| `doc/architecture.md` | §5 entity list. §7's MLflow entity diagram (#47, on the unmerged branch `docs/mlflow-entity-model`) states that "MLflow's `Experiment` and `Run` are **not** this project's `app.experiments` row" — **D33 makes that callout wrong**, since the two then correspond directly. Whichever of the two branches merges second must carry the fix. |
| `doc/plans/2026-08-19-project-2-training-launch-ui.md` | D40 — experiment picker replaces the dataset picker |
| `doc/plans/2026-08-19-project-2-phase-3-retrieval-agent-tracing-design.md` (branch `phase3/design`) | §10 — chunk `source_id` addresses `runs.id`; deliverable 3.0 promoted to a prerequisite |
| `doc/user-manual.md` | The experiments walkthrough; the leaderboard section |
| `README.md` | Feature list |
