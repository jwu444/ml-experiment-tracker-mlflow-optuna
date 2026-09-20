# Project 2 — Phase 2b Design: EDA, Diagnostics, and Chunk Source Types

> **Scope:** the design for Phase 2b of `doc/plans/2026-08-05-project-2-overall-implementation-plan.md`
> (§3b, deliverables 2b.1–2b.4). Amends `doc/plans/2026-08-10-project-2-phases-2-4-design.md`
> (D19, D20, D21) where 2a's build changed what those decisions imply.
>
> **Status:** approved 2026-08-14; **implemented 2026-08-15/16** on `phase2b/impl`, all
> ten tasks landed and reviewed. D22–D27 shipped as designed. Headline result: the D25
> persistence baseline is the **best model on the revenue panel** — 0 of 25 runs beat it
> (see §3b of the overall plan). One deviation found during integration and fixed:
> `PriorValueRegressor` had to be added to `experiment_log.log_run`'s `skops_trusted_types`,
> without which every persistence run 500s against a real MLflow store.
> The task-by-task implementation plan follows as
> `doc/plans/2026-08-14-project-2-phase-2b-eda-diagnostics.md`.

**Parent design:** `doc/project-2-ml-experiment-tracker-design.md`
**Phase 2a plan (complete):** `doc/plans/2026-08-10-project-2-phase-2-training-mlflow-optuna.md`

---

## 1. Goal

Two things Phase 2a deliberately left out:

1. **An honest read on whether the models are worth anything.** 2a produced 32 tuned runs and a
   leaderboard. It never answered whether any of them beats predicting *next quarter's revenue
   equals this quarter's revenue*. On a 224-row panel with a ~30-row holdout, that is the
   question that decides whether the numbers mean anything.
2. **The other two content types D21 requires.** Phase 3 retrieves over experiment notes, EDA
   findings, and diagnostic interpretations. Only the first exists.

**Non-goals.** No retrieval, no embeddings, no agent — those are Phase 3. No new LLM plumbing:
D19 commits to reusing `app/loop.py`, and this design holds that line except for two analysis
tools (§4.3), which are data-plumbing rather than LLM machinery.

---

## 2. What 2a already settled

Recorded here because three of Phase 2b's original assumptions turned out to be stale.

- **D20's review panel already exists.** Built as 2a Task 9 (`frontend/src/pages/ExperimentsPage.tsx`),
  including the `draft`/`approved`/`rejected` badges and the per-run review dialog. 2b.4 is
  therefore only the *richer* review — bulk approval and a diff — not the panel itself.
- **Fitted models are already persisted.** `backend/app/experiment_log.py:138` calls
  `mlflow.sklearn.log_model` for every `FINISHED` run, serialised with skops. All 32 seeded runs
  have a loadable pipeline. Diagnostics does not need a refit.
- **LLM-calling routes are already a solved testing problem.** `backend/tests/test_chats.py:42`
  monkeypatches `run_loop` on the route module. D17's "endpoints never call Claude" was scoped to
  the *training* endpoints, to keep them keyless; it was never a whole-app rule, and `/chats`
  has always broken it.

---

## 3. Data model

### 3.1 New table: `app.findings`

| Column | Type | Notes |
|---|---|---|
| `id` | `varchar` pk (uuid) | |
| `source_type` | `varchar(16)` not null | `eda` \| `diagnostic` |
| `source_id` | `varchar` not null, indexed | `datasets.id` when `eda`, `experiments.id` when `diagnostic` |
| `text` | `text` not null | the reviewable write-up; edited in place by the reviewer |
| `original_text` | `text` not null | the model's untouched draft, frozen at insert |
| `status` | `varchar(16)` not null, server_default `'draft'` | `draft` \| `approved` \| `rejected` |
| `created_at` | `timestamptz` server_default `now()` | |

**Why `source_id` has no foreign key.** It addresses two different tables depending on
`source_type`, and a column cannot carry two FKs. D21 already accepted this for the chunk table;
`findings` inherits the same trade-off and the same mitigation — validation in `app/findings.py`
(§4.1) rather than in the database.

**Why `original_text` exists.** 2b.4 asks for a draft-vs-edit diff. Without a frozen copy of what
the model wrote, the left-hand side of that diff is gone the moment the reviewer saves. It is set
once at insert and never rewritten, which also gives Phase 4 a provenance record: how much of the
"known-relevant" ground truth is the model's words and how much is the human's.

