# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

ML Experiment Tracker — Project 2 of a 3-project AI Engineering Workshop, forked from Project 1's CSV Analysis Assistant. The inherited Project 1 flow: upload a CSV, ask natural-language questions, get plots + statistics + LLM interpretation. Uses Claude with tool-calling over a fixed menu of pandas/plot functions, driven by a **judge-gated multi-pass loop** (`app/loop.py`, issue #9): an analyst pass picks/adds chart tools and writes an interpretation, the charts are rendered, and a separate judge pass scores the attempt against the real rendered output — iterating until the score clears a threshold or a pass cap is hit. Full-stack: **FastAPI** backend + **React/Vite/TypeScript** frontend (`frontend/`). **This repo is Project 2**, adding ML experiment tracking (MLflow + Optuna), retrieval over experiment history, and a hand-rolled agent loop. Project 2 deliberately does **not** add auth (design D2).

## Run the whole app

Two terminals. Set `ANTHROPIC_API_KEY` in `.env` first (`cp .env.example .env`) —
required for `/chat`. Backend: `make dev` (http://localhost:8000). Frontend:
`cd frontend && npm install && npm run dev` (http://localhost:5173, proxies
`/api → :8000`). Open http://localhost:5173. See `README.md` for the full
quickstart, testing walkthrough, and toolchain setup. See `doc/architecture.md`
for a diagrammed architecture overview.

## Commands (backend)

All commands require `poetry install` first. Run from the repo root. The project
pins Python **3.12** (`.python-version`); a fresh shell may need pyenv + Poetry on
`PATH` — see the Testing section of `README.md` for the toolchain setup and a manual-testing walkthrough.

```bash
make install        # install all deps (creates poetry.lock)
make check          # lint + format-check + type-check + test (the CI gate)
make test           # pytest only (ephemeral SQLite, no API key needed)
make lint           # ruff check backend
make format         # black backend (auto-fix)
make type-check     # mypy backend/app (strict)
make dev            # uvicorn with --reload (app-dir backend)
make migrate        # apply Alembic migrations (alembic upgrade head)
make migration m="…" # autogenerate a migration from app/models.py changes
make eval           # retrieval quality over a committed golden set (see below)

# Local dev services (Project 2). SQLite stays the zero-setup default and the
# test backend; Postgres is only needed for pgvector and MLflow work.
make db-up          # docker compose up: Postgres 16 + pgvector on :5433, Jaeger on :16686
make db-down        # docker compose down
make db-psql        # psql into the dev Postgres
make mlflow-init    # CREATE SCHEMA mlflow + mlflow db upgrade (run once, needs db-up)
make mlflow-ui      # MLflow UI against that store
make prepare-data   # rebuild data-sources/prepared/ from the committed snapshots (offline)
make data-fetch     # ingest the prepared panel + component CSVs (needs make dev running)
make seed-history   # seed 32 real runs + Claude-written draft notes (needs the above + a key)
make embed          # reconcile the retrieval index against approved notes/findings (needs VOYAGE_API_KEY)
```

**`make eval` — retrieval quality over a committed golden set (D43/D44).**
`backend/eval/runner.py` grades **retrieval only** — precision@k, recall@k, and
MRR over `(source_type, source_id)` — against `backend/eval/golden_set.yaml`,
reading through `retrieval.search_runs` exactly as `POST /agent/chat` does, so
what is measured is the production path and not a reimplementation that can
drift from it. It deliberately never grades answer quality: an LLM-judged
answer grade would put Claude on both sides of the scoring, which is the
circularity D44 exists to break — the Project 1-era description that used to
live here (grading tool selection, columns passed, and keyword presence in
chat prose) described a suite that was never built and is now wrong; the eval
surface this project actually ships is retrieval-only. Kept deliberately
separate from `make test` because it needs a real `VOYAGE_API_KEY` (on a cold
cache — `eval/cache.py`'s `CachingVoyageClient` makes repeat runs free) and
Postgres with pgvector, since the `<=>` similarity operator has no SQLite
equivalent. The golden set's 20 queries are **blind-drafted** (D44): written
from the leaderboard, run params, and metrics only, never from note or finding
prose, and labelled for relevance afterward — a query written while reading
the prose it should retrieve measures whether Voyage can match text that was
copied, not whether retrieval works, and the resulting numbers would not
distinguish the two. This rule binds anyone extending the set later, since a
set that is blind for its first 20 queries and prose-derived for the next 20
would report one number over two incomparable halves. `make eval
ARGS=--validate-only` checks every labelled source against the live index
without spending a Voyage call; an unreachable id is fixed rather than shipped,
since it would score 0.0 and read as a retrieval failure rather than a
data-entry bug.

Run a single test file:
```bash
poetry run pytest backend/tests/test_profiler.py -v
```

The pgvector half cannot run on SQLite, so it is marked and skipped by default:

```bash
POSTGRES_TEST_URL=postgresql+psycopg2://wavepoint:wavepoint@localhost:5433/wavepoint \
  poetry run pytest -m postgres -v
```
Without `POSTGRES_TEST_URL` those tests **skip**, which is why they run as their
own `backend-postgres` CI job against a `pgvector/pgvector:pg16` service rather
than inside `make check` — a job that silently skipped would be decoration.

## Commands (frontend)

Run from `frontend/`:

```bash
npm install         # first run only
npm run dev         # Vite dev server at :5173, proxies /api → :8000
npm test            # Vitest + React Testing Library (mocked fetch, no backend)
npm run build       # tsc type-check then production build
npm run type-check  # tsc --noEmit
```

`/ci-check [pr|branch]` — runs `make check` + the frontend CI job locally. GitHub
Actions now runs both jobs on every push to `main` and on **every** pull request
regardless of its base (`.github/workflows/ci.yml`) — phases land as stacks of
PRs targeting the previous task's branch, and `pull_request.branches` filters on
the base, so an enumerated list would leave a whole stack unchecked. So this is a fast pre-push check rather than the
only way to get CI signal, as it was while Actions was blocked by account
billing. See `doc/ci-check-skill-design.md`.

## Code layout

```
.github/workflows/ci.yml    # backend (make check) + frontend (type-check/test/build) on push to main + every PR
docker-compose.yml          # Postgres 16 + pgvector on :5433, Jaeger on :16686
Dockerfile                  # the API service image only — no secrets, no mlruns/ (D48); the SPA is a separate static site
docker-entrypoint.sh        # prepares the MLflow store at container start (free tiers have no pre-deploy hook), then
                            #   exports the tracking URI the prepare script prints — it carries MLflow's search_path,
                            #   and the bare fromDatabase string would resolve to `public`, not the schema just prepared
render.yaml                 # two Render services (runtime: static SPA + Docker API) — two origins, because one would
                            #   force every route under /api and rename /agent/chat, the path D42 argues for by name
scripts/
  prepare_dataset.py        # make prepare-data — offline join/label into data-sources/prepared/
  fetch_component_data.sh   # make data-fetch — POSTs the committed CSVs to /datasets
  seed_experiment_history.py # make seed-history — Optuna studies + Claude-written DRAFT notes (D17/D20)
  backfill_embeddings.py    # make embed — reconciles app.experiment_note_chunks against approved text (3.3b)
  apply_curation.py         # applies backend/eval/curation.yaml's approve/reject verdicts through PATCH /runs/{id} (D45)
  sweep_retrieval.py        # runs the pre-registered chunking/overfetch grid through eval/runner.py (D46)
  migrate_artifact_uris.py  # rewrites MLflow's ABSOLUTE artifact URIs to the s3:// root (D48) — three columns, see below
  prepare_mlflow_store.py   # CREATE SCHEMA mlflow + mlflow db upgrade, idempotent; run by docker-entrypoint.sh
data-sources/               # committed source-data snapshots + a catalogue README (see below)
  prepared/                 # generated model-ready panels (revenue_nowcast.csv) — do not hand-edit
.claude/
  skills/ci-check/SKILL.md  # /ci-check — runs backend+frontend CI checks locally
backend/
  app/
    main.py          # create_app() factory; /health route; CORS; includes datasets + chats routers
    config.py        # Settings (pydantic-settings); DATABASE_URL, anthropic_*, profile_*, llm_* (loop, issue #9), etc.
    models.py        # Dataset, DatasetColumn, Chat, ChatDataset, ChatMessage (+pass_count/judge_score/trace_json), Analysis, Experiment (an investigation, D33), Run (one training run, belongs to an Experiment, D34/D37), Finding, ExperimentNoteChunk (+EMBEDDING_DIM, +source_type/source_id)
    db.py            # engine, SessionLocal, init_db() (Alembic on PG, create_all on SQLite), get_session() DI
    dataset_io.py    # decode_csv() / load_csv() / hash_csv() — pure CSV (de)serialization + content-hash helpers
    profiler.py      # profile_dataframe() — bounded rich profile (see §4 constraints below)
    tools.py         # tool schemas (incl. compare, error_by_group, line) + validate_tool_call() — validates args vs. per-dataset profiles
    llm.py           # analyst/judge primitives: analyst_call, judge_call, image_block, stats_block; used by app.loop
    loop.py          # run_loop() — quality-gated analyst/judge loop (issue #9); returns LoopResult (+per-pass trace, system_prompt)
    analysis.py      # pandas/plot analysis functions incl. compare(), error_by_group(), line() (fresh Figure per call, Agg backend)
    charts.py        # _DISPATCH tool→fn map (incl. error_by_group, line) over a dict of per-dataset dfs; render_message_analysis() re-renders
    findings.py      # create_finding()/list_findings()/update_finding() — validates (source_type, source_id) against datasets|runs; freezes original_text
    diagnostics.py   # residual_frame() / learning_curve_frame() — derives the holdout via training.split_frame, never refits (D24)
    training.py      # ModelSpec/MODEL_REGISTRY (incl. persistence/PriorValueRegressor), prepare(), split_frame(), cv_splitter(), build_pipeline(), fit_and_score() — takes a DataFrame, never a path
    tuning.py        # run_study() + suggest_params() — Optuna search over a ModelSpec's space, synchronous inside the request
    experiment_log.py # MLflow I/O: log_run() writes, fetch_runs() reads N runs in ONE search_runs call, search_runs() filters
    ranking.py       # rank_runs() — orders one experiment's runs by its primary_metric; pure (metrics in, ranked order out), no DB/HTTP (D38)
    leaderboard.py   # build_leaderboard() — one investigation's ranked rows, extracted out of the route so the
                     #   agent's get_leaderboard tool reaches the same logic without importing HTTPException;
                     #   raises ExperimentNotFound, a LookupError — _execute already catches KeyError for an
                     #   unknown run_id, and a missing experiment reported as a missing run is a wrong message
    tracing.py       # configure_tracing() + span() — the only module importing opentelemetry; off by default (3.1)
    embeddings.py    # chunk_text()/embed_texts() — the only module importing voyageai; + backfill() and approved_sources(), the index reconciliation (3.3)
    retrieval.py     # two-stage retrieval (3.4): candidate_runs() resolves Filters relationally (D15/D31), search_runs() then embeds the query and groups chunks back into per-source Hits; get_run_detail() merges our row + MLflow
    agent.py         # the retrieval agent (3.5): TOOLS (search_runs, get_run_detail, get_leaderboard — D41/D47)
                     #   + validate_tool_call(), and run_agent() —
                     #   a hand-rolled Anthropic tool loop, separate from app/loop.py (D41)
    schemas.py       # Pydantic models: DatasetOut, ChatCreateRequest, ChatOut, ChatDatasetOut, ChatMessageOut (+trace), ChatHistoryOut, MessageTraceOut/PassTraceOut/AnalystPassOut/JudgePassOut, ExperimentOut/ExperimentCreateRequest/ExperimentPatchRequest, RunOut/RunDetailOut/RunPatchRequest, LeaderboardOut/LeaderboardRowOut, AgentChatRequest/AgentChatOut/RetrievedOut/AgentTraceOut/AgentStepOut
    sqlite_schema.py # attach_app_schema() — ATTACHes a second SQLite file as the `app` schema/catalog, shared by env.py, db.py, and tests/conftest.py
    routes/
      datasets.py    # POST /datasets (upload → validate → profile → persist, deduplicated by content hash), GET /datasets (list, newest first), GET /datasets/{id} (DatasetDetailOut — adds `columns`; the list route stays on DatasetOut), POST /datasets/{id}/eda (no body → run_loop → draft finding)
      chats.py       # POST /chats, POST /chats/{id}/messages, GET /chats/{id} — run_loop, persist (+pass_count/judge_score), re-render
      experiments.py # investigations (D33): POST /experiments, GET /experiments (filters), GET /experiments/{id}, PATCH /experiments/{id} (name/objective); launches runs INSIDE one: POST /experiments/{id}/train, POST /experiments/{id}/tune; GET /experiments/{id}/runs (ranked leaderboard, D38)
      runs.py        # run-level: GET /runs (filters, incl. experiment_id), GET /runs/{id}, PATCH /runs/{id} (notes + notes_status), POST /runs/{id}/diagnostics (no body → loads the logged model → draft finding)
      agent.py       # POST /agent/chat — the agent's one stateless endpoint, mounted at /agent (D42)
      shared.py      # load_training_frame() + merge_runs() — shared by routes/experiments.py and routes/runs.py, to avoid an import cycle between them
      findings.py    # GET /findings (status/source_type/source_id filters), PATCH /findings/{id} (text + status; approving an empty finding is a 422)
      models.py      # GET /models — serializes MODEL_REGISTRY (task_type, tunable, hyperparams, column_hyperparams) for the run form (#52)
  alembic/           # Alembic migration environment
    env.py           # wired to Settings.database_url + Base.metadata; schema-aware; app_schema_only guard keeps autogenerate off MLflow's schema
    versions/        # migration scripts (initial schema = 6 tables in the app schema; + experiments/experiment_note_chunks/findings; + the run-hierarchy split: rename experiments→runs (019c2ddeec73) → add a new experiments parent (747b57a1d7a5) → contract runs' now-inherited columns (7fd6e7527935), D33/D34/D37)
  tests/
    conftest.py      # client fixture — isolated SQLite DB per test via tmp_path
    test_config.py   # Settings parsing — pins the CORS-origin forms that must not stop the process booting (see below)
    test_*.py
  eval/              # make eval — retrieval quality, real API, deliberately NOT in make check (D43/D44)
    golden_set.yaml  # 20 blind-drafted queries labelled on (source_type, source_id) (D43/D44)
    curation.yaml    # the approve/reject verdict + reason for every run in the DB at curation time (34) + 6 findings (D45)
    metrics.py       # precision@k / recall@k / MRR over SOURCES — pure, no I/O, no app imports
    cache.py         # CachingVoyageClient — a client shim, not a change to app.retrieval; makes the sweep affordable
    runner.py        # reads through retrieval.search_runs exactly as POST /agent/chat does
    results/         # committed reports: baseline.md, sweep.md (the grid was committed before its numbers, D46)
frontend/            # React + Vite + TypeScript SPA
  src/
    api.ts           # fetch wrappers (uploadDataset, getDataset, createChat, get/postChat, listFindings, updateFinding, runEda, listExperiments, createExperiment, getExperiment, updateExperiment, getLeaderboard, listRuns, getRun, updateRun, runDiagnostics, listModels, trainRun, tuneRun, askAgent); VITE_API_BASE
    App.tsx          # routes: / (UploadPage), /c/:chatId (ChatPage), /datasets/:datasetId (DatasetPage), /experiments (ExperimentsPage), /experiments/:experimentId (ExperimentDetailPage), /ask (AskPage)
    pages/           # UploadPage (multi-file), ChatPage, DatasetPage (one dataset's columns + Run EDA + its EDA findings), ExperimentsPage (investigation list, D33), ExperimentDetailPage (one experiment's ranked leaderboard, model-type filter, compare, note review, diagnostics + the run's diagnostic findings), AskPage (ask the agent one question; each citation deep-links to the page holding its text, 3.6)
    components/      # AppShell (two-column collapsible shell; width="chat"|"upload"|"wide") and NavRail (the one nav surface: category → entity — Data, Machine learning, Agent), FindingsPanel (one source's findings, reviewed in place), QuestionBox, ChatTurn (role-styled bubble + optional `delivery` state), ChartList, StatsDetails, PassTrace (loop trace, tokenized per-pass UI, system prompt excluded), ErrorBanner, DatasetChips, NewExperimentDialog (start an investigation) and NewRunDialog (launch train/tune inside one, #52 — both share DialogForm.module.css)
    ui/              # tokenized primitive component library — Button, Input, Textarea, Card, Badge, Dialog, Skeleton, IconButton, ThemeToggle — + barrel index.ts
    styles/          # tokens.css (CSS-variable design tokens: color/type/spacing/radius) + global.css (base + focus-visible)
    theme.tsx        # ThemeProvider / useTheme() — dark mode
  vite.config.ts     # dev /api → :8000 proxy; Vitest config
prompts/
  system.md          # system prompt fed to Claude (the analysis loop)
  agent.md           # system prompt for the retrieval agent — cite sources, say so when empty (3.5)
doc/
  architecture.md                              # student-oriented architecture overview + diagrams (both halves: analysis + experiments)
  user-manual.md                               # task-oriented end-user guide (setup, chat, training, reviewing write-ups, troubleshooting)
  deploy-runbook.md                            # how the Render + R2 deploy was done, in order, incl. the manifest/CORS/artifact-URI failures
  project-1-csv-analysis-assistant-design.md   # approved design; read before changing architecture
  plans/2026-06-23-project-1-backend-foundation.md  # task-by-task backend plan with checkboxes
```

- Backend application code: `backend/app/` only. Backend tests: `backend/tests/` only.
- Frontend code and tests: `frontend/src/` (co-located `*.test.tsx`).
- Imports are absolute from `app` (e.g. `from app.profiler import profile_dataframe`).
- Line length: **100** (ruff + black both configured to 100).
- mypy is **strict** on `backend/app`.

## Non-obvious design decisions (read before touching these areas)

**No `users` table, no auth (Project 1 D4, reaffirmed by Project 2 D2).** A dataset `id` is its own shareable link. There is no user scoping, no login, no session. Do not add a `User` model or FK — Project 2 stays single-tenant, and `experiments` has no owner column.

**Raw CSV in Postgres, no object store (D5).** Uploaded data is stored verbatim as raw CSV text in `datasets.data_csv` (`Text` → `text` on Postgres, `TEXT` on SQLite) — the single durable copy. `load_csv()` is the one canonical parser used at both upload-profiling and later chart re-render, so both see identical dtypes. No parquet/pyarrow step, no S3/GCS/local-disk storage. Trade-off: no compression (a 50MB CSV stays ~50MB), bounded by the upload cap. The ephemeral filesystem on Render/Fly free tiers is intentionally avoided.

**Alembic is the schema authority on Postgres.** `app/models.py` is the source
of truth; migrations under `backend/alembic/versions/` translate it to the DB.
`init_db()` runs `alembic upgrade head` at startup for Postgres and falls back to
`Base.metadata.create_all()` only for SQLite (local default + tests). All tables
live in the `app` Postgres schema; the initial migration `CREATE SCHEMA`s it
(autogenerate does not). After changing a model, run `make migration m="…"`,
review the generated file, then `make migrate`. The legacy `backend/db/schema.sql`
is a Week-2 SQL-learning artifact and is **no longer** used to build the DB — do
not treat it as authoritative; it predates and diverges from the ORM.

**Renaming a table does not rename its indexes.** `ALTER TABLE … RENAME TO` moves
the table on both Postgres and SQLite and leaves every index — and, on Postgres,
the primary-key constraint — under its old name, because index names live in the
*schema's* namespace, not the table's. The old names survive, so nothing errors
and the rename looks clean; the damage shows up in the **next** migration. Alembic
batch mode reflects and recreates every index on the table it rebuilds, so a
stale index over a column that migration drops takes the whole batch down. The
`019c2ddeec73` → `747b57a1d7a5` → `7fd6e7527935` chain therefore re-points the
indexes explicitly in the rename step (`_INDEXES`, plus `ALTER INDEX
app.experiments_pkey RENAME TO runs_pkey` on Postgres only), and the contract
step drops `ix_app_runs_dataset_id` **before** its batch block and recreates it in
`downgrade()`. Two dialect traps when hand-writing this: SQLite qualifies the
INDEX name rather than the table (`CREATE INDEX app.ix_foo ON experiments (col)`),
and `ALTER INDEX` does not exist there at all. `test_migration_hierarchy.py`
exercises upgrade → downgrade → upgrade and asserts on index names for exactly
this reason.

**MLflow owns the `mlflow` schema; Alembic must never see it (Project 2 D4).**
The tracking store shares the app's Postgres. `backend/alembic/env.py` runs with
`include_schemas=True`, so without the `app_schema_only` `include_object` filter,
`--autogenerate` proposes dropping every MLflow table — 59 of them, as of the
version pinned here. Never model MLflow tables in `app/models.py` — read them
through the `mlflow` SDK, joined on `runs.mlflow_run_id`. Since the run-hierarchy split
(D33), `app.experiments` and `app.runs` correspond directly to MLflow's own
`mlflow.experiments` and `mlflow.runs` — the same shape, mirrored rather than reused, so
the `app_schema_only` filter still has to discriminate on schema, not name, to avoid
dropping MLflow's real tables.
Set up the store with `make mlflow-init`; browse it with `make mlflow-ui`.
`experiments.mlflow_experiment_id` records which MLflow experiment an
investigation's runs land in, and is written on the **first logged run**, not at
creation — `POST /experiments` is a plain database write and must not start
failing because the tracking store is down. Until that first run the two sides
are joined only by name (`experiment.name`, D35), which a rename of either would
silently break, so do not "simplify" by resolving the id lazily every time.
That name-join is also why **experiment names are unique**: `POST /experiments`
and a renaming `PATCH /experiments/{id}` both **409** on a name another row
already answers to. The constraint lives in the route (`_name_taken`), not in a
DB unique index, because it has to hold for the rename too and one check in one
place is easier to keep honest than a constraint plus an error translator. Two
investigations sharing a name would file their runs into the same MLflow
experiment and silently interleave two leaderboards.

**The embedding column is dialect-split.** `experiment_note_chunks.embedding` is
`Vector(512).with_variant(JSON(), "sqlite")` — `VECTOR(512)` on Postgres, `JSON`
on SQLite, because the whole test suite runs on SQLite. Vector *operators*
(`<=>`) are Postgres-only, so Phase 3's similarity search cannot be tested on
SQLite; test its SQL against Postgres and unit-test the merge logic separately.
The width (`EMBEDDING_DIM` in `app/models.py`) is **not** a firm commitment — the
provider is chosen in Phase 3, and the table is empty until then, so migrating to
a different width stays cheap.

**Postgres runs on port 5433, not 5432** (`docker compose`), to avoid colliding
with a system Postgres. `make db-up` / `make db-down` / `make db-psql`.

**One source-data path: the `datasets` table (Project 2 D13/D18).** `data-sources/` is the
committed, licence-shipping catalogue of snapshots (~50 CSVs across 12 sources, documented
in `data-sources/README.md`). Joining, coercing, and labelling happen **offline** in
`scripts/prepare_dataset.py` (`make prepare-data`), which writes wide, model-ready CSVs into
the committed `data-sources/prepared/`. `make data-fetch` then uploads
`prepared/revenue_nowcast.csv` and `pc-part-dataset/{video-card,cpu}.csv` into `datasets` via
`POST /datasets`. Nothing downloads at run time and nothing reads CSVs off disk at request
time, and the training code added in Phase 2a holds that line: `app/training.py` takes a
DataFrame, and `routes/shared.py`'s `load_training_frame()` (called from both
`routes/experiments.py` and `routes/runs.py`) parses `datasets.data_csv` with
`dataset_io.load_csv()`.
Adding a new training input means preparing it and uploading it, never adding a file path to
the request path. `scripts/` goes through the API for the same reason — `seed_experiment_history.py`
POSTs and PATCHes rather than touching the DB, so route validation is never bypassed.

**Training takes a DataFrame, never a path (design §3.3).** `app/training.py` is pure sklearn
plumbing and knows nothing about HTTP or the DB; the **route** parses `datasets.data_csv`.
Models live in a `MODEL_REGISTRY` of `ModelSpec`s, each carrying its estimator factory, its
Optuna space, and its `cv_scoring` string. Adding a model means adding a spec, not editing
the route. Categorical features are one-hot encoded inside the pipeline, so the encoder is
fit on training folds only — fitting it on the full frame before splitting leaks the test
distribution into the model, and the failure is invisible because every metric still looks
plausible.

Two MLflow facts that cost time to rediscover: a `file://` tracking store is **rejected** by
MLflow 3.x, so tests use `sqlite:///{tmp_path}/mlflow.db`; and
`search_runs(filter_string="attributes.run_id IN (...)")` works, which is why `fetch_runs` is
one call and not an N+1.

**The training path never calls Claude or Voyage (D17)** — `/experiments/{id}/train`,
`/experiments/{id}/tune`, and every read route stay LLM-free, so training needs no API
key, and note *enrichment* lives in `scripts/seed_experiment_history.py` rather than in a
route. Embedding calls are Phase 3's and are never made from a request.

Phase 2b's two **generation** endpoints are the deliberate, bounded exception (D23):
`POST /datasets/{id}/eda` and `POST /runs/{id}/diagnostics` call `run_loop`
synchronously inside the request, exactly as `POST /chats/{id}/messages` always has. That
is why `test_eda_route.py` and `test_diagnostics_route.py` mock `run_loop` while the
training route tests still need no LLM mock at all. Do not "fix" the generation endpoints
by moving the loop call out of the request path.

**Temporal data is split chronologically, never shuffled (design §3.6, D18).**
`POST /experiments/{id}/train` and `/tune` take an optional `time_column`. When it is present the
holdout is the tail of the sorted frame and cross-validation is `TimeSeriesSplit`; when it is
absent the split is random. The column itself is dropped from the features — it is the split
axis, not a predictor. A typo'd `time_column` is a **422**, not a silent fallback to a random
split, because the leaky version returns 200 with flattering metrics and nothing downstream
would notice. Every metric is reported with its cross-validation standard deviation: the
revenue panel is ~224 rows and a difference smaller than the fold spread is noise.

**Generated notes are drafts until a human approves them (D20).** `runs.notes_status`
is `draft` at creation from both flows (`POST /experiments/{id}/train` and `/tune`), and
only `PATCH /runs/{id}` with an explicit
`notes_status` moves it to `approved` or `rejected`. Writing note text through the same route
is deliberately **not** an approval — the seeding script writes `{"notes": ...}` and nothing
else, so its output cannot approve itself. An empty note cannot be approved (422), though it
can be rejected. Phase 3 embeds approved notes.

**Findings are a separate table from run notes (D22).** EDA write-ups and
diagnostic interpretations live in `app.findings`, keyed by `(source_type, source_id)` —
`datasets.id` for `eda`, `runs.id` for `diagnostic` (moved off `experiments.id` by the
run-hierarchy split, D33/D37 — a diagnostic is scored against one trained run, not the
investigation it belongs to). `source_id` carries **no
foreign key** because it addresses two tables; `app/findings.py` validates the reference
at write time instead. `original_text` is frozen at insert and never rewritten, which is
what keeps the draft-vs-edit diff from losing its left-hand side the moment a reviewer
saves. `runs.notes` was deliberately **not** folded in — migrating 32 live drafts
and breaking a route Phase 2a just shipped is not worth the uniformity, and Phase 3 reads
two sources with a UNION.

**The persistence baseline is a registry entry, not a number in prose (D25).**
`MODEL_REGISTRY["persistence"]` fits `PriorValueRegressor`, whose `predict` returns
`X[prior_column]` unchanged, so the baseline is a real logged run — on the leaderboard, in
the compare table, retrievable by Phase 3. It requires `ModelSpec.preprocess = False`:
inside the standard `build_pipeline` the estimator would receive a **scaled** prior value
and could never emit raw dollars, so the baseline would be silently wrong rather than
fail. Its `search_space` is empty and `POST /experiments/{id}/tune` **422s** on it rather than
running N identical trials. It is also the first registry entry built on a non-sklearn
estimator, which means `experiment_log.log_run` must name it in `skops_trusted_types` —
see the MLflow note below.

**A non-sklearn estimator must be added to the skops trust list.** `log_run` passes an
explicit `skops_trusted_types` to `mlflow.sklearn.log_model`; mlflow 3.15 serialises with
skops, which refuses any type not on that list. Adding a `MODEL_REGISTRY` entry whose
estimator is our own class and *not* the trust entry makes every run of that model **500 at
log time** — and only against a real tracking store, so unit tests on the SQLite store stay
green if they never log that model. `test_experiment_log.py::test_every_registry_model_logs`
parametrizes over `MODEL_REGISTRY` and both logs and loads each entry (D24 needs the load
half too), so adding a model to the registry automatically covers it.

**Diagnostics loads the logged MLflow model; a missing artifact is a 409 (D24).**
`POST /runs/{id}/diagnostics` calls `mlflow.sklearn.load_model` and never refits
from logged params — a close-but-different model reported as the one that was scored is
the worse failure, because nothing about it looks wrong. `app/diagnostics.py` re-derives
the holdout with `training.split_frame`, so residuals are computed on exactly the rows the
run was scored on. Both frames are handed to `run_loop` as in-memory datasets with
ephemeral ids and are **never** inserted into `datasets` — D13 makes that table the single
*source*-data path, and a derived frame is not source data.

**The leaderboard's model filter derives its options from the rows, never from
a list (#51).** `ExperimentDetailPage`'s **Model type** `<select>` is built from
the distinct `run.model_type` values in the loaded leaderboard. The filter it
replaces kept a hardcoded `MODEL_TYPES` array in the frontend, which silently
stopped covering `MODEL_REGISTRY` the moment `persistence` was added (D25) —
selecting a model that existed in the backend and not in the array returned
nothing, with no error. Options built from the data cannot drift from it, and
the filter can never match zero rows, which is why there is no empty state.
Two properties the tests pin: filtering **does not renumber ranks** (they are
the backend's, over the whole investigation, D38 — a filtered view claiming its
top row is rank 1 would be a lie), and changing the filter **clears the
comparison selection** (a selected row the filter then hides has no reachable
checkbox and would feed an invisible run into the compare table). The filtering
is client-side over the already-ranked rows: `GET /experiments/{id}/runs`
returns the whole ranked investigation in one call, so a per-filter refetch
would buy nothing. `listRuns`' `model_type` query param still exists for
run-level API use; the leaderboard does not go through it.

**`GET /models` exists so the frontend never restates the registry (#52).**
The run form's model list, its per-model hyperparameter inputs, and its Train/Tune
availability are all read from `GET /models`, which only serializes
`training.MODEL_REGISTRY`. The alternative — a list in the frontend — is exactly
what #51 was: a hardcoded `MODEL_TYPES` array that silently stopped covering the
registry the moment `persistence` was added. Two fields on that response carry
weight. `tunable` is `bool(spec.search_space)`, and the form disables Tune when it
is false because `POST /experiments/{id}/tune` **422s** on an empty space (D25).
`column_hyperparams` names the settings whose value is a *column name* rather than
a number — `persistence`'s `prior_column`, which is required to fit but has nothing
to search over, so it appears in neither `search_space` nor a numeric input. It
lives on `ModelSpec` rather than in the dialog so that adding such a model is still
a registry edit; a frontend that checked `model_type === "persistence"` would be
#51 again in a new file. `feature_columns` is deliberately absent from the form —
the backend infers the feature set from the dataset minus the target, and the
endpoint still accepts an explicit list for API callers.

**Approval happens beside the write-up, not in a bulk queue (supersedes D26).**
The standalone `/review` page is gone. Findings are reviewed inline through
`FindingsPanel`, mounted on the page for the thing they are about — EDA findings on
`DatasetPage`, a run's diagnostic findings under the leaderboard on
`ExperimentDetailPage`. D26 gated bulk approval on having expanded a row, because that
page approved N rows at once with most of their text off screen. The property it was
buying — approval only of text that was actually rendered — now holds **by
construction**: every finding's text is rendered unclamped next to its own Approve
button, and there is no way to approve N at a time. Keep it that way. Phase 4's eval
harness treats approved rows as known-relevant ground truth, so a rubber-stamped batch
corrupts that measurement silently, and re-adding a select-all is re-adding the hazard.
Run *notes* were never part of `/review`'s value here — they are approved through
`ExperimentDetailPage`'s per-run `ReviewDialog`, which is why removing the page cost
nothing on that side.

**One navigation surface: categories, then the entities under them.** `NavRail`
replaces a split with no principle behind it — a horizontal row of section links in the
topbar plus a left sidebar that listed datasets no matter which section you were in, so
the experiments pages carried a dataset nav they had no use for. Now `Data` owns
datasets and `Machine learning` owns experiments, each group collapsible and persisted
(`wp-rail-collapsed`), and the topbar keeps only the brand. Two things the rail must
not lose: datasets keep their **checkboxes**, because a chat spans N datasets fixed at
creation (#6), and a bare row click opens `/datasets/{id}` rather than starting a chat —
that page carries Start chat and Run EDA and is where the EDA draft lands, so generating
a write-up and reading it are no longer in different sections. The two fetches are
deliberately independent: one list failing must not blank the other.

**The chat renders the question optimistically, and says so (#50).** `ChatPage`
appends the local user turn on submit rather than after `postChat` resolves — the
judge-gated loop can run several passes, and `QuestionBox` clears its input on submit, so
the thread otherwise looked like the question was never received. Optimistic rows are the
one place `messages` is **not** a mirror of persisted history, so the turn carries a
`delivery` prop (`"sending"` | `"failed"`) that `ChatTurn` renders as a status line. A
failed turn is deliberately **kept** — dropping it destroys the only copy of the question —
but it must keep saying "Not sent", or it silently disappears on the next reload. Turns
loaded from history pass no `delivery` and are by definition delivered. `ChatTurn.module.css`
styles `[data-role="user"]` with the documented `--accent` / `--accent-ink` fill pair so
contrast holds in both themes; a hand-mixed tint would not.

**Read mode and edit mode are not the same text (#49, now in `FindingsPanel`).**
A finding renders its Markdown through `react-markdown` exactly as `ChatTurn` renders
assistant prose; **Edit** swaps in the `<Textarea>` over the **raw source**, and
`edits[id]` always holds that source. Handing the reviewer rendered text to edit would
strip the formatting on save with nothing visibly wrong, so keep the textarea bound to
`currentText` and never to anything derived from the rendered output. Approving edited
text sends `{text, status}` in **one** PATCH: `text` alone is deliberately an edit and
not an approval (D20), so a save-then-approve pair would leave the row a draft if the
second call failed.

**`GET /findings` filters on `source_id`, and the panels always send it.** A panel shows
one dataset's or one run's findings. Fetching broadly and filtering in the component
would drop everything past the route's `limit` and render as "no findings yet" — empty
rather than truncated, with nothing to indicate which. `source_id` carries no
`source_type` requirement (ids are uuids and do not collide across the two tables it
addresses, D22) but composes with every other filter.

**Both generation endpoints take no request body (D23).** `POST /datasets/{id}/eda` and
`POST /runs/{id}/diagnostics` derive everything from the stored row. Neither wraps
its `run_loop` call in a try/except — `routes/chats.py` does not either, so a loop failure
propagates to FastAPI's default handler and the behaviour stays uniform. The "no partial
finding" guarantee comes from **statement ordering** (`create_finding` sits below the loop
call), not from an exception handler; keep that ordering if you refactor.

**Charts are never stored.** Charts are a pure function of `data_csv` + a message's `tool_calls`. On any history reload the backend re-renders them from those two inputs. There is no `chart_urls` column and no image files.

**Quality-gated LLM loop (issue #9, replaces D2 single-pass).** `app/loop.py`'s `run_loop()` is the orchestrator: an analyst pass (`app.llm.analyst_call`) picks/adds chart tools and writes an interpretation, the backend validates and renders those charts (as it always did), and a separate judge pass (`app.llm.judge_call`, scored per `prompts/judge.md` via a forced `submit_verdict` tool call) rates the attempt 0–100 against the actual rendered charts + stats — not a prediction of them. The loop feeds the analyst its own prior interpretation, the rendered images/stats, and the judge's feedback/gaps, and repeats until the judge score clears `Settings.llm_quality_threshold` (default **80**), `Settings.llm_max_passes` (default **3**) is reached, or the pass stalls out (adds no new charts and the judge score does not improve over the best so far), then returns the **best-scoring** pass (not necessarily the last). `Settings.judge_model` (default `""` → falls back to `anthropic_model`) lets the judge run on a different model. `chat_messages.pass_count` / `judge_score` (both nullable) persist per turn for later eval/analysis. `tokens_in/out`, `cost_usd`, `latency_ms` on the assistant row are now **sums across every analyst + judge call** in the turn. See `doc/project-1-llm-loop-design.md`.

**Loop trace exposed in the UI (issue #9 review).** `run_loop()` also returns a per-pass `trace` (list of `{analyst, judge, charts, stats, errors, revision_instruction}`, one per pass); the route persists it as `{"passes": [...]}` in `chat_messages.trace_json` (nullable) and returns it as `ChatMessageOut.trace` (a `MessageTraceOut`, `None` for user/pre-trace rows). The frontend renders it via `PassTrace` — a collapsed `<details>` under each answer showing each pass's analyst/judge model + tokens + latency + cost, the judge score/feedback/gaps, and the revision instruction fed to the next pass. **This intentionally reverses the earlier "response shape unchanged / pass detail not exposed" decision** (the reviewer asked for it). Two constraints from that review: (1) the assembled **system prompt is never exposed** — it is not returned, not stored, and has no UI toggle (it can leak guardrail language, so it never leaves the backend); (2) unlike the main charts (re-rendered from `tool_calls`, never stored), the trace's per-pass PNGs **are** stored verbatim in `trace_json` — the deliberate exception to "charts are never stored", accepted for its storage cost so the UI shows exactly what each judge saw.

**Multi-dataset chat (issue #6).** A chat spans N datasets via the `chat_datasets` join table (`Chat` has no `dataset_id`). Datasets are fixed at chat creation (`POST /chats {dataset_ids}`); there is no mid-chat attach. The three per-dataset tools (`histogram`, `scatter`, `correlation_matrix`) each require a `dataset_id` arg, and a `compare` tool does an in-memory, inner-join comparison of an aggregated metric across **exactly two** datasets. Both are additive to the LLM loop above (dataset profiles are assembled once per turn into the shared system prompt every analyst pass reuses, degrading `sample_rows` first if the combined budget `profile_token_budget * n_datasets` is exceeded) and D5 (joined/compared data is computed per request and never persisted). See `doc/project-1-multi-dataset-chat-design.md`.

**Profiler token budget.** `profile_dataframe()` enforces: `value_counts` only for columns with cardinality ≤ 20, correlations capped at top-25 pairs beyond 30 numeric columns, 5 sample rows. If the assembled profile exceeds the token budget, it degrades to schema + `describe()` + correlations only (`degraded=True`). These caps are **configuration parameters** (`Settings.profile_max_cardinality`, `profile_max_corr_cols`, `profile_top_corr_pairs`, `profile_sample_rows`, `profile_token_budget`; overridable via `.env`, see `.env.example`) — the upload route passes `settings.profile_*` into `profile_dataframe()`. Do not widen these defaults without reviewing D3.

**matplotlib `Agg` backend, fresh `Figure` per call.** The analysis engine must never touch `pyplot` global state — it is not thread-safe under FastAPI. Each function creates a fresh `Figure`, renders, and closes it.

**Backend validates Claude's tool args before executing.** On column mismatch or type mismatch, skip that call and return a graceful error entry — never pass raw Claude output to the analysis functions unchecked.

**Profiler normalizes NaN → None at the record level.** `profile_dataframe()` sample rows convert NaN to `None` per-scalar after `to_dict()` (`_is_na_scalar`), *not* via `DataFrame.where(..., None)` — under pandas 2.3 a float column re-coerces `None` back to `NaN`, which silently breaks JSON null-ness. Keep the per-record normalization.

**FastAPI `Depends()`/`File()` in defaults are exempted from ruff B008.** `pyproject.toml` lists FastAPI's dependency markers under `[tool.ruff.lint.flake8-bugbear] extend-immutable-calls`. This is intentional — the idiomatic FastAPI signature (`file: UploadFile = File(...)`) would otherwise trip flake8-bugbear's "function call in default argument" rule. Don't rewrite route signatures to dodge it.

**Idempotent upload (issue #7).** `POST /datasets` deduplicates by a SHA-256 hash of the raw upload bytes, stored in `datasets.content_hash` (`VARCHAR(64)`, unique). A re-upload of identical content returns the existing record with 200; `content_hash` is internal and not exposed in `DatasetOut`. Backfill for pre-existing rows hashes the stored decoded CSV (best-effort — original raw bytes are not retained).

**Frontend design foundation is Radix primitives + CSS-variable tokens + CSS modules (issue #11).** The only new runtime dependency is `@radix-ui/react-dialog`; everything else in `frontend/src/ui/` is a hand-rolled, tokenized wrapper. Dark mode is a persisted `data-theme` toggle (localStorage key `wp-theme`), defaulting to the OS `prefers-color-scheme`. Because Vitest runs with `css: false`, component tests must assert on roles / accessible names / `data-*` attributes / visible text — never CSS-module class names.

**A dialog stops being centred the moment it is measured.** `ui/Dialog` opens at
a fixed base width (`52rem`, capped at `94vw`) and is user-resizable via
`resize: both`. Those two things are in tension: CSS centres the box with
`transform: translate(-50%, -50%)`, and growing a translated box shifts it back
by half of what it grew, so the drag handle crawls away at half the pointer's
speed. `pinForResize` therefore measures the centred box on mount and rewrites
`top`/`left` to those pixel values with `transform: none`, then derives
`max-width`/`max-height` from the pinned corner so a downward drag stops at the
viewport edge instead of pulling the dialog's own bottom off-screen. The guard
that matters: it **returns early on a 0×0 rect**, because jsdom reports that for
everything and pinning an unmeasured element to (0, 0) would throw away the
centring in any environment that mounts a dialog before layout.

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

## Tests

Tests run against **SQLite** (via `tmp_path`). Production uses Postgres via `DATABASE_URL`. The `client` pytest fixture in `conftest.py` overrides `get_session` with an isolated SQLite session for every test — no shared state between tests.

The pgvector similarity query is the one thing SQLite cannot exercise. `make
check` monkeypatches `_rank_chunks` to test grouping and scoring; the real SQL is
covered by `pytest -m postgres` in the `backend-postgres` CI job (see Commands).

The eval suite (`make eval`) is a separate, real-API grader over retrieval quality — see the **`make eval`** write-up under Commands (backend). It needs real Postgres/pgvector and Voyage credentials, so it stays separate from `make test`.

## Implementation plans

`doc/plans/` contains task-by-task implementation plans with checkbox steps. When executing a plan, use the `superpowers:executing-plans` or `superpowers:subagent-driven-development` skill and track progress via the checkboxes. Complete one task fully (including its test) before starting the next.

## Document sync — required before merging a PR or committing a major feature

Before merging a PR or committing a change that adds, removes, or significantly alters a feature, sync the following key documents so they stay accurate:

- **`README.md`** — update the quickstart, commands, and feature list if the user-facing behaviour changed
- **`CLAUDE.md`** — update code layout, non-obvious design decisions, and constraints if the architecture changed
- **`doc/project-1-csv-analysis-assistant-design.md`** — update any design decisions (D1–D6) that were revised
- **`doc/plans/`** — tick off completed tasks in the relevant plan file

A PR that changes behaviour without updating the relevant doc should not be merged.

**Tracing is off by default and never carries payloads (3.1).** `app/tracing.py` is
the only module that imports `opentelemetry`. `Settings.otel_enabled` is `False`, so
`make test` needs no collector and CI needs no service container; `span()` still works
when nothing is installed — OpenTelemetry's default tracer returns a non-recording
span — so **no caller ever branches on whether tracing is on**. Two constraints that
are not decoration. (1) **Span attributes carry ids, counts and durations, never
payloads**: no embedding vectors, no note text, no user questions. An exporter is a
place data leaves the process from, and a trace is for finding where the time and the
calls went. (2) `span()` **drops `None`-valued attributes** rather than passing them
through, because OTel raises on `None` — so callers hand optional values straight in
instead of inventing a sentinel, and a sentinel like `-1` would be averaged into any
dashboard built on that attribute. Tests substitute a tracer by monkeypatching
`tracing._tracer` (the `spans` fixture), **not** by calling `trace.set_tracer_provider`:
the global provider can only be set once per process, so a fixture that set it would
work in the first test that used it and silently export nothing in every later one.
`configure_tracing()` is idempotent for the same reason — `create_app()` runs once per
test, and a second install would add a second span processor for the rest of the run.

**The loop's spans are per-pass; its accumulators are not (3.2).** `run_loop()` opens
one `llm.loop` root and, per pass, `llm.analyst_pass` → `charts.render` →
`llm.judge_pass`. `passes` is incremented **before** the analyst call so both spans of
one pass carry the same `pass_index`, and the same number as that pass's trace
`pass_no`. The trap is that `errors`, `charts` and `stats` are loop-wide accumulators
reused every pass: `charts.render` therefore reports `errors` as a **delta** against a
count snapshotted before the render loop, with the running total under `errors_total`.
Reading `len(errors)` directly would re-report pass 1's failures on pass 3 beside a
`charts` count that is genuinely per-pass — two denominators under one span, and
nothing about the number looks wrong.

**Retrieval's spans count, they never quote.** `retrieval.search` wraps both
stages, with `retrieval.embed_query` and `retrieval.rank_chunks` beneath it and
`retrieval.run_detail` beside them, so one `/agent/chat` request is one trace
carrying LLM, tool and retrieval spans together. `filters` is a **count** of how
many were supplied, not which: a filter value is the model's own query text, and
3.1's rule admits ids, counts and durations only. `unrestricted` is exported
alongside `candidate_keys` because the count alone cannot distinguish "no filters,
search everything" (`keys is None`) from "the filters matched nothing" (`keys ==
()`), which is the whole point of that distinction (3.4a) — and a trace that
cannot tell them apart is a trace you cannot debug a silently-empty answer with.
`test_retrieval_tracing.py` seeds a note with a known sentence, asserts it comes
back in the `Hit`, and then asserts it appears in **no** span attribute.

**Chunking is a pure function of a string; indexing and querying are not
symmetric (D29/3.3).** `app/embeddings.py` is the only module that imports
`voyageai`. `chunk_text()` splits on sentence boundaries and accumulates to ~1000
characters with **no overlap** — sentence boundaries already guarantee no sentence
is unretrievable, so overlap would duplicate text in the index and inflate Phase
4's recall by counting one passage twice. A blank line is a **hard** boundary while
a sentence break is only a permitted one: pack a markdown heading onto the tail of
the section above it and it retrieves as that section, which is the wrong section
with nothing about the result looking wrong. Headings therefore attach to the
section *below* them — `"## Missingness"` alone embeds as almost nothing and would
answer a question about missingness with a bare heading. A single sentence longer
than the budget is emitted whole rather than cut; half a sentence retrieves as
nonsense. `embed_texts()` **requires** `input_type` (`"document"` when indexing,
`"query"` when searching) rather than defaulting it — Voyage's models are trained
with that asymmetry, and passing "document" for a query costs recall with no symptom
except mediocre eval numbers nobody can attribute. The returned width is checked
against `EMBEDDING_DIM` here rather than left to fail at INSERT, where the error
names the column and says nothing about the provider that produced it.
Rate limits are the one error `embed_texts` retries, with bounded exponential
backoff (`VOYAGE_MAX_ATTEMPTS`, `VOYAGE_RETRY_BASE_SECONDS`): the free tier
allows **3 requests/minute** and `make embed` sends one request per changed
source, so a review session of a dozen notes trips it as a matter of course, and
an unretried 429 aborts the backfill partway — leaving the index
half-reconciled, the state 3.3b's reap exists to prevent. A bad key or a wrong
model name is **not** retried; it fails identically on every attempt, so retrying
turns an instant, legible error into a slow one. The 429 is matched on the
exception's class name plus the status code in its message rather than by
importing `voyageai.error`, because that import is deliberately deferred into
`_default_client()` so a missing package fails at call time instead of at app
startup. `_sleep` is a module attribute so tests can record the delays instead of
serving them.
`Settings.voyage_model` is a config value, but changing it is **not** a config
change: two models' vectors are not comparable, so every indexed vector has to be
recomputed. D14 fixes the provider and the 512 width, not the model string.

**`python = ">=3.12,<3.15"`, not `^3.12`.** The upper bound is not decoration:
`voyageai` requires `<3.15`, and `^3.12` claims a range (`<4.0`) this app cannot
actually install on. Everything else pins 3.12 — `.python-version`, mypy's
`python_version`, and CI.

**The backfill is a reconciliation, not an append (3.3b).** `embeddings.backfill()`
compares what is *currently approved* against what is *currently indexed* and handles
three cases: newly approved (chunk, embed, insert), edited after approval (delete the
key's chunks, re-insert), and **no longer approved (reap)**. The reap is the one an
append-only implementation misses while passing every other test: without it,
`approved → rejected` leaves chunks in the table carrying `status = 'approved'`, still
ranking, and serving rejected text labelled approved is worse than serving nothing —
it defeats D28 silently. "No longer approved" covers both `notes_status` changing and
the text being emptied, which is why eligibility is recomputed from the **source**
tables every run and never from the chunk table's own denormalised `status`; that copy
is exactly what goes stale. Re-indexing is delete-then-insert per key, never an upsert:
text edited from four chunks down to one would otherwise leave `chunk_index` 1..3
behind. Unchanged keys are skipped **before** embedding, so a no-op run costs no Voyage
calls. All approved text under one key is concatenated into a single document —
`POST /datasets/{id}/eda` can run twice and both write `("eda", dataset_id)`, which the
chunk table's unique constraint on `(source_type, source_id, chunk_index)` does not
allow to be two documents. That concatenation is ordered by `(created_at, id)`: on
SQLite `created_at` is second-resolution, so two findings written in one commit compare
equal, and an unstable order would reindex text nobody edited on every run.

**Indexing is `make embed`, never a route (D17).** An embedding call inside
`PATCH /runs/{id}` would mean an approval fails when Voyage is down — a local
bookkeeping action made dependent on a vendor being up. The accepted cost is that the
index lags approval and nothing detects the gap; run `make embed` after a review
session. `scripts/backfill_embeddings.py` goes through `app.embeddings`, and prints a
guidance line rather than a bare row of zeros when nothing is approved yet.

**An empty candidate set is not an unrestricted one (3.4a).** `retrieval.Candidates.keys`
is `None` when no filters were supplied — stage 2 searches the whole index — and `()`
when filters were supplied and matched nothing. Collapsing the two is the tempting
simplification and it turns "no ridge runs exist" into "here is everything", which the
agent then summarises with total confidence and no visible symptom. `candidate_runs`
short-circuits to `keys=None` *before* building the query for exactly this reason.
Each matching run expands to three chunk keys (D30) — `("note", run.id)`,
`("diagnostic", run.id)`, and `("eda", experiment.dataset_id)` — so "what do we know
about this data" reaches the dataset write-up and not only run notes; the EDA key is
skipped when `experiments.dataset_id` is NULL rather than emitted as `("eda", None)`.
`dataset_id` and `task_type` filter on the **parent** experiment (D37), `model_type` and
`experiment_id` on the run. `status` has no relational column — it lives in MLflow (D4) —
so it intersects with the tracking store, and an unreachable one
appends a warning and drops that one filter rather than 503ing the whole request: notes
and findings are in Postgres and stay answerable. That intersection goes through
`experiment_log.fetch_runs`, **not** `search_runs`: `search_runs` asks for the whole
store capped at `SEARCH_MAX_RESULTS` and truncates *before* applying the status filter,
so past that cap it silently returns fewer candidates than exist — the same
narrowing-with-no-symptom failure the `None`/`()` distinction above exists to prevent.
`fetch_runs` scopes the query to `attributes.run_id IN (...)` over the rows the
relational stage already admitted, in one call. The relational query selects three
**columns**, not two ORM entities: `runs.notes` is TEXT and nothing in stage 1 reads it.

**`k` counts sources, not chunks, and a source is scored by its single best chunk
(3.4b).** Chunks are the retrieval *unit*; sources are the *answer* unit. A `k` of
chunks lets one four-chunk finding fill the whole budget and hide three other runs —
the agent then answers from a single source while sounding like it surveyed the
history, and every hit it cites is genuinely relevant, so nothing about the answer
looks wrong. `search_runs` therefore over-fetches `k * chunk_overfetch` chunks, groups
them by `(source_type, source_id)`, and keeps `k` sources. Each source scores by its
**nearest** chunk rather than the mean: averaging punishes a long, thorough write-up
for its own breadth, which is exactly the document most worth surfacing. `Hit` carries
`run_id` / `experiment_id` / `dataset_id`, resolved in `_resolve_ids` while the join is
already open — the per-hit alternative is an N+1 that only shows up at a full `k`.

**`_rank_chunks` is the only function that emits `<=>`.** pgvector's cosine operator
has no SQLite equivalent and the whole suite runs on SQLite, so the similarity query is
isolated behind one seam that `test_retrieval_grouping.py` monkeypatches to test
grouping and scoring; the real SQL is exercised against Postgres in
`test_retrieval_postgres.py`, which runs as its own `backend-postgres` CI job
and **skips** without `POSTGRES_TEST_URL` (3.7). Nothing at module scope may touch
`ExperimentNoteChunk.embedding.cosine_distance` — the expression is built inside
`_rank_chunks`, so importing `app.retrieval` on SQLite stays safe. The chunk-level
`status == "approved"` predicate there is a second line of defence, not the first:
what actually keeps rejected text out of the index is the backfill's reap (3.3b).

**The agent's tools are `search_runs`, `get_run_detail` and `get_leaderboard`
(D41, extended by D47).** Never `search_experiments`: since D33 "experiment"
names an *investigation*, so a tool by that name would promise a search over
investigations and deliver a search over runs. The model reads the tool name as
part of its contract, and a name that lies is a prompt bug that looks like a
retrieval bug — which is also why the third tool is not called `recommend_next`
(D47). `prompts/agent.md` is part of that contract and has to be counted as
part of `TOOLS`: it went on saying "two tools" after the third landed, and a
prompt that undercounts the tools is a tool the model will not reach for
(fixed in `0697cb6`). `app/agent.py` validates every call against `TOOLS` before
executing it — same rule as `app/tools.py` for the analysis loop: never pass raw
model output to a function unchecked.

**`run_agent` is deliberately not `run_loop` (3.5).** `app/loop.py` is
judge-gated and renders charts; the agent answers from retrieved text. Folding
them together would make each carry the other's concerns for no shared behaviour.
Two properties of the agent loop that are not decoration. (1) Hitting
`Settings.agent_max_turns` (default 6) does **not** end the request empty-handed:
the loop makes one further call with the tools removed, and that call is not
counted — a model that spent its whole budget searching would otherwise return
`""`, which reads as a backend failure rather than as a model that ran long.
**Removing `tools` from that call is not sufficient on its own.** The transcript
still carries `tool_use` and `tool_result` blocks, and the model reads those as
evidence the tools exist: observed live, the forced call came back
`stop_reason="tool_use"` on a request carrying no tool definitions at all, the
loop broke with no text block, and the user got an empty answer — precisely the
failure the forced call exists to prevent. `_final_turn` therefore also *says
so in words*, attaching the instruction to the trailing `tool_result` message
rather than sending a second consecutive `user` turn, which the Messages API
rejects. It builds a **copy**, because `messages` is mutated in place across
turns. Belt and braces, an `answer` still empty at the end falls back to
`_NO_ANSWER` rather than `""`: a blank answer bubble is indistinguishable from a
crashed request. Note also that Sonnet 5 returns `thinking` blocks by default, so
the answer is the **text** blocks specifically — never `content[0]`.
`Settings.agent_max_k` (default 25) bounds the `k` the model may ask for, since
every returned source's snippet lands in its context and stage 2 over-fetches
`k * chunk_overfetch` chunks to produce them. It is **rejected, not clamped**:
answering a `k` of 500 with 25 sources tells the model the history holds 25, and
it then reports that. `validate_tool_call` promises to return a string and never
raise, so the JSON-schema-type → Python-type map is checked at **import** — a
`KeyError` from the one function whose job is turning bad model input into a
correctable message would be a 500 that loses the conversation, and `_execute`
calls it outside its `try`.
(2) `_execute` **never raises**. A bad argument, an unknown `run_id`, an
unreachable tracking store — each comes back as a `tool_result` the model can act
on. Letting one propagate turns a recoverable step into a 500 for the whole
request. `AgentStep` carries counts, ids and durations but **never retrieved
text**; the text lives once, in `AgentResult.retrieved`, under the same rule the
spans follow.

**`POST /agent/chat` is stateless and lives at `/agent` (D42).** Not under
`/experiments`: the agent answers *across* investigations, and nesting it under
one would imply a scope it does not have. There is no `agent_chats` table and no
history — `AgentChatRequest` sets `extra="forbid"`, so a client that thinks it is
continuing a conversation gets a 422 instead of having its `chat_id` silently
ignored. The Project 1 chat is stateful because it accumulates charts against a
fixed dataset set; this is question-answering over history that already lives
elsewhere. It is the **one request-path caller of Voyage** — every search embeds
its query — while indexing stays in `make embed` (D17). Like the loop trace
(issue #9), the response has no `system_prompt` field: not returned, not stored,
no UI toggle. `cost_usd` on the response is `llm._estimate_cost` over the summed
token counts, the same estimator the chat turns use, so the two surfaces' numbers
are comparable rather than each being separately plausible.

**A citation you cannot click through is unfalsifiable (3.6b).** Every hit on
`AskPage` deep-links to the page holding the reviewed text it came from — `eda` to
`/datasets/{dataset_id}`, `note` and `diagnostic` to `/experiments/{experiment_id}`
— so a wrong citation is *visibly* wrong rather than merely plausible. `hrefFor`
switches on `source_type`, not on whichever id happens to be non-null, because a
hit carries several. The `Agent` rail category is top-level beside `Data` and
`Machine learning`, not nested under the latter: the agent reads across both
halves, dataset EDA findings included. Its group toggle is labelled **"Ask
history"** rather than "Ask" — `ChatPage`'s submit button already answers to that
exact accessible name, and two buttons sharing one makes every `getByRole` query
for it ambiguous.

**`get_run_detail` reports a missing `cv_std` as `None`, never `0.0` (D32).**
"Unquantified" is something the agent can say; a fabricated zero band makes every
difference look significant, and runs logged before 3.0 legitimately have no band.
Unlike the status *filter* in `candidate_runs` — which degrades to a warning because
notes and findings are still in Postgres — an unreachable tracking store here raises
`TrackingStoreUnavailable`: the params and metrics **are** the answer, so there is no
partial one to give.

**Ground truth is a source, not a chunk (D43).** Relevance in
`backend/eval/golden_set.yaml` is labelled on `(source_type, source_id)` — the unit
`retrieval.search_runs` returns after grouping (3.4b). Labelling chunks would measure
the chunker rather than the retrieval, and the labels would silently expire the next
time `chunk_max_chars` changed: the ids would still parse, the run would still report
a number, and nothing would say the number was now over a different index. It is also
not *experiment* ids — D33 split experiment from run, and an `eda` source is keyed to
a dataset and has no experiment id at all.

**Golden-set queries are written blind (D44).** The rule, and how to hold to it when
extending the set, is written up under **`make eval`** in Commands (backend) — it is an
instruction for anyone touching `golden_set.yaml`, so it lives beside the command that
reads it. The decision it records is this one: Claude wrote the notes *and* would be
answering from them, so a query drafted while reading its target measures whether
retrieval can find a document it was copied from — a test that passes whether or not
retrieval works. Blind drafting is what makes the resulting number mean anything, and it
is the same circularity D44 breaks on the answer side by refusing to grade answers at all.

**The corpus is a curated subset (D45).** `scripts/apply_curation.py` decides **every
run in the database**, not a fixed count: at curation time that was 34 — the 32 `make
seed-history` creates, plus two the database had acquired since — and 17 were approved,
chosen for model and outcome diversity. The quotas are therefore **absolute per-family
counts, not proportions**, so the manifest is unaffected when the run count drifts from
the 32 the seeding script produces; anything written as "N of the 32 seeded runs" is
reading the seed count where it should be reading the database. The verdict and the
reason for each are recorded in `backend/eval/curation.yaml` and applied through
`PATCH /runs/{id}` (never by touching the DB, D13). Approving everything makes almost
every source relevant to almost every query and precision stops discriminating;
approving whichever ones happen to read well biases the corpus toward the queries. **Count the corpus from the index, never from the manifest.**
The 17 approved notes plus 6 approved findings are 23 approved *rows* but **21
retrievable sources** — 17 note, 3 diagnostic, 1 eda — because `POST /datasets/{id}/eda`
ran three times against one dataset and 3.3b concatenates all approved text under a key
into a single document, so those three findings are one `("eda", dataset_id)` source. A
metric that counted 23 would inflate every `recall@k` denominator by two unreachable
sources: uniform across the sweep, so it would not change D46's ranking, and therefore
would never show up as a discrepancy — it would just quietly understate every absolute
number in the report.

**The sweep is pre-registered (D46).** The grid, the metric and the adoption rule in
`backend/eval/results/sweep.md` were committed before any configuration was measured.
Nine configurations on twenty queries with a post-hoc winner finds one from noise
essentially every time. Adoption needs a paired MRR delta beyond **two standard errors**
across the 20 queries, and no cell cleared it, so the defaults stand. This shares D38's
*principle* — a difference below the noise floor is reported as noise, not as a win —
but **not its threshold, and the two must not be conflated**: D38's floor is the
leader's own `cv_std`, one standard deviation of a single run's fold spread, while
D46's is two standard errors of a paired delta between two configurations over a fixed
query set. They answer different questions on different statistics, and quoting one
number as though it were the other would make a within-noise result look adopted or an
adopted one look within noise. Two things that report as findings rather than as a failed sweep, and
must not be quietly repaired: `chunk_max_chars=600` was a real *negative* effect
(-0.117 MRR, 2.17 sigma), and MRR is structurally blind to the `chunk_overfetch` axis,
since overfetch only extends the tail of the candidate pool and can never promote a
source ahead of one already retrieved. Re-scoring that grid on `precision@k` after
seeing the results would be exactly the post-hoc selection the pre-registration exists
to prevent, so the flaw is reported instead.

**`get_leaderboard` is named for what it returns (D47).** Not `recommend_next`: a tool
returning rows must not be named for the conclusion drawn from them, or the model
treats its output as the recommendation rather than as the evidence for one. The
recommendation is the model's job and the leaderboard is its grounding — which is the
point, since snippets retrieved by similarity are prose *about* runs and cannot be
ranked. Adding it made `TOOLS` three long while `prompts/agent.md` still said two; the
prompt is part of the tool contract, so both move together.

**Artifacts live in object storage on the deploy (D48).** `mlflow_artifact_root` is an
`s3://` URI (Cloudflare R2). MLflow stores **absolute** artifact URIs in the database,
so copying the directory is not enough — `scripts/migrate_artifact_uris.py` rewrites
them, across **three** columns: `mlflow.runs.artifact_uri`,
`mlflow.experiments.artifact_location`, and `mlflow.logged_models.artifact_location`,
which is what `runs:/{run_id}/model` actually resolves through in MLflow 3.x. Missing
the third leaves every row looking migrated while `mlflow.sklearn.load_model` still
resolves to a path that is not there, so `POST /runs/{id}/diagnostics` 409s (D24) with
nothing in the URI columns to explain it. Re-training on the deployed instance instead
of migrating would mint new run ids and orphan both `curation.yaml` and
`golden_set.yaml`, which address runs by id. The rewrite is raw SQL against MLflow's
schema on purpose: D4 forbids modelling those tables, and this is a data change, not a
schema change.

**A list-typed setting must not be able to stop the process booting.**
`Settings.cors_allow_origins` is `list[str]`, and pydantic-settings JSON-decodes any
list-typed env var **before** validation — so a plainly-typed `https://app.example.com`
raised `SettingsError` at import, uvicorn never bound, and the health check failed. On a
host that keeps the previous container alive when a deploy fails that check, the symptom
is not an outage: the site stays up, the API keeps returning 200, and the setting simply
never takes — a config change that looks applied from outside and is not. Observed on
Render during Task 14's smoke test. The fix is `NoDecode` plus a `mode="before"`
validator accepting a bare origin, a comma-separated list, or a JSON list; a value that
*opens* with `[` is still parsed as JSON and still fails loudly, because a malformed JSON
list silently reinterpreted as one long origin string is worse than an error.
`backend/tests/test_config.py` pins all of those forms — including the boot-time one,
which is the only reason the trap is visible in `make check` at all.
