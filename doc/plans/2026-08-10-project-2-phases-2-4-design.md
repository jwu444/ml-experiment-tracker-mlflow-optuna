# Project 2 — Phases 2–4 Design

**Status:** Approved (brainstorm), 2026-08-10.
**Parent design:** `doc/project-2-ml-experiment-tracker-design.md` (approved 2026-08-04).
**Program plan:** `doc/plans/2026-08-05-project-2-overall-implementation-plan.md`.
**Phase 1 plan (complete):** `doc/plans/2026-08-05-project-2-phase-1-foundations.md`.

This document does not replace the parent design. It records the decisions Phase 1's
outcomes forced, and specifies the module boundaries, interfaces, and test strategy for
Phases 2–4 at the level the parent design deliberately left generic.

Phase 2 gets its own task-by-task implementation plan immediately. Phases 3 and 4 get
theirs when they start — their detail depends on artefacts that do not exist yet (real
experiment notes, real retrieval failures), and a plan written against guesses is worse
than one written on time.

---

## 1. What Phase 1 changed

> **Revised 2026-08-11** after mentor review (`doc/plans/project-2-phase-2-4-design-comments.md`).
> Facts 8–10 below arrived on `main` in `1287fcc`, `50d7057`, `66e0209` *after* this document
> was first written against `730fe46`, which is why the original §1 read as stale. D12 is
> amended and D18–D21 are new. Phase 2 is now split into **2a (pipeline)** and
> **2b (enrichment)**.

Ten facts from the shipped repo that the 2026-08-04 design could not have known:

1. **CI exists and is SQLite-only.** `.github/workflows/ci.yml` runs `make check` (backend)
   and type-check/test/build (frontend) on push and PR to `main`. There is no service
   container and no secret in the environment. Every `Settings` field has a default, which
   is why the job needs neither.
2. **The embedding column is already dialect-split.** `experiment_note_chunks.embedding`
   is `Vector(512).with_variant(JSON(), "sqlite")`. The width is real; the provider was
   not chosen.
3. **MLflow's schema is fenced off.** `backend/alembic/env.py` carries an `app_schema_only`
   `include_object` filter; without it autogenerate proposes dropping 59 MLflow tables.
4. **The ingested dataset is cross-sectional.** `video-card.csv` columns are
   `name, price, chipset, memory, core_clock, boost_clock, color, length` — **no date
   column**. `price` is null in 80.8% of video-card rows and 61.3% of CPU rows, leaving
   1,275 and 547 usable rows.
5. **A second, larger data layer arrived on `main`** from a concurrent contributor:
   `data-sources/`, ~50 CSVs across 12 sources with a provenance/licence catalogue. It
   includes genuine time series (daily equities for 17 semiconductor and OEM firms, FRED
   PPI, WSTS billings, consumer RAM prices 1957–2015) and **duplicates** the pc-part tables
   that `make data-fetch` downloads.
6. **`scikit-learn` is present only transitively**, pulled in by `mlflow` (verified:
   `sklearn 1.9.0` via `mlflow 3.15.1`).
7. **Jaeger already accepts OTLP.** `docker-compose.yml` sets `COLLECTOR_OTLP_ENABLED=true`
   and publishes 4317 (gRPC) and 4318 (HTTP) alongside the 16686 UI, so Phase 3's exporter
   has a destination without touching compose.
8. **`README.md` now carries five exploratory ML question candidates** (`66e0209`), each
   mapped to sources actually in the catalogue. They supersede this document's original
   framing of §2's driving question as a single target column.
9. **A dense GPU price dataset exists** (`50d7057`):
   `data-sources/gpu-prices-prediction/gpu_specs_prices.csv`, 311 rows, **0% null price**.
   It removes the null-target problem for the cross-sectional GPU case — but see fact 10.
10. **Almost nothing in that file is numeric on read.** Verified with pandas: **13 of its 14
    columns parse as `object`**. `price` is the string `"$1,289.99 "`; the spec columns carry
    their units (`" 24 GB "`, `" 335 mm "`, `" 1395 MHz "`). Only `used` is an `int64`. The
    same pattern holds across the catalogue. **No dataset here is trainable as ingested**,
    which is what D18 exists to fix — and it is why "0% null" is not the same as "ready".

---

## 2. Decisions resolved here

### D12 (amended 2026-08-11) — Both task types, drawn from the README candidates.

**Superseded:** the original D12 shipped `price ~ specs` cross-sectional regression alone and
left the temporal question open. That was written before fact 8; the README now defines five
candidates grounded in the catalogue, and the driving question is answerable.

Phase 2 ships **regression and classification**, in that order:

| | Task | Candidate | Target | Why this one |
|---|---|---|---|---|
| **First** | Regression | **#4 — company revenue nowcasting** | NVDA/AMD/INTC next-quarter revenue from stock momentum + WSTS billings + macro | Labels are dense — no null-target fighting while `app/training.py` is still new |
| **Second** | Classification | **#1 or #3 — supply-shock / macro → price direction** | `sign(price[t+1] − price[t])` as up/down/flat | The domain's headline question; produces the richest notes for Phase 3 to retrieve |

Both are **temporal**, which is the consequential part: it makes §3.6's evaluation
methodology load-bearing rather than boilerplate (see the leakage note there). Candidate #4
was chosen over the zero-join `gpu_specs_prices.csv` deliberately — the join is itself a
learning goal, and doing it first means the wide-table contract is proven before
classification depends on it.

**Two sizing facts, verified, that the plan must respect:**

- `sec-edgar-revenue/` contains AAPL, AMD, DELL, HPQ, INTC, NVDA — **there is no Micron
  file**, despite README candidate #4 naming it. Use INTC as the third ticker, or source
  Micron from `memory-market/`. The README should be corrected.