**Why not one table for all reviewable text.** Folding `experiments.notes` in would give a single
review surface and a single status column, at the cost of migrating 32 live draft rows and making
a breaking change to `PATCH /experiments/{id}` — a route 2a shipped, reviewed, and fixed one
defect in. The uniformity is not worth reopening it. Phase 3 reads two sources instead of one,
which is a `UNION` in one query.

**Why not write findings into the chunk table directly.** `chunk_index` and `chunk_text` have no
meaning before chunking, and chunking is a Phase 3 decision. Reusing that table would mean a
nullable `embedding` and a `NOT NULL` guard on every Phase 3 query — a schema that lies about what
a row is.

### 3.2 Migration: `experiment_note_chunks` (2b.3)

| Before | After |
|---|---|
| `experiment_id` FK → `app.experiments.id`, `ondelete=CASCADE` | `source_type varchar(16)`, `source_id varchar` (indexed, no FK) |
| — | `status varchar(16)` not null, server_default `'draft'` |
| `UNIQUE (experiment_id, chunk_index)` | `UNIQUE (source_type, source_id, chunk_index)` |

The table is empty, so this is a pure schema change with no data step — which is exactly why D21
wanted it done before Phase 3 fills it.

**The real cost is the lost `CASCADE`.** Deleting an experiment currently cleans up its chunks;
after this migration it will not. Phase 3 owns that cleanup, and the migration file will say so in
a comment rather than leaving it to be discovered when orphaned chunks start appearing in
retrieval results.

### 3.3 Unchanged

`experiments.notes` and `experiments.notes_status` keep their 2a definitions, and the 32 existing
drafts are untouched.

---

## 4. Backend

### 4.1 `app/findings.py` — persistence and validation

Knows nothing about LLMs or HTTP. Create a draft, list by `status`/`source_type`, update text
and status, and perform the referential validation the missing FK no longer provides: an `eda`
finding's `source_id` must exist in `datasets`, a `diagnostic`'s in `experiments`. An unknown
`source_id` is an error at write time, not a dangling row discovered later.

Status transitions mirror the experiment-notes rules established in 2a: approving an empty
finding is a 422; rejecting one is allowed; editing text is never implicitly an approval.

### 4.2 `app/diagnostics.py` — the residual frame

Two pure functions. Neither loads anything, calls an LLM, or touches the database — each takes an
already-loaded pipeline and returns a DataFrame.

```
residual_frame(model, frame, target_column, time_column)       -> DataFrame
learning_curve_frame(model, frame, target_column, time_column) -> DataFrame
```

`residual_frame` re-derives the holdout with the existing `training.split_frame`, predicts, and
returns `actual`, `predicted`, `residual`, `abs_error`, plus the identifying columns (`ticker`,
the time column) needed to group and plot.

`learning_curve_frame` wraps sklearn's `learning_curve` — using the same `cv_splitter` the run was
scored with, so a temporal run gets `TimeSeriesSplit` — and returns one row per training size:
`train_size`, `train_score`, `validation_score`.

**Why both return frames.** `charts.py:_DISPATCH` hands tools a dict of DataFrames and nothing
else; a tool has no route to a fitted estimator. Computing the curve *here* and handing the loop a
frame keeps every tool a pure function of a DataFrame, which is the property that makes the whole
chart layer testable. The alternative — widening the dispatch signature so one tool can reach a
model — would leak modelling state into the chart layer for a single caller.

Separating both from the route is what makes them testable: the assertion that matters is that the
rows scored here are identical to the rows the run was scored on. A diagnostic computed on the
wrong split is entirely plausible-looking and completely wrong.

### 4.3 Two new analysis tools

Added to `app/analysis.py`, `app/tools.py`, and `charts.py:_DISPATCH`, following exactly the
pattern `compare` established in Project 1.

| Tool | Purpose | Why the existing four cannot do it |
|---|---|---|
| `error_by_group(dataset_id, group_column, error_column)` | mean absolute error per group, as a bar chart — this is per-ticker error | `compare` aggregates across *two datasets*, not across groups within one |
| `line(dataset_id, x_column, y_columns)` | an ordered line plot of one or more series against a shared x | `scatter` draws unordered points; a learning curve and a residual trend both need the connecting line to be readable |

Both keep the existing tool contract exactly: a `dataset_id` plus column names, validated against
that dataset's profile by `validate_tool_call`. `line` is what renders the learning-curve frame
from §4.2, and it serves residuals-against-time better than `scatter` does.