- Quarterly rows across NVDA/AMD/INTC total 332, but NVDA alone shows 167 rows across ~74
  quarters: these are **restatements**, and deduplicating to the latest `filed` per period
  leaves **≈150 rows**. With a ~30-row test split, differences in RMSE between two models
  will frequently sit inside the noise band. Runs therefore report **CV standard deviation
  alongside the point metric**, and "which model is best" is never read off a single number.

**Consequence:** the parent design's §2 driving question is now in Phase 2's scope via the
classification half, rather than staying open.

### D13 — One data path: the `datasets` table. `data-sources/` becomes its source.

`training.py` never touches the filesystem. The route loads `datasets.data_csv` by
`dataset_id` and parses it with `dataset_io.load_csv()` — the canonical parser — so training
sees exactly the dtypes the profiler saw at upload.

`scripts/fetch_component_data.sh` is repointed from `raw.githubusercontent.com` at the
committed `data-sources/pc-part-dataset/*.csv`. `make data-fetch` becomes offline, pinned,
and licence-shipping. `data/pc-parts/` and its `.gitignore` entry are deleted.

This closes the duplication CLAUDE.md flags as "unresolved, not intentional", and keeps D5's
`experiments.dataset_id` FK meaningful rather than perpetually NULL.

### D14 — Embeddings: Voyage AI. `EMBEDDING_DIM` stays 512.

Anthropic publishes no embeddings API, so D6 requires a provider the project did not have.
Voyage is Anthropic's recommended partner and its current models accept a configurable
output dimension including 512 (Matryoshka truncation), so the existing column width stands
and no migration is written.

`VOYAGE_API_KEY` cannot live in CI, so embeddings are mocked in tests — the same pattern the
repo already uses for `ANTHROPIC_API_KEY`. `app/embeddings.py` is the only module that
imports `voyageai`.

Rejected: OpenAI (a third LLM vendor for one function), and local `sentence-transformers`
(would work in CI, but pulls ~2GB of torch into the dependency tree and forces a 512→384
migration).

### D15 — D6 resolved: pre-filter, then rank.

`search_experiments(query, filters)` runs the structured stage first and the vector stage
second, over the survivors:

```
filters ──▶ SQL over app.experiments  ─┐
                                       ├─▶ candidate experiment_ids
filters ──▶ mlflow.search_runs()      ─┘        │
                                                ▼
query ────▶ embed ──▶ ORDER BY embedding <=> q
                      WHERE experiment_id IN (candidates)
                      LIMIT k
```

Metrics and hyperparameters live in MLflow, not in `experiments` (§7), so the structured
stage is an *intersection of two sources* joined on `mlflow_run_id` — not one SQL query.

It degenerates cleanly at both ends: no filters is pure semantic search, no query is a pure
structured listing. Both acceptance-criteria questions map onto it directly — "which model
performed best on dataset X" is filter-then-rank, "what hyperparameter ranges have I tried"
is the structured stage alone.

**Known cost:** a strongly relevant note inside a filtered-out experiment is invisible.
Accepted; Phase 4's evals will show if it bites.

Rejected: post-filter (selective filters can return zero after over-fetching, and tuning the
over-fetch factor is the fragile part) and RRF score fusion (needs both sides to produce a
*ranking*, but structured fields give a filter — any ranking signal would be invented).

### D16 — A third CI job covers the Postgres-only path.

`<=>` is Postgres-only, so the single most important query in the project is currently
untestable by any automated gate. A `backend-postgres` job with a `pgvector/pgvector`
service container runs only `@pytest.mark.postgres` tests. The fast SQLite `make check` job
and local `make test` are untouched.

Rejected: leaving it manually verified (a regression would surface only as bad Phase 4 eval
numbers, where it is hard to attribute), and moving the whole suite to Postgres (a
disruptive rewrite of 119 passing tests that discards the zero-setup default).

### D17 — Endpoints stay fast and keyless; enrichment is a second pass.

The parent design's Flow A embeds `notes` inline, step 3. Combined with Flow B's one-row-per-
trial rule and §3.11's requirement that notes be observation-grade, a 20-trial study would
make 20 Claude calls and 20 Voyage calls inside a single synchronous HTTP request — one to
two minutes, two API keys required to train a model, and a partial-failure mode that leaves
some trials noted and embedded and others not.

Instead: **`/train` and `/tune` write a short factual note and return.** They need no
Anthropic or Voyage key, which also keeps their tests free of LLM mocking. Enrichment is a
separate, resumable pass:

- `scripts/seed_experiment_history.py` (deliverable 2.7) runs the study, then writes
  observation-grade notes in a second loop.
- `app/embeddings.py`'s backfill indexes notes in batches (Phase 3), rather than Flow A
  indexing one at a time.

**This amends the parent design's Flow A step 3** from inline to batched. The trade-off
accepted is that history is briefly un-indexed between a run and its backfill — acceptable
because nothing reads `experiment_note_chunks` until the agent exists, and the backfill is
idempotent on `(experiment_id, chunk_index)`, which already carries a unique constraint.

### D18 (new 2026-08-11) — Data preparation is an offline step producing one wide CSV.

Fact 10 is the reason this decision exists: **no dataset in the catalogue is trainable as
ingested.** This is broader than joining. Candidate #4 needs a 4-way join; but even the
zero-join `gpu_specs_prices.csv` needs unit stripping and currency parsing before a single
`fit()` can succeed. Preparation is therefore its own step, not a footnote to training.

`scripts/prepare_dataset.py` runs **offline**, before ingestion, and emits one analysis-ready
wide CSV per candidate into `data-sources/prepared/`. It is responsible for:

1. **Type coercion** — strip units and currency (`" 24 GB "` → `24.0`, `"$1,289.99 "` →
   `1289.99`), parse dates, coerce numerics.
2. **Grain alignment** — the join keys are periods, not rows. Revenue is quarterly, stocks
   daily, WSTS monthly, `worldbank-macro` **annual and multi-country** (so it also needs a
   country filter). Everything is resampled to the target's grain — quarterly for #4 — with
   the aggregation named explicitly per column.
3. **Deduplication** — keep the latest `filed` per `(ticker, period_end)`, per D12's
   restatement finding.
4. **Label engineering** — `next_quarter_revenue = revenue.shift(-1)` for #4;
   `sign(price[t+1] − price[t])` bucketed to up/down/flat for #1/#3.
5. **Lag discipline** — every feature is lagged to information available at prediction time.
   A feature is admissible only if it was knowable at `t`; the target is at `t+1`. This is
   enforced in preparation, not in `training.py`, because it is a property of the table.

The output is an ordinary CSV uploaded through `POST /datasets`. **D13 is unchanged** —
`training.py` still reads only `datasets.data_csv` and still knows nothing about the domain.
Preparation is versioned by the same SHA-256 content hash as any other upload, so a run
always pins the exact prepared bytes it trained on.

**Why offline and not a route:** it is slow, iterative, and needs eyeballing. Making it a
request path would put pandas reshaping behind an HTTP timeout for no benefit, and would let
a bad join reach the database as though it were data.

### D19 (new 2026-08-11) — EDA and diagnostics reuse Project 1's loop; no new machinery.

The workshop's visualization and interpretation skills have been deferred twice. Phase 2b
closes that with two uses of the **existing** `app/loop.py` — no new LLM plumbing:

- **EDA before modelling.** Run the judge-gated loop over the prepared dataset to produce
  distribution, correlation, and missingness findings. Keyed by `dataset_id`.
- **Diagnostics after modelling.** Residual and error analysis on completed runs — where the
  model fails, not just how well it scores. Keyed by `experiment_id`. Given D12's ~30-row
  test split, this is where "the difference is inside the noise" gets stated in words.

Both produce text that Phase 3 indexes (D21). Charts stay unstored per the parent design;
only the findings text persists.

### D20 (new 2026-08-11) — LLM-authored text is a draft until a human approves it.

Nothing written by a model is treated as fact, and nothing unapproved is ever embedded.

`experiments.notes` and the D21 chunk table gain a `status` of `draft` | `approved` |
`rejected`, defaulting to `draft`. The seeding and EDA/diagnostics passes write drafts;
**only `approved` rows are eligible for embedding.** Review happens in `ExperimentsPage` — a
panel lists drafts with the run's params and metrics beside the proposed text, and the
reviewer approves, edits, or rejects.

Chosen over a CLI prompt in the seeding script because approval state belongs in the database
rather than in whoever happened to run the script: it survives interruption, is reviewable
later, and gives Phase 4's eval harness a defensible definition of "known-relevant". The cost
is a `status` column and a review panel, both small.

### D21 (new 2026-08-11) — RAG scope: three content types plus one static, and nothing else.

Amends D6/D14/D15's content scope. The vector index holds exactly:

| Content | Keyed by | Gate |
|---|---|---|
| Experiment notes | `experiment_id` | HITL-approved (D20) |
| EDA findings | `dataset_id` | HITL-approved (D20) |
| Diagnostic interpretations | `experiment_id` | HITL-approved (D20) |
| Research-question candidates (the five README entries) | none — global | static, embedded once |

**Explicitly rejected: embedding external tech/business/economic articles for style or tone
grounding.** It conflates fact-retrieval with style-grounding, and Phase 4's harness
(precision@k / recall@k / MRR) is scoped to known-relevant *experiments* — it cannot measure
prose quality, so the addition would be unmeasurable by construction. If domain grounding is
ever wanted (say, referencing the 2022 mining-demand collapse when explaining a price-
direction result), it needs its own narrow licensed source and its own stated measure of
whether it improves *correctness*.

**Schema consequence:** `experiment_note_chunks`'s hard FK to `experiment_id` cannot express
a `dataset_id`-keyed or global chunk. It generalizes to `source_type` + `source_id`, validated
in code rather than by a DB foreign key, plus the `status` column from D20. This requires a
migration against a table that is still empty — cheap now, expensive after Phase 3 fills it.
§7's column spec and Phase 3's module boundaries (§4) are updated accordingly.

Structured fields (params, metrics, `model_type`, dataset, status) stay **out** of the vector
index — D15's SQL/MLflow pre-filter stage already answers those, and duplicating them into
embeddings is how a retrieval layer starts returning fuzzy matches for exact questions.

---

## 3. Phase 2 — Training, MLflow, Optuna

> **Phase 2 is split (2026-08-11).** **2a** is the pipeline: preparation/join, dual-task
> training, MLflow, Optuna, and the experiments UI — a working, measurable path end to end.
> **2b** is enrichment: EDA, diagnostics, the HITL review panel, and the note-chunk
> migration. The split exists so the HITL mechanism is designed against real runs rather than
> imagined ones, and so there is a demonstrable milestone before Phase 3's dependencies land.
> Sections below are marked **[2a]** or **[2b]** where the distinction matters.

### 3.1 Module boundaries

The parent design's §4 has `training.py` fit the model *and* log to MLflow. Splitting that
is the one structural change this document makes, because a module touching sklearn, MLflow,
and the DB at once cannot be tested without all three.