`histogram`, `scatter`, and `correlation_matrix` cover EDA's distributions, pairwise
relationships, and correlation structure without change.

### 4.4 Two new endpoints

Both call `run_loop` synchronously, as `/chats` does.

```
POST /datasets/{id}/eda            -> 201 {finding_id, status: "draft", text}
POST /experiments/{id}/diagnostics -> 201 {finding_id, status: "draft", text}
```

**EDA.** Load `datasets.data_csv` via `dataset_io.load_csv`, profile it with the existing
`profile_dataframe`, run the loop with an EDA question, persist a `draft` finding keyed by
`dataset_id`.

**Diagnostics.** `mlflow.sklearn.load_model` on the run's artifact → `residual_frame` and
`learning_curve_frame` → profile each → run the loop over both → persist a `draft` finding keyed
by `experiment_id`.

The two derived frames are passed to `run_loop` as in-memory datasets with ephemeral ids. The loop
is already multi-dataset (issue #6), so two frames need no new plumbing. Neither is **ever**
inserted into `datasets`: D13 makes that table the single source-data path, and a derived
diagnostic frame is not source data.

Charts follow the parent design — rendered for the judge, not stored. Only the findings text
persists.

### 4.5 Read/write API for findings

```
GET   /findings?status=&source_type=      -> list, newest first
PATCH /findings/{id} {text?, status?}      -> the updated finding
```

`PATCH` carries the same D20 semantics as `PATCH /experiments/{id}`: sending `text` alone is an
edit, never an approval; approval requires an explicit `status`.

### 4.6 The persistence baseline

A `persistence` entry in `MODEL_REGISTRY`, so the baseline is a real logged run — on the
leaderboard, in the compare table, able to carry its own note, and retrievable by Phase 3.
"Did anything beat persistence" becomes sorting a column rather than reading prose.

`PriorValueRegressor(prior_column)` is a real `BaseEstimator`/`RegressorMixin` (so
`cross_val_score` can clone it) whose `predict` returns `X[prior_column]` unchanged. Its
`search_space` is empty, so `POST /experiments/tune` on it is rejected rather than running eight
identical trials. `prior_column` arrives through the existing `hyperparams` dict — no new request
field.

**The one structural change, and why it is needed.** `build_pipeline`
(`backend/app/training.py:205-225`) imputes and `StandardScaler`s every numeric column. A
persistence estimator inside that pipeline would receive a *scaled* prior value and could never
emit raw dollars — the baseline would be silently wrong rather than fail. So `ModelSpec` gains one
optional field:

```python
preprocess: bool = True
```

When `False`, `build_pipeline` returns a bare `Pipeline([("model", ...)])`, so the estimator
receives the DataFrame with its column names intact. Every existing spec keeps the default and is
unaffected.

**Scope.** Persistence is meaningful only for the temporal panel. It is not registered as
applicable to the cross-sectional components dataset, and nothing forces a user to fit it there.

---

## 5. Frontend

### 5.1 `/review` — one queue over three content types

A new route in `App.tsx`. Loads `GET /experiments?notes_status=draft` and
`GET /findings?status=draft`, normalising both into one row shape:

```ts
{ kind: 'note' | 'eda' | 'diagnostic', id, context, text }
```

Each row carries the context needed to judge it, collapsed by default: notes and diagnostics show
their run's params and metrics; EDA findings show the dataset name and row count.

`ExperimentsPage`'s existing per-run dialog is unchanged. It remains the right surface for editing
one note in the context of its run; `/review` is the right surface for working through a queue.

### 5.2 The opened-rows guard

Component state holds a `Set` of row ids expanded during this session. A row's bulk-approve
checkbox is enabled only once its id is in that set. Unopened rows remain selectable for
**reject** — rejecting unread text is a coherent action; approving it is not.

The bulk bar states the constraint rather than silently ignoring rows:
*"Approve 3 selected — 2 more need opening."*

**What this does and does not prove.** It proves the text was rendered on screen. It does not
prove anyone read it. It removes the accident — one select-all click approving 32 unread drafts —
not the intent. That limitation is stated here rather than left implied, because Phase 4's eval
harness treats approved rows as known-relevant ground truth, and a rubber-stamped batch corrupts
the measurement silently.

### 5.3 The diff, and its asymmetry

Findings carry `original_text`, so their diff is permanent: the model's words against the human's,
still visible later.

Experiment notes have no such column, so a note's diff is the stored draft against the current
textarea contents, and it is gone once saved. This asymmetry is deliberate — adding
`original_notes` to a table 2a just shipped is not worth the symmetry. If note provenance is
wanted later, it is a one-column migration.

### 5.4 Bulk approval semantics

Issues N `PATCH`es and reports partial failure honestly — *"approved 4 of 6; e17 and e23 failed"* —
rather than rolling back or claiming success.

---

## 6. Error handling

| Case | Response |
|---|---|
| EDA or diagnostics on an unknown id | 404 |
| Diagnostics on a `FAILED` run | 409 — there is no logged model to load |
| Diagnostics where the MLflow artifact is missing | 409, naming the run and the artifact path |
| Diagnostics on a **classification** run | 409 — residuals are regression-only; 2b scopes to the panel |
| MLflow unreachable | 503, matching `GET /experiments` |
| Approving an empty finding | 422, mirroring the existing empty-note guard |
| Loop failure mid-generation | the same mapping `/chats` uses; **no partial finding is written** |

---

## 7. Testing

Everything runs on SQLite with no API key, as now.

- `run_loop` is monkeypatched on each new route module, exactly as `backend/tests/test_chats.py:42`
  does for `/chats`.
- `residual_frame` is tested directly against a hand-built frame. The assertion that matters is
  that the split it reproduces is identical to what `split_frame` produced at training time.
- `learning_curve_frame` is tested for shape and monotonic `train_size`, and for using
  `TimeSeriesSplit` when a `time_column` is given — a learning curve built on shuffled folds for a
  temporal run reports optimistic scores at every training size.
- `PriorValueRegressor` is tested **through the pipeline**, not in isolation — that is what catches
  a regression if anyone flips `preprocess` back to the default.
- `app/findings.py` gets unit tests for `source_id` validation and every status transition,
  including the empty-approval 422.
- The two new analysis tools get the same treatment the existing four have: chart bytes produced,
  and `validate_tool_call` rejecting bad args.
- `/review` gets frontend tests with mocked fetch, including the opened-rows guard (approve
  disabled until expanded) and partial-failure reporting.

**Known gap.** The chunk-table migration executes only on Postgres — SQLite uses
`Base.metadata.create_all` — so its correctness is verified by running `make migrate` against the
dev Postgres, not by a test. This is the same limitation every existing migration has.

---

## 8. Exit criteria

Carried from the overall plan §3b, made concrete:

1. At least one **approved** EDA finding exists for `revenue-nowcast.csv`.
2. At least one **approved** diagnostic interpretation exists for a tuned run.
3. The persistence baseline is a logged experiment, visible on the leaderboard next to the tuned
   models — **whether or not anything beats it**.
4. `experiment_note_chunks` is migrated to `source_type` + `source_id` + `status`, verified by
   `make migrate` against Postgres.
5. `/review` supports bulk approval under the opened-rows guard, and a draft-vs-edit diff.
6. CI green.

**On the baseline.** 224 rows is a small panel with a ~30-row holdout. If nothing beats
persistence, that is the finding, and it gets written down rather than buried. The deliverable is
a working experiment-tracking system, not a winning model.

---

## 9. Decisions recorded

| # | Decision | Alternative rejected |
|---|---|---|
| D22 | EDA findings and diagnostics live in a new `findings` table; `experiments.notes` is untouched | One table for all reviewable text — rejected for the cost of migrating live rows and breaking a route 2a just shipped |
| D23 | Both are generated by **endpoints** calling `run_loop`, like `/chats` | A script like `seed_experiment_history.py` — rejected because nothing in the UI would then generate anything |
| D24 | Diagnostics loads the **logged MLflow model**; a missing artifact is a 409, never a silent refit | Refitting from logged params — rejected because a close-but-different model reported as the scored one is the worse failure |
| D25 | The persistence baseline is a `MODEL_REGISTRY` entry, reached via `ModelSpec.preprocess = False` | Computing it inside diagnostics — rejected because the number would live only in prose, off the leaderboard and out of the compare table |
| D26 | Bulk approval is gated on the row having been opened in this session | Unconstrained bulk approve — rejected because Phase 4 treats approved rows as ground truth, and a rubber stamp corrupts that silently |
| D27 | **Amends D19.** "No new machinery" holds for the LLM layer — the loop, judge, validation, and rendering paths are untouched — but two analysis tools (`error_by_group`, `line`) are added | Building diagnostics from the existing four tools — rejected because per-ticker error and learning curves are simply not expressible, so 2b.2 would ship with two of its four items quietly dropped |