| File | Responsibility | External boundary |
|---|---|---|
| `app/training.py` | `MODEL_REGISTRY`, `build_pipeline()`, `fit_and_score()` | sklearn only — no MLflow, no DB, no network |
| `app/experiment_log.py` | `log_run()`, `fetch_runs()`, `search_runs()` | **the only module importing `mlflow`** |
| `app/tuning.py` | Optuna `Study` driving the two above | — |
| `app/routes/experiments.py` | Four endpoints; owns all DB writes | — |

`experiment_log.py` as the sole MLflow boundary is the load-bearing part: Phase 3's D15
structured stage reuses `search_runs()` rather than reimplementing SDK access, and it is the
one thing route tests mock.

### 3.2 Interfaces

```python
# app/training.py — pure, deterministic, no I/O
@dataclass(frozen=True)
class TrainResult:
    status: str                    # "FINISHED" | "FAILED"
    metrics: dict[str, float]      # per task_type (§3.4); empty when FAILED
    params: dict[str, Any]         # resolved hyperparams actually used
    error: str | None
    model: Any | None              # fitted sklearn Pipeline, None when FAILED

@dataclass(frozen=True)
class ModelSpec:
    task_type: str                 # "regression" | "classification"
    factory: Callable[..., Any]
    search_space: SearchSpace
    metrics: Callable[[Any, Any], dict[str, float]]
    objective_metric: str          # e.g. "cv_rmse" | "cv_f1_macro"
    direction: str                 # "minimize" | "maximize" — per entry, not global

MODEL_REGISTRY: dict[str, ModelSpec]   # keyed by model_type; task_type is a field

def build_pipeline(model_type: str, hyperparams: dict, numeric: list[str],
                   categorical: list[str]) -> Pipeline: ...

def fit_and_score(model_type: str, hyperparams: dict, df: DataFrame, target: str,
                  features: list[str], time_column: str | None) -> TrainResult: ...

# Returns (mean, std) — the std is required by §3.6, not optional decoration.
def cv_objective(model_type: str, hyperparams: dict, df: DataFrame, target: str,
                 features: list[str], time_column: str | None) -> tuple[float, float]: ...

def infer_feature_columns(df: DataFrame, target: str, max_cardinality: int) -> list[str]: ...
```

`time_column` is what makes §3.6's chronological split possible. When it is `None` the data
is treated as cross-sectional and a shuffled split is used; when it is set, the frame is
sorted by it and both the holdout and `TimeSeriesSplit` operate on that order. It is passed
explicitly rather than sniffed from dtypes, because guessing which column is "the" time axis
is exactly the kind of silent wrong answer that produces leakage.

`infer_feature_columns` takes the **DataFrame**, not the profile — see §3.3.

`suggest_params(trial, model_type)` was listed here in an earlier draft but belongs in
`app/tuning.py`: it is the one function that needs an `optuna.Trial`, and keeping it out of
`training.py` is what lets that module be imported and tested without optuna. It still reads
its bounds from `MODEL_REGISTRY`, so `/train` and `/tune` cannot disagree about what a
hyperparameter means.

**Study direction comes from the registry entry**, not from a constant. An earlier draft
created every study with `direction="minimize"` on the grounds that `cv_objective` returns
RMSE. Under the amended D12 that is wrong for the classification half, and wrong silently: a
minimised `f1_macro` study selects the *worst* model and reports it as best.

```python
# app/experiment_log.py — the MLflow seam
@dataclass(frozen=True)
class RunData:
    run_id: str
    status: str                    # MLflow's own status string
    params: dict[str, str]         # MLflow stores params as strings
    metrics: dict[str, float]

def log_run(experiment_name: str, model_type: str, task_type: str, params: dict,
            result: TrainResult, dataset_id: str | None, dataset_version: str | None,
            target: str, features: list[str]) -> str: ...          # -> mlflow_run_id

def fetch_runs(run_ids: list[str]) -> dict[str, RunData]: ...      # one batched call

def search_runs(metric_filters: list[str] | None,
                param_filters: list[str] | None,
                statuses: list[str] | None) -> list[str]: ...      # -> mlflow_run_ids
```

### 3.3 Staying domain-agnostic

No column name is hard-coded. Requests carry `target_column` and optional
`feature_columns`. When features are omitted they are inferred: numeric columns, plus
categoricals with cardinality at or below `profile_max_cardinality`, excluding the target and
high-cardinality identifier-shaped columns (`name`). Pointing the endpoint at a different CSV
requires no code change.

> **Corrected 2026-08-11.** An earlier draft inferred features from the stored
> `profile_json`, asserting a `n_unique` key per column. **That key does not exist** —
> `profiler.py:46` emits `{name, dtype, n_null}` and nothing else, so every categorical would
> have been silently dropped, including `chipset`.
>
> The fix is to infer from the **DataFrame**, which the route has already loaded via
> `load_csv()`, rather than from the profile. Beyond fixing the missing key, this avoids a
> second failure mode: the profiler's `categorical_summary` — the only place cardinality is
> implicitly recorded — is emptied to `{}` whenever a profile exceeds its token budget and
> degrades. Feature selection would then quietly become numeric-only, on large datasets only,
> with no error. The profiler's field set is tuned for LLM context budgeting and was reviewed
> as such; feature selection should not constrain it, and `nunique()` on a DataFrame already
> in memory is exact and cheap.

### 3.4 Model registry — keyed by task type (amended 2026-08-11)

D12 now requires classification as well as regression, so a registry entry carries its
`task_type` and the registry is keyed by `(task_type, model_type)`:

| `task_type` | `model_type` | Search space |
|---|---|---|
| `regression` | `ridge` | `alpha` log-uniform 1e-3 … 1e3 |
| `regression` | `random_forest` | `n_estimators` 50–400, `max_depth` 2–20, `min_samples_leaf` 1–10 |
| `regression` | `gradient_boosting` | `n_estimators` 50–400, `learning_rate` log 1e-3 … 0.3, `max_depth` 2–8 |
| `classification` | `logistic` | `C` log-uniform 1e-3 … 1e3 |
| `classification` | `random_forest_clf` | as above |
| `classification` | `gradient_boosting_clf` | as above |

Each entry supplies the estimator factory, its search space, **its metric set, and its
optimisation direction**, so `/train` and `/tune` can never disagree about what a
hyperparameter means or which way is better:

| `task_type` | Metrics | Optuna objective | Direction |
|---|---|---|---|
| `regression` | `rmse`, `mae`, `r2` | `cv_rmse` | minimise |
| `classification` | `accuracy`, `f1_macro`, `roc_auc` (binary only) | `cv_f1_macro` | **maximise** |

Direction is a property of the registry entry, not a constant. The earlier draft hard-coded
`direction="minimize"` on the reasoning that "cv_objective returns RMSE, so every study
minimises" — true then, wrong the moment classification exists, and wrong in a way that would
have produced *worst*-model selection with no error message. `f1_macro` is the classification
default because D12's up/down/flat labels are unlikely to be balanced.

Preprocessing lives inside the sklearn `Pipeline`: median imputation and
`OneHotEncoder(handle_unknown="ignore")`. One object is fit, scored, and logged.

### 3.5 What gets recorded where

§7 of the parent design says params and metrics are never duplicated into `experiments`.
That leaves several things with no stated home:

| Fact | Home | Why |
|---|---|---|
| `target_column`, `feature_columns` | MLflow **params** | Without these, "which model performed best" silently compares runs trained against *different targets*. They are as much a hyperparameter of the run as `alpha` is. |
| Resolved hyperparameters | MLflow params | Already the design's intent |
| `task_type` | MLflow **params** | Added 2026-08-11 (D12). Metric names alone do not identify the task, and a mixed history must be filterable by it — a regression and a classification run are not comparable, however similar their tags look. |
| Task metrics (§3.4) | MLflow metrics | Holdout values; the CV score is logged separately (`cv_rmse` / `cv_f1_macro`) so tuning and reporting are distinguishable |
| **CV standard deviation** | MLflow metric `cv_std` | Added 2026-08-11 (§3.6). At ~30 test rows, a point metric without its spread invites rankings the data does not support. |
| `time_column`, split strategy | MLflow params | Added 2026-08-11. Records whether a run was split chronologically or randomly — otherwise a leaked run and a sound one are indistinguishable in history, which is the failure that would quietly poison Phases 3–4. |
| Fitted `Pipeline` | MLflow artifact via `mlflow.sklearn.log_model` | D4's `mlruns/` |
| Run status | MLflow run status | Set to `FAILED` via `end_run(status=...)` on a failed fit |
| `dataset_version` | **`experiments.dataset_version` = the dataset's `content_hash`** | D13 routes everything through the `datasets` table, which would otherwise leave D5's fallback column permanently NULL. Populating it with the SHA-256 content hash pins a run to the exact bytes it trained on, which is what a version string is for. |

**MLflow experiment naming.** MLflow groups runs into its own `experiments` table, and that
grouping was unspecified. Convention: **one MLflow experiment per Optuna study**, named
`tune-{model_type}-{iso8601}`, so a study is one browsable unit in `mlflow ui`; every
`POST /train` call lands in a single shared `adhoc` experiment. `experiment_name` is
therefore a parameter of `log_run`, not a global.

**Optuna's own storage is in-memory.** `optuna.create_study()` is called without a
`storage=`, so there is **no third schema** — MLflow is the durable record of every trial,
and the `Study` object lives only for the duration of the request. This is only viable
because studies are synchronous and bounded (§3.8); resumable studies would need a storage
backend and are not in scope.

### 3.6 Evaluation methodology — temporal (rewritten 2026-08-11)

Rows with a null target are dropped explicitly.

**Optuna's objective is a mean cross-validated score on the train split; reported metrics come
from a held-out test split the study never sees.** Tuning against the test set and then
reporting that same test set is an invalid number, and experiment quality is this project's
whole subject.

**The split must be chronological, and this is not a detail.** The original draft used
`train_test_split(...)` and `KFold(shuffle=True)` — both shuffle by default. That was
defensible when D12 was cross-sectional. Under the amended D12 **every candidate is a time
series with a next-period target**, and a shuffled split trains on 2025 to predict 2024.
The consequence is not a slightly optimistic number; it is that *every metric in the
experiment history is inflated by an unknown amount*, and Phases 3 and 4 are built on top of
that history. So:

| Concern | Rule |
|---|---|
| Holdout | The **last** `train_test_size` fraction by time. Never random. |
| Cross-validation | `TimeSeriesSplit(n_splits=cv_folds)` — expanding window, never `KFold`. |
| Features | Lagged to information available at `t` for a target at `t+1` (enforced in D18's preparation, since it is a property of the table). |
| Grouping | Panel data (three tickers) splits on the **time axis**, not on rows, so one ticker's future never trains a fold that predicts another's past at the same date. |
| Scaling/imputation | Fit inside the `Pipeline` on train folds only — already true, and it matters more here. |

Determinism no longer comes from a shuffle seed, because there is no shuffle: an ordered split
is reproducible by construction. `train_test_seed` is retained only for estimators with
internal randomness (`random_forest`'s bootstrap, `gradient_boosting`'s subsampling).

**Reported alongside every metric: the CV standard deviation across folds.** Per D12's sizing,
the test split is ~30 rows, so two models can differ on RMSE while being indistinguishable.
Recording only the point estimate would let the seeded history assert rankings the data does
not support — and Phase 4 would then evaluate retrieval against claims that were never true.

### 3.7 API surface

| Endpoint | Request | Response |
|---|---|---|
| `POST /experiments/train` | `model_type, hyperparams, dataset_id, target_column, feature_columns?, notes` | `{experiment_id, mlflow_run_id, status, metrics}` |
| `POST /experiments/tune` | `model_type, dataset_id, target_column, feature_columns?, n_trials, search_space?, notes` | `{n_trials, best_experiment_id, best_metrics, trials[]}` |
| `GET /experiments` | `?model_type=&dataset_id=&status=&limit=&offset=` | list, newest first |
| `GET /experiments/{id}` | — | detail + full notes |

Both GETs merge our columns with MLflow params/metrics through **one batched `fetch_runs`
call**. A per-row SDK lookup would be an N+1 across a process boundary.

**`status` has no column to filter on.** `experiments` carries no status — it lives in
MLflow. So `?status=` resolves first, through `search_runs(statuses=[...])`, into a candidate
`mlflow_run_id` set that is intersected with the SQL query before pagination is applied.
That is **precisely the structured stage D15 specifies for the agent**, so Phase 2 builds the
intersection helper once and Phase 3 reuses it rather than reimplementing SDK access. The
cost is a round trip on the most common filter, and it is the reason `?status=` cannot be a
plain indexed `WHERE`.

**Degradation when the tracking store is unreachable.** A `GET` must not 500 because MLflow
is down: the structured fields are ours and always available. Both GETs return our columns
with `params` and `metrics` as `null` plus an explicit `mlflow_available: false` flag, and
`?status=` returns 503 — it is the one filter that cannot be answered without MLflow.

### 3.8 Guardrails (parent design §8)

- **A failed fit returns 200 with `status: "FAILED"`** and still inserts an `experiments`
  row plus an MLflow run tagged `FAILED`, so the failure is queryable history. Only
  malformed requests (unknown `model_type`, missing dataset, target not a column) are 4xx.
- `n_trials` is clamped by `optuna_max_trials` (50), with `optuna_trial_timeout_s` (60) and
  `optuna_study_timeout_s` (600).
- Studies run **synchronously**. Twenty trials over 1,275 rows takes seconds; a job queue
  would be unused machinery.
- **`mlflow_tracking_uri` fails fast at training time when empty.** Verified against the
  pinned `mlflow 3.15.1`: an empty value does *not* silently write a local `./mlruns` file
  store — MLflow now **refuses the filesystem tracking backend entirely** and raises a
  maintenance-mode error naming `sqlite://` and database URIs as the supported options. The
  guard therefore trades a confusing library-internal traceback for a clear message; it is
  not preventing silent data loss.

### 3.9 New `Settings` fields

`optuna_max_trials=50`, `optuna_trial_timeout_s=60`, `optuna_study_timeout_s=600`,
`train_test_size=0.2`, `train_test_seed=42`, `cv_folds=5`.

Added 2026-08-11: `default_task_type="regression"` (D12) and
`hitl_require_approval=True` (D20 — when `False`, drafts are auto-approved; **intended for
tests only**, never for the seeding path, since auto-approval would defeat the gate the
decision exists to create).

### 3.10 Frontend

**[2a]** `ExperimentsPage` at `/experiments`: list, filter by model type, task type, and
dataset, and side-by-side comparison of selected runs. Reuses the existing `ui/` primitives and
CSS tokens; `api.ts` gains `listExperiments` and `getExperiment`. This is D9's public
equivalent of the MLflow UI. Comparison shows the CV standard deviation next to each point
metric (§3.6), so two runs whose difference is inside the noise band read that way on screen.

**[2b]** A **review panel** on the same page implements D20: it lists `draft` text — seeded
notes, EDA findings, diagnostics — beside the originating run's params and metrics, and offers
approve / edit / reject. `api.ts` gains `listDrafts` and `reviewDraft`. Nothing reaches the
vector index without passing through it.

### 3.11 Seeded history (2.7) and the notes problem

Deliverable 2.7 runs a genuine Optuna study of at least 20 trials over the Phase-1 dataset,
via `scripts/seed_experiment_history.py` (D17).

`experiments.notes` is the **only** text Phase 3 embeds and the only thing Phase 4 measures
retrieval against. If notes are templated from the structured fields (`"ridge with
alpha=0.3"`), semantic search over them is circular and the retrieval evals measure nothing —
every query would be answerable by the structured stage alone, and D15's vector stage would
be decoration.

Notes must therefore carry information not already in the structured fields — observations,
comparisons against prior trials, hypotheses about why a configuration behaved as it did. The
script's second pass makes one Claude call per trial, given that trial's params, its metrics,
and its delta against the study's best-so-far, with a handful of hand-written notes mixed in
so the eval set is not measuring one generator's voice against itself.

The script is **resumable and idempotent**: it skips trials whose `experiments.notes` is
already non-empty, so a mid-run API failure costs only the remaining trials.

**Every generated note is a `draft` (D20).** The script never writes `approved`. Phase 2b's
review panel is what promotes text, and only promoted text is embedded. Two consequences worth
stating plainly:

- The hand-written notes mixed into the set are the *reviewer's* edits, which is a more honest
  source of variation than a second prompt — the eval set stops measuring one generator's
  voice against itself precisely because a human intervened.
- Deliverable 2.7's exit criterion changes from "≥20 runs with non-empty notes" to **"≥20 runs
  with *approved* notes"**. That is a slower gate on purpose: unreviewed model output is
  exactly the material that would make Phase 4's retrieval scores meaningless while looking
  fine.

### 3.12 Testing

`training.py` is tested against a 20-row synthetic frame — fast, deterministic, no services.
Tuning is tested at `n_trials=2` on synthetic data. Because D17 keeps Anthropic and Voyage
out of the endpoints entirely, no route test needs an LLM mock at all. Everything stays on
SQLite, so **Phase 2 needs no CI change**; D16's Postgres job lands with Phase 3.

**`experiment_log.py` is tested against real MLflow, not a mock**, using a
`sqlite:///{tmp_path}/mlflow.db` tracking store. The obvious choice — a `file://` store —
does not work: MLflow 3.15 rejects the filesystem backend. A per-test SQLite store is fast,
needs no service, and exercises the real SDK, which is worth more than a mock for the one
module whose entire job is SDK access. Route tests still stub `experiment_log`.

Also verified against 3.15.1: `search_runs(filter_string="attributes.run_id IN (...)")`
works, so §3.7's batched `fetch_runs` is a single call and not an aspiration.

---

## 4. Phase 3 — Retrieval, agent, tracing

| File | Responsibility | External boundary |
|---|---|---|
| `app/embeddings.py` | `chunk_text()`, `embed_texts()`, `index_source()`, backfill | **the only module importing `voyageai`** |
| `app/tracing.py` | OTel span helpers, OTLP exporter to Jaeger | opentelemetry |
| `app/agent.py` | Hand-rolled tool loop (D7) | anthropic |

**The chunk table is source-agnostic (D21).** `experiment_note_chunks` becomes:

| Column | Change |
|---|---|
| `experiment_id` FK | **Removed**, replaced by `source_type` + `source_id` |
| `source_type` | `experiment_note` \| `eda_finding` \| `diagnostic` \| `research_question` |
| `source_id` | The keyed id, validated in code per `source_type`; **nullable**, since `research_question` chunks are global |
| `status` | `draft` \| `approved` \| `rejected` (D20) — only `approved` rows are embedded |
| unique constraint | `(source_type, source_id, chunk_index)`, replacing `(experiment_id, chunk_index)` |

No DB-level foreign key, because the referent varies by `source_type` — the trade-off D21
accepts, mitigated by validating on write in one module. The migration runs while the table is
**empty**; deferring it past Phase 3 means backfilling live vectors instead.

**Chunking, honestly.** These notes are a paragraph. A plain size-threshold splitter with
sentence-boundary breaks is the right amount of machinery, and `chunk_index=0` will dominate
in practice — the column earns its keep only for the longer hand-written notes. Per D17
indexing is a **batched backfill**, not inline in Flow A; the unique constraint above makes
re-running it idempotent.

**Tracing is off by default** (`otel_enabled=False`), so `make test` needs no Jaeger and CI
is unaffected. The `loop.py` retrofit (3.3) proves the helpers on existing code before the
agent depends on them.

**The agent** mirrors `loop.py`'s shape: tool-arg validation before any execution (the same
discipline as `validate_tool_call()`), a `max_turns` cap, and a span per Claude call, tool
call, and retrieval. `search_experiments` implements D15; `get_experiment_detail` returns one
merged run. `POST /experiments/chat` returns `{answer, retrieved_experiments, trace}`.

**Testing.** Vector SQL runs in D16's `backend-postgres` job under `@pytest.mark.postgres`.
The agent's merge and validation logic is unit-tested on SQLite against a fake retriever.
Voyage and Anthropic are mocked in both.

---

## 5. Phase 4 — UI, evals, ship

Deliberately the thinnest section: its detail depends on history and retrieval failures that
do not exist yet.

- `ExperimentChatPage` — NL input, answer, retrieved-experiment cards, per-step trace, in the
  same spirit as Project 1's `PassTrace`.

  > **Superseded — already shipped before Phase 4 began.** This landed in 3.6b as
  > `AskPage` (`/ask`), with per-hit citations that deep-link to the page holding the
  > reviewed text. The outline's first Phase 4 task was complete on the day Phase 4
  > opened. Left in place rather than deleted: a document that quietly loses a claim
  > gives a later reader no way to tell it was reconsidered.

- A hand-labelled fixture mapping queries to known-relevant experiment ids, drawn from real
  Phase 2 runs.

  > **Superseded — "experiment ids" is the wrong unit (D43).** Written before D33 split
  > *experiment* (an investigation) from *run* (one attempt). `search_runs` returns
  > `(source_type, source_id)` spanning `note`, `diagnostic` and `eda`, and the last is
  > keyed to a **dataset** and has no experiment id at all — so a fixture labelled on
  > experiment ids could not address a third of the corpus. The shipped
  > `backend/eval/golden_set.yaml` labels `(source_type, source_id)`, the unit retrieval
  > actually returns.

- `make eval` reports precision@k, recall@k, and MRR, per-query and aggregate.

  > **Superseded in its unit — `k` counts sources, not chunks (3.4b).** The outline's `k`
  > predates that change and reads as a `k` of passages. As shipped, precision@k is a
  > precision over *answers*: a source is scored by its single best chunk, so one long
  > write-up cannot fill the budget and hide three other runs. The metric names are
  > unchanged; what they are computed over is not.

**`make eval` is repurposed, not replaced.** It is currently a stub for Project 1's
prose-keyword golden-set grader, which was never built — while CLAUDE.md carries a long
write-up describing that grader as though it exists. Rather than maintain two eval suites
where one is fictional, `make eval` becomes the retrieval suite and CLAUDE.md is corrected to
record that Project 1's grader was never written.

> **Done 2026-08-29 (Phase 4 Task 6).** `make eval` is the retrieval suite:
> `backend/eval/runner.py` grading precision@k, recall@k and MRR over
> `(source_type, source_id)` against `backend/eval/golden_set.yaml`. CLAUDE.md's
> `make eval` paragraph was rewritten in the same task — the Project 1-era text it
> replaced described grading tool selection, columns passed and keyword presence in
> chat prose, a suite that was never built. This is the sixth of the six supersessions
> the Phase 4 spec's §2 enumerates; the other five are the two risks in §7 and the
> three annotated bullets above.

---

## 6. Dependencies to add

| Package | Phase | Note |
|---|---|---|
| `scikit-learn` | 2a | Currently transitive via `mlflow`; pin it directly |
| `optuna` | 2a | Not installed |
| `voyageai` | 3 | Not installed (D14) |
| `opentelemetry-sdk` | 3 | Not installed |
| `opentelemetry-exporter-otlp-proto-http` | 3 | Not installed |

New environment variables: `VOYAGE_API_KEY`, `OTEL_EXPORTER_OTLP_ENDPOINT`. Both get
`.env.example` entries and safe defaults, so CI continues to need no secrets.

---

## 7. Open risks

1. ~~**Deployment and pgvector (4.6).** Render's Postgres supports the `pgvector` extension,
   but this is **unverified on their free tier**, and Fly would need a custom image. Check
   before Phase 4 starts, not during it.~~ **Resolved 2026-08-29** by the live deploy
   (`doc/deploy-runbook.md`): Render's free-tier Postgres does support `pgvector`, and the
   retrieval half works there. The check the risk asked for turned out to be necessary but
   not sufficient — the extension being *available* is not the same as it being *enabled in
   the restored database*. `pg_dump --schema=app --schema=mlflow` excludes `public`, where
   the extension lives, so the dump referenced `public.vector(512)` while carrying no
   `CREATE EXTENSION`; the restore therefore failed on a type that the server was perfectly
   capable of providing. `CREATE EXTENSION IF NOT EXISTS vector;` runs before the restore
   for that reason, and is not left to whatever the host happens to pre-install.
2. ~~**`mlruns/` is ephemeral on free-tier filesystems.** Already acknowledged by D4 and
   bounded by D10 — model artefacts do not survive a deploy. Acceptable while MLflow's own
   UI stays a local tool.~~ **Resolved 2026-08-29** by D48: artifacts live in object
   storage (Cloudflare R2) and `scripts/migrate_artifact_uris.py` rewrites MLflow's
   absolute artifact URIs to that root. "Acceptable" was wrong, and for a specific
   reason this risk did not name: D24 refuses to refit from logged params, because a
   close-but-different model reported as the one that was scored is the worse failure.
   So losing the artefacts does not make diagnostics *slower* — it makes
   `POST /runs/{id}/diagnostics` permanently 409 on every run logged before the deploy,
   for a whole feature, with no way back short of re-training and orphaning every id
   `curation.yaml` and `golden_set.yaml` refer to.
3. **Note quality is the hidden dependency** of the entire Phase 3–4 arc. See §3.11. D20's
   review gate is the mitigation.
4. ~~**Branch protection on `main` is still unset**, carried since Phase 1 Task 1. It was
   originally blocked by a GitHub Actions outage that has since resolved. The repo is now
   multi-contributor with a green CI, so nothing justifies deferring it further.~~
   **Closed won't-fix 2026-08-29.** It is impossible on this account, not deferred: the
   repository is private on a free plan, and the branch-protection API answers HTTP 403.
   Recorded here rather than dropped, and rather than carried into a fifth phase as an
   open action — a risk left open with no note reads as unexamined, and the next person
   re-tries the same 403. The standing mitigation is that CI runs on **every** pull
   request regardless of base (`.github/workflows/ci.yml`), so a stacked phase branch
   still gets signal; what is missing is only the enforcement that a red one cannot
   merge.
5. ~~**The temporal model has no plan yet.**~~ **Closed 2026-08-11** by the amended D12 and
   D18 — both Phase 2 candidates are temporal, and the join is a specified task.
6. **Statistical power is thin** (new 2026-08-11). D12's ≈150 rows leave ~30 in the test
   split. Model rankings will often be inside the noise band. Mitigated by reporting `cv_std`
   (§3.6) and by D19's diagnostics, but not eliminated — the honest framing is that Phase 2
   demonstrates a *sound comparison method*, not a competitive model. Any note claiming a
   decisive winner should be rejected at D20's gate.
7. **The join is the likeliest place to introduce silent error** (new 2026-08-11). Four
   sources at three different grains, with restatements and an annual macro layer. A quiet
   off-by-one in the `shift(-1)` would leak the label directly into the features and produce
   suspiciously excellent metrics. D18 puts preparation in a reviewable offline script for
   this reason, and the plan tests the lag boundary explicitly rather than trusting it.

---

## 8. Traceability to the workshop program overview's §3.2 acceptance criteria

Section references in the right-hand column are to *this* document.

| Criterion | Lands in |
|---|---|
| Log experiments; ask "which model performed best" / "what ranges have I tried" | §3.7, §4 |
| MLflow UI shows params/metrics/artifacts | §3.5, §3.10 `ExperimentsPage` (D9) |
| At least one Optuna study, logged to MLflow | §3.4, §3.11 |
| Agent retrieves relevant experiments and recommends next ones | §4 `app/agent.py` (`get_leaderboard`, D47), `app/leaderboard.py`, `prompts/agent.md` |
| Retrieval quality measured | `backend/eval/` (`make eval`), reports in `backend/eval/results/` |
| Agent traces inspectable | §4 `tracing.py` |
| CI passes on every PR | Phase 1 `ci.yml`; extended by D16 |
| README updated with new architecture diagram | Phase 4 doc-sync |
