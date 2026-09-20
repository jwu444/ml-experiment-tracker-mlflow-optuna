# WavePoint-Project-2 — ML Experiment Tracker

Project 2 of a 3-project AI Engineering Workshop, forked from Project 1's CSV
Analysis Assistant. It keeps Project 1's upload-and-ask flow — Claude reads a
bounded profile of your data, selects from a fixed menu of pandas/plot tools
(histogram, scatter, correlation matrix), and writes an interpretation through a
judge-gated multi-pass loop — and adds ML experiment tracking on top: training
runs logged to MLflow, hyperparameter search with Optuna, retrieval over
experiment history, and an agent that recommends what to try next.

The working domain is computer-component pricing and demand (see
`doc/project-2-ml-experiment-tracker-design.md` §2). This repo is a full-stack
app: a **FastAPI** backend and a **React + Vite** frontend.

Design: `doc/project-2-ml-experiment-tracker-design.md` ·
Roadmap: `doc/plans/2026-08-05-project-2-overall-implementation-plan.md`

## Live demo

**https://wavepoint-web.onrender.com** — the SPA. Its API is at
`https://wavepoint-api.onrender.com`.

Both run on Render's free tier, with the trained models in Cloudflare R2 (D48)
rather than on the service's disk, which every deploy wipes. Three things to
know before judging it:

- **The first request takes ≈50 seconds.** Free services sleep after ~15
  minutes idle, and the first hit wakes the container. It is cold, not broken.
- **The free Postgres expires ~30 days after it is created.** When the demo goes
  quiet, that is usually why. `doc/deploy-runbook.md` Step 5 is the recovery.
- **Tracing is off** (`OTEL_ENABLED=false`): no collector is deployed, and
  Jaeger stays a local tool. Run the app locally to see spans.

Generating a diagnostic write-up calls Claude synchronously inside the request
(D23), so it takes a couple of minutes on free-tier CPU. That is the same code
path as local — it is not a deploy-specific workaround.

`doc/deploy-runbook.md` records how this was deployed, step by step, including
the three failures that cost the most time.

## Data catalog

`data-sources/README.md` is a working catalog of public data for the ML
domain — 27 sources evaluated, 22 with real data actually pulled into this
repo (~13MB across 52 CSVs), 5 deliberately left unpulled (dead link, ToS
restrictions, or no redistribution license — documented, not just skipped
silently). A top-of-file summary table gives the shape of every pulled file
(category, span, candidate key, dimensions, rows) at a glance. Highlights:

- **Component pricing & specs** — `pc-part-dataset` (MIT) is what Phase 1
  actually ingests via `make data-fetch`; its `price` column is 80.8% null for
  GPUs, though, so a second Kaggle dataset with **100% price completeness**
  (311 GPU listings, license terms unclear — a documented judgment call) was
  added specifically to densify the regression target. 3 more Kaggle datasets
  (Apache 2.0 / CC BY-SA 4.0 / CC0) add GPU price history, specs back to 1986,
  and Newegg component listings.
- **Macro economy** — World Bank GDP, GDP growth, and inflation for
  World/US/China/Japan/South Korea/Germany, 1986–2025 (Taiwan is a documented
  gap: not a World Bank member, no modern open API from its own statistics
  agency either).
- **Markets** — 10 stock indices (S&P 500, Nasdaq, PHLX Semiconductor, plus 6
  regional indices) and 17 individual stocks across the hardware value chain
  (manufacturers, system builders, retailers, distributors), 15 years daily.
- **Company financials** — SEC EDGAR revenue for Nvidia, AMD, Dell, HP, Apple,
  Intel, including Nvidia's actual Data Center segment broken out from 19
  individual filings' dimensional XBRL (now ~90% of Nvidia's total revenue,
  up from 78% two years ago).
- **Memory market** — DRAM/NAND demand split by consumer/mobile vs.
  server/enterprise-data-center use: Micron's own segment revenue (dimensional
  XBRL, 9 filings), a 1957–2015 consumer RAM price trend, and a storage-device
  PPI series.
- **Consumer/gaming signal** — a Steam Hardware & Software Survey archive
  (2009–2021 + current) and a live top-100-games activity snapshot.

Every entry, pulled or not, is documented with its license terms and any
data-quality caveats found along the way (stale/discontinued series swapped
for active ones, schema changes across years, etc.) — see
`data-sources/README.md` for the full table.

## Exploratory ML question candidates

Phase 2 needs a real `fit(X, y) → metrics` target for `app/training.py` to
train and MLflow/Optuna to track — these are candidates, mapped to the
domain's driving question in
`doc/project-2-ml-experiment-tracker-design.md` §2 ("what dictates price and
demand for computer components?"), grounded in data actually in the catalog
above rather than hypothetical sources.

**One constraint that shapes all of them:** `pc-part-dataset`'s `price`
column — the design doc's original target — is 80.8% null for GPUs, 61.3%
for CPUs, 78.6% for RAM. `data-sources/gpu-prices-prediction/` (100% price
completeness, 311 GPUs) exists specifically to work around this for the GPU
case; the CPU/RAM cases don't have that fix yet.

1. **Supply-shock → price.** Regress/classify `gpu-price-trends-nvidia-amd/gpu_price_history.csv`
   (retail vs. used, 2022-01–2024-01 — straddles the crypto/shortage-era
   unwind) against `wsts-semiconductor-billings/` + `fred-semiconductor-ppi/`
   as supply-side features.
2. **Consumer signal lead/lag.** Does `steam-hss-archive/`'s category-adoption
   trend (2009–2021) lead or lag GPU/component price movement?
3. **Macro/demand → price direction.** Classify next-period price direction
   (up/down/flat) for `gpu_price_history.csv` using `worldbank-macro/` +
   `market-indices/` (esp. `phlx_semiconductor.csv`) + WSTS billings as
   features.
4. **Company revenue nowcasting.** *(Built — this is the Phase 2a panel.)* Predict
   next-quarter revenue (`sec-edgar-revenue/`) from stock-price momentum
   (`company-stocks/`) + WSTS billings + macro. The five usable tickers are
   **AMD, DELL, HPQ, INTC, NVDA** — a ticker needs both a `sec-edgar-revenue/`
   and a `company-stocks/` file, and Micron has only the latter, so it cannot
   appear in the panel at all. Labels are dense — no null-target problem, unlike
   1–3 — which matters for a first training/tuning pass. `make prepare-data`
   builds it into `data-sources/prepared/revenue_nowcast.csv` (~224 rows).
5. **Memory supercycle regression.** Predict Micron's data-center revenue
   share (`memory-market/micron_revenue_by_segment.csv`, `CMBU`+`CDBU` ÷
   total) from `memory-market/fred_storage_device_ppi.csv` +
   `consumer_ram_price_history_1957-2015.csv` + macro.

**Suggested sequencing:** start with #4 — clean, dense labels mean the first
Optuna study is actually about hyperparameters, not fighting a null-target
column, while `app/training.py` itself is still new. Bring in #1 or #3 (the
domain's original headline question) once the training/tuning path is
proven; those produce the richest experiment-notes text for the retrieval
layer to search over.

## Run the webapp (two terminals)

You need **Python 3.12**, **Poetry**, **Node 18+**, and an **Anthropic API key**.

### 1. Configure your API key

```bash
cp .env.example .env
```

Then edit `.env` and set `ANTHROPIC_API_KEY=sk-ant-...`. Set `VOYAGE_API_KEY=pa-...`
too if you want the retrieval agent — it is not needed for chat, training or any
read route. The `sqlite` default for
`DATABASE_URL` works out of the box — no database to install. (Chat won't work
without a valid key; upload/profile will.)

### 2. Terminal A — backend (http://localhost:8000)

```bash
make install     # poetry install (first run only)
make dev         # uvicorn --reload; API docs at http://localhost:8000/docs
```

### 3. Terminal B — frontend (http://localhost:5173)

```bash
cd frontend
npm install      # first run only
npm run dev
```

Open **http://localhost:5173**. Upload a CSV, then ask questions like
*"show me the distribution of age"* or *"is income correlated with age?"*. The
dev server proxies `/api → http://localhost:8000`, so no CORS setup is needed.

**`/experiments`** lists investigations — name, objective, dataset, and run
count, and **New experiment** creates one (name, objective, dataset, target
column, task type — the target is picked from the dataset's real columns).
Training and tuning always happen inside an investigation (there is no way to
launch a run without creating one first), which is what **New run** on the
detail page does: it offers the models that match the investigation's task
type, a number box per hyperparameter, and a Train/Tune switch. Everything on
that form comes from the backend — the model list from `GET /models`, the
column pickers from `GET /datasets/{id}` — so it cannot fall behind
`MODEL_REGISTRY`. Tune is unavailable for a model with an empty search space
(the persistence baseline), and both modes run synchronously, so the dialog
stays open until the work finishes. Opening an experiment goes to
`/experiments/<id>`, a ranked **leaderboard** of its runs (rank, the primary
metric, `cv_<metric> ± cv_std`, status, notes), with checkboxes to compare
selected runs side by side. A **Model type** dropdown narrows the table to one
model; its options come from the runs on the leaderboard rather than a
hardcoded list, so every model you have trained is filterable, and ranks stay
the ones the full leaderboard assigned. The best run is badged, and a win
smaller than its
`cv_std` is additionally marked **within noise** rather than presented as a clean
victory. Each run opens a review panel for its note, where the three actions are
deliberately distinct — **Save** edits the text without endorsing it, **Approve**
requires non-empty text, and **Reject** does not. Only approved notes are
indexed for retrieval, so approving is a human judgement the machine has no path to
make on its own (D20). If MLflow is unreachable the page still lists the runs,
unranked and newest-first, rather than showing an empty table.

*Findings* — the EDA write-ups and model diagnostics generated by the two
endpoints below — are reviewed **where they were generated**, not in a separate
queue. A dataset's EDA findings sit on `/datasets/<id>` under its column list; a
run's diagnostic findings appear under the leaderboard on the experiment page as
soon as the pass finishes. Each one renders its Markdown the way the chat renders
an answer, with its own **Edit**, **Approve** and **Reject**; **Edit** swaps in a
textarea over the raw source, and approving edited text saves and approves in one
step. Approval is deliberately one finding at a time, next to the text it applies
to — Phase 4 treats approved findings as ground truth, and a batch action over
write-ups nobody had on screen quietly corrupts that.

### Asking about past experiments

**Ask** in the left rail (or `/ask`) puts a question to a retrieval agent that
answers **only from reviewed text** — approved run notes, approved EDA findings,
approved diagnostics. It searches with two stages: structured filters
(model type, dataset, task type, investigation, run status) narrow the candidate
runs relationally, then a vector search over the note index ranks what is left.

Ask it what to try next and it reaches for a third tool, `get_leaderboard`, rather
than answering from the snippets: "what should I try next" is a question about
rankings, and prose *about* runs cannot be ordered. It gets the same ranked rows and
`cv_std` bands the leaderboard page shows, so a gap smaller than the noise band comes
back described as within noise instead of as a winner.

Every answer comes with its sources, and every source is a link: an EDA citation
opens the dataset page, a run note or diagnostic opens its investigation. A
citation you cannot click through is unfalsifiable — this way a wrong one is
visibly wrong. A collapsed **Trace** underneath shows each tool call the agent
made, with token counts and timings.

Two things that surprise people on a fresh install. **Nothing unapproved is
searchable**, so before anything is approved the honest answer is "no reviewed
history matches" — that is the system working, not a failure. And the index is
built **offline** by `make embed` (see below), so text approved since the last
run of it is not yet searchable.

### Generating findings

From the UI: **Run EDA** sits on each dataset's own page, and **Diagnostics** on
each run in an experiment's leaderboard (disabled for classification runs, which
the endpoint rejects). Both write a *draft* and leave it, in place, for you to
approve — they never publish straight through. Each takes tens of seconds, since it
runs the same judge-gated loop the chat uses.

The equivalent API calls, neither of which takes a request body — each derives
everything it needs from the stored row:

```bash
# an EDA write-up over a dataset's real distributions, gaps and correlations
curl -X POST localhost:8000/datasets/<dataset-id>/eda

# an interpretation of one run's residuals, per-group error and learning curve
curl -X POST localhost:8000/runs/<run-id>/diagnostics
```

Both return `201` with `status: "draft"` and run the same judge-gated loop the
chat uses, so generation takes tens of seconds and needs `ANTHROPIC_API_KEY`.
Diagnostics loads the **logged MLflow model** rather than refitting from the
logged params, so a run whose artifact is missing is a `409` and not a plausible
but different model (D24). Read and update them with `GET /findings`
(filterable by `status` and `source_type`) and `PATCH /findings/{id}`; as with
notes, writing text is not approving it, and approving an empty finding is a
`422`.

### The persistence baseline

`model_type: "persistence"` is a real model in the registry, not a number quoted
in a doc: it predicts next period's value as *this* period's value, straight
through. Train it like any other model and it lands on the leaderboard where it
can be compared and beaten — or not. Runs launch inside an experiment, so create
one first — `dataset_id` and `target_column` live on the experiment, not the run:

```bash
curl -X POST localhost:8000/experiments -H 'Content-Type: application/json' -d '{
  "name": "revenue nowcast",
  "dataset_id": "<revenue-panel-id>",
  "target_column": "revenue_next_usd",
  "task_type": "regression"
}'
# -> {"id":"<experiment-id>", ...}

curl -X POST localhost:8000/experiments/<experiment-id>/train -H 'Content-Type: application/json' -d '{
  "model_type": "persistence",
  "feature_columns": ["revenue_usd"],
  "hyperparams": {"prior_column": "revenue_usd"},
  "time_column": "as_of"
}'
```

`POST /experiments/{id}/tune` rejects it with a `422` — its search space is empty, so
tuning it would run N identical trials. **On the shipped revenue panel it is
currently the best model on the board:** RMSE 4.064e9 against the best tuned
ridge's 4.116e9, across 25 runs. With 224 rows and a ~30-row holdout that is the
honest result, and it is the reason the baseline is a first-class run rather than
a footnote.

## Local services (Postgres + Jaeger)

SQLite is the zero-setup default and the test backend. Postgres is required for
anything touching pgvector or MLflow:

```bash
make db-up      # Postgres on :5433, Jaeger UI on :16686
make db-psql    # psql shell
make db-down    # stop
```

Then point `DATABASE_URL` at it in `.env` (see `.env.example`) and run
`make migrate`.

Requires a container runtime — Docker Desktop, OrbStack, or Colima with the
`docker` CLI on `PATH`. Port 5433 is deliberate: it avoids colliding with a
Postgres already running on the host.

### MLflow tracking store

MLflow shares the same Postgres, in its own `mlflow` schema (design D4). One-time
setup after `make db-up`:

```bash
make mlflow-init
```

Then set `MLFLOW_TRACKING_URI` in `.env` (see `.env.example`). MLflow's own web UI
is never deployed — run browsing lives in the app's `ExperimentsPage` (D9/D10). To
inspect runs locally: `make mlflow-ui`.

MLflow owns every table in the `mlflow` schema and migrates them itself. Our
Alembic env filters them out of `--autogenerate` (`app_schema_only` in
`backend/alembic/env.py`); without that filter autogenerate proposes dropping all
59 of them.

### Artifact storage (local disk vs. object storage, D48)

`MLFLOW_ARTIFACT_ROOT` defaults to `./mlruns` — trained models are written to
local disk, which is the right default for development and the only one the
tests use. Render's filesystem is ephemeral, so a deployed instance must point
that root at object storage instead (Cloudflare R2, reached through its S3
API). Set all four together — a partial set fails at the first artifact write,
not at startup:

```bash
MLFLOW_ARTIFACT_ROOT=s3://wavepoint-artifacts/mlruns
MLFLOW_S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
AWS_ACCESS_KEY_ID=<R2 access key id>
AWS_SECRET_ACCESS_KEY=<R2 secret access key>
```

Changing the root only affects **new** runs. Runs already logged carry an
absolute path baked into three MLflow columns, and `POST /runs/{id}/diagnostics`
loads the logged model rather than refitting it (D24), so a run whose artifact
moved without its URI being rewritten returns a 409 — the model is simply gone.
`scripts/migrate_artifact_uris.py` re-points those columns after the files are
copied. It is a dry run unless `--apply` is passed:

```bash
# copy the artifacts first (aws-cli or any S3 client), then:
poetry run python scripts/migrate_artifact_uris.py \
  --database-url "$DATABASE_URL" \
  --old-root "/old/absolute/path/mlruns" \
  --new-root "s3://wavepoint-artifacts/mlruns"          # add --apply to write
```

It rewrites only the root prefix, and only on a path boundary, so a sibling
directory that merely shares a string prefix is left alone; a URI under neither
root is reported rather than guessed at. `mlflow.logged_models.artifact_location`
is the column that actually resolves `runs:/{run_id}/model` under MLflow 3.x —
rewriting only `mlflow.runs.artifact_uri` leaves every model unreachable while
every test still passes.

### Tracing

`make db-up` already runs Jaeger, but the backend sends it nothing until you turn
tracing on — it is **off by default** so `make test` needs no collector and CI
needs no service container. In `.env`:

```bash
OTEL_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
```

Restart `make dev`, ask a question in the chat, and the spans land at
http://localhost:16686 under the service `wavepoint-backend`. Spans carry ids,
counts and durations only — never note text, user questions, or embedding
vectors.

### Seeding experiment history

With the store initialised and the backend running, this builds the panel, uploads
it, and fills the experiment log:

```bash
make prepare-data   # offline: rebuild data-sources/prepared/ from the snapshots
make data-fetch     # upload the prepared panel + component CSVs into `datasets`
make seed-history   # 4 Optuna studies x 8 trials = 32 runs, each with a note
```

`seed-history` is the only part that needs `ANTHROPIC_API_KEY` — the training and
tuning endpoints themselves never call an LLM (D17), which is why they need no key
and no test needs an LLM mock. Every note it writes is a **draft**: the script
PATCHes `{"notes": ...}` and never `notes_status`, so it cannot approve its own
output. Review and approve them at `/experiments` — open an experiment to see and
review its runs. Only approved notes are indexed (D20) — run `make embed`
afterwards to make them searchable.

Re-running `make seed-history` will not duplicate the history; it skips tuning once
the log is populated. `SEED_FORCE_TUNE=1` overrides that.

### Indexing approved text for retrieval

```bash
make embed          # reconcile app.experiment_note_chunks against what is approved
```

Needs `VOYAGE_API_KEY` and a `DATABASE_URL` pointing at the Postgres from `make db-up`.
This is a script rather than something the review endpoints do, on purpose (D17): an
embedding call inside `PATCH /runs/{id}` would make an approval fail whenever Voyage is
down. The cost of that choice is that the index lags approval — run `make embed` after
a review session.

It is a **reconciliation**, so it is safe to run repeatedly and it is how un-approval
takes effect: newly approved text is indexed, edited text is re-indexed, and text that
is no longer approved has its chunks deleted. With nothing approved yet it prints zeros
and tells you where to approve things.

### Measuring retrieval quality (`make eval`)

```bash
make eval                       # score the golden set, print the report
make eval ARGS=--validate-only  # check every labelled source is reachable, spending no Voyage call
```

Needs a real `VOYAGE_API_KEY` and the Postgres from `make db-up` — the `<=>` similarity
operator has no SQLite equivalent, which is why this is not part of `make test`.
`eval/cache.py` caches embeddings by query text, so only the first run costs anything.

It grades **retrieval only** — precision@k, recall@k and MRR over
`(source_type, source_id)` — and reads through the same `retrieval.search_runs` that
`POST /agent/chat` calls, so what is measured is the shipping path rather than a
reimplementation that can drift from it. It deliberately never grades the answer: an
LLM-judged answer score would put Claude on both sides of the scoring, and Claude wrote
the notes.

The 20 queries in `backend/eval/golden_set.yaml` are drafted **blind** — from the
leaderboard, params and metrics only, never from note prose — because a query written
while reading the note it should retrieve mostly measures whether retrieval can find a
document it was copied from. The corpus behind them is curated rather than complete:
`scripts/apply_curation.py` gives every run in the database a verdict and a reason,
recorded in `backend/eval/curation.yaml` — 17 approved out of the 34 that were there
when it ran (the 32 `make seed-history` creates, plus two picked up since) — because
approving everything makes almost every note relevant to almost every query and
precision stops telling you anything.

Committed results live in `backend/eval/results/`. The baseline scores MRR **0.942**
over 20 queries; `sweep.md` records a nine-cell grid whose metric and adoption rule
were fixed before any cell was measured, and which nothing cleared — reported as a
result, not as a failed sweep, and read with the two caveats written up there.

## Try it without the frontend (curl)

```bash
# Make a tiny CSV to play with
printf 'age,income,city\n20,100,NY\n30,200,NY\n40,300,LA\n25,150,SF\n' > sample.csv

# Upload it → returns the dataset id
curl -X POST http://localhost:8000/datasets -F "file=@sample.csv;type=text/csv"
# -> {"id":"<dataset-uuid>","name":"sample.csv","n_rows":4,"n_cols":3}

# Start a chat over one or more datasets → returns the chat id (its own shareable link)
curl -X POST http://localhost:8000/chats \
  -H 'Content-Type: application/json' \
  -d '{"dataset_ids":["<dataset-uuid>"]}'
# -> {"id":"<chat-uuid>","datasets":[{"id":"<dataset-uuid>","name":"sample.csv"}]}

# Ask a question (needs ANTHROPIC_API_KEY set)
curl -X POST http://localhost:8000/chats/<chat-uuid>/messages \
  -H 'Content-Type: application/json' \
  -d '{"question":"show the distribution of income"}'

# Ask the retrieval agent about past experiments (needs ANTHROPIC_API_KEY +
# VOYAGE_API_KEY, and `make embed` already run over some approved text)
curl -X POST http://localhost:8000/agent/chat \
  -H 'Content-Type: application/json' \
  -d '{"question":"Which model did best on the revenue panel, and by how much?"}'
```

## Endpoints

| Method | Path                          | Purpose                                                        |
| ------ | ----------------------------- | -------------------------------------------------------------- |
| GET    | `/health`                     | Liveness check → `{"status":"ok"}`                             |
| POST   | `/datasets`                   | Upload a CSV (multipart `file`): validate → profile → persist  |
| GET    | `/datasets`                   | List all datasets (newest first)                               |
| GET    | `/datasets/{id}`              | Fetch a dataset by id, with its columns                        |
| GET    | `/models`                     | The training registry: models, their hyperparameters, tunability |
| POST   | `/chats`                      | Create a chat over one or more `dataset_ids`                   |
| POST   | `/chats/{chat_id}/messages`   | Ask a question → Claude selects tools → charts + interpretation |
| GET    | `/chats/{chat_id}`            | Chat history (charts re-rendered on the fly, never stored)     |
| POST   | `/experiments`                 | Create an experiment (investigation): name, dataset, target    |
| GET    | `/experiments`                 | List experiments with their run counts                         |
| GET    | `/experiments/{id}`            | One experiment                                                 |
| PATCH  | `/experiments/{id}`            | Edit an experiment's name/objective                            |
| GET    | `/experiments/{id}/runs`       | Ranked leaderboard of the experiment's runs                    |
| POST   | `/experiments/{id}/train`      | Train one model inside the experiment → logs a run to MLflow   |
| POST   | `/experiments/{id}/tune`       | Run an Optuna study inside the experiment → one run per trial  |
| GET    | `/runs`                        | List runs, joined with their MLflow params/metrics             |
| GET    | `/runs/{id}`                   | One run with its params, metrics, and note                     |
| PATCH  | `/runs/{id}`                   | Edit a note, or move `notes_status` to approved/rejected       |
| POST   | `/datasets/{id}/eda`          | Generate an EDA finding for a dataset (no body) → `201` draft  |
| POST   | `/runs/{id}/diagnostics`       | Interpret one run's residuals/errors (no body) → `201` draft   |
| GET    | `/findings`                   | List findings, filterable by `status` and `source_type`        |
| PATCH  | `/findings/{id}`              | Edit finding text, or move `status` to approved/rejected       |
| POST   | `/agent/chat`                 | Ask the retrieval agent one question → answer + sources + trace |

Re-uploading an identical CSV returns the existing dataset (deduplicated by
SHA-256 content hash) instead of creating a duplicate.

The training endpoints need `MLFLOW_TRACKING_URI` set (so, Postgres) and refuse to
run on SQLite. Passing a `time_column` makes the holdout the tail of the sorted
frame and cross-validation `TimeSeriesSplit`; omitting it gives a random split. A
`time_column` that is not a real column is a 422 rather than a silent fall back to
a random split — the leaky version would return 200 with flattering metrics and
nothing downstream would catch it.

## Architecture at a glance

- **FastAPI** backend, **SQLAlchemy 2.0** models (`datasets`, `chats`,
  `chat_messages`, `analyses` — no `users` table; a dataset id *is* its
  shareable link).
- Uploaded data is stored verbatim as **raw CSV text** in `datasets.data_csv`
  (single durable copy, no object store). Charts are re-rendered on demand from
  `data_csv` + a message's `tool_calls`; nothing is stored as image files.
- `profile_dataframe()` builds a **bounded rich profile** (schema, `describe()`,
  cardinality-gated value counts, capped correlations, sample rows) within a
  token budget — this is what Claude reads.
- **Judge-gated LLM loop** (issue #9): an analyst pass reads the profile, picks
  tools, and writes the prose; the backend **validates every tool call** against
  the profile and renders the charts; a separate judge pass then scores the
  attempt (0-100) against the actual rendered charts + stats. The loop repeats,
  feeding the analyst its own charts/stats and the judge's feedback, until the
  score clears a threshold or a pass cap is hit (default 3 passes) — a turn may
  take longer than a single API call as a result. Each answer carries a
  collapsible **loop trace** rendered with the tokenized UI — each pass is its
  own collapsible block with a color-coded judge-score badge, the analyst
  interpretation, judge feedback/gaps, and the revision fed to the next pass;
  model/tokens/latency/cost is demoted to a muted footer line, and the system
  prompt is never exposed. See `doc/project-1-llm-loop-design.md`.
- The frontend ships a **tokenized component system** (CSS-variable design
  tokens + a Radix-based primitive library) with light/dark themes and a
  refreshed Upload + Chat UI (issue #11, Slice A). The composer sends on
  **Enter** (Shift+Enter for a newline), the upload page has a styled file
  picker, and the raw-statistics panel offers a **Download JSON** export. A
  collapsible left rail groups everything you can open under the category that
  owns it — **Data** over your uploaded datasets, **Machine learning** over your
  experiments. Click a dataset to open its page; tick several and start one chat
  across all of them.

See `doc/project-1-csv-analysis-assistant-design.md` for the approved design and
the numbered design decisions (D2–D5, D2 now superseded by the judge-gated loop
in `doc/project-1-llm-loop-design.md`) referenced throughout the code.

## Development

Backend (from repo root):

```bash
make check        # CI gate: ruff + black --check + mypy (strict) + pytest
make test         # pytest only (ephemeral SQLite, no API key needed)
make lint         # ruff
make format       # black (auto-fix)
make type-check   # mypy backend/app (strict)
make migrate      # apply Alembic migrations (alembic upgrade head)
make migration m="describe change"   # autogenerate a migration from model changes
make eval         # retrieval quality over the committed golden set (real API + Postgres; see below)
```

Frontend (from `frontend/`):

```bash
npm test          # Vitest + React Testing Library (mocked fetch, no backend)
npm run build     # type-check (tsc) then production build
npm run type-check
```

Tests run against ephemeral SQLite; production uses Postgres via `DATABASE_URL`.

### Database migrations (Alembic)

The Postgres schema is managed by **Alembic** (`backend/alembic/`). On app
startup `init_db()` runs `alembic upgrade head`, so a fresh database is created
and an existing one is brought up to date automatically. To apply migrations
manually, run `make migrate`. After changing a model in `app/models.py`,
generate a migration with `make migration m="add foo column"`, review the
generated file under `backend/alembic/versions/`, then `make migrate`. (SQLite —
the local default and the test backend — skips Alembic and builds tables
directly from the ORM metadata.)

To reset a Postgres dev DB from scratch:

```bash
psql "$DATABASE_URL" -c "DROP SCHEMA IF EXISTS app CASCADE; DROP TABLE IF EXISTS public.alembic_version;"
make migrate
```

(The legacy `backend/db/schema.sql` is a Week-2 learning artifact — do not use
it to build the app database; it diverges from the ORM models.)

## Testing

### One-time: make the toolchain visible to your shell

Poetry and pyenv are not on `PATH` in a fresh terminal. Either prepend this to
each command, or add it to `~/.zshrc`:

```bash
export PATH="$HOME/.local/bin:$PATH"
eval "$(pyenv init -)"
```

The project pins Python **3.12** (`.python-version`) and uses **Poetry** for
deps; run `make install` first if you haven't. Run a single backend test file
with `poetry run pytest backend/tests/test_datasets.py -v`.

### Manual testing against a live server

Start the backend with `make dev` — serves on **http://127.0.0.1:8000** and
writes to a local SQLite `dev.db` (the default `DATABASE_URL`), so uploads and
chats persist across restarts. Delete `dev.db` to reset. Interactive API docs
(Swagger) are at **http://127.0.0.1:8000/docs** — you can upload a CSV and
try endpoints straight from the browser there.

Exercise the dataset + chat flow with the curl walkthrough above, then check
these error paths:

```bash
# unknown dataset id -> 404
curl -i http://127.0.0.1:8000/datasets/nope

# non-.csv file -> 400
echo hi > /tmp/notes.txt
curl -i -X POST http://127.0.0.1:8000/datasets -F "file=@/tmp/notes.txt;type=text/plain"

# header-only / no data rows -> 400
printf 'a,b\n' > /tmp/empty.csv
curl -i -X POST http://127.0.0.1:8000/datasets -F "file=@/tmp/empty.csv;type=text/csv"
```

| Case | Expected status |
| --- | --- |
| valid CSV upload | 200 |
| get existing dataset | 200 |
| get unknown id | 404 |
| non-`.csv` file | 400 |
| header-only CSV | 400 |
| over `MAX_UPLOAD_BYTES` | 413 |
| over `MAX_ROWS` | 413 |
| unknown dataset id in `POST /chats` | 404 |
| empty `dataset_ids` in `POST /chats` | 400 |

### Inspecting the stored profile

`DatasetOut` returns only `id/name/n_rows/n_cols` — the full bounded rich
profile that Claude reads is persisted in `datasets.profile_json` and isn't
exposed via an endpoint. To eyeball it (uses `dev.db`):

```bash
poetry run python -c "from app.db import SessionLocal; from app.models import Dataset; import json; s=SessionLocal(); d=s.query(Dataset).first(); print(json.dumps(d.profile_json, indent=2))"
```

## Configuration

Backend settings live in `app.config.Settings`, overridable per-environment via
`.env` (copy `.env.example`):

| Key | Purpose |
| --- | --- |
| `ANTHROPIC_API_KEY` | **Required for `/chat`.** Your Anthropic key. |
| `ANTHROPIC_MODEL` | LLM model id (default `claude-sonnet-5`). |
| `ANTHROPIC_MAX_TOKENS` | Max output tokens per call (default 4096). |
| `DATABASE_URL` | `sqlite:///./dev.db` by default; Postgres in production. |
| `MAX_UPLOAD_BYTES`, `MAX_ROWS` | Upload caps. |
| `CORS_ALLOW_ORIGINS` | Allowed frontend origins (prod only; dev uses the Vite proxy). |
| `PROFILE_MAX_CARDINALITY`, `PROFILE_MAX_CORR_COLS`, `PROFILE_TOP_CORR_PAIRS`, `PROFILE_SAMPLE_ROWS`, `PROFILE_TOKEN_BUDGET` | Profiler tunables. |
| `LLM_MAX_PASSES` | Max analyst passes per turn in the judge-gated loop (default 3). |
| `LLM_QUALITY_THRESHOLD` | Judge score (0-100) that stops the loop early (default 80). |
| `JUDGE_MODEL` | Model id for the judge call; empty (default) reuses `ANTHROPIC_MODEL`. |
| `VOYAGE_API_KEY` | **Required for `make embed` and `/agent/chat`.** Your Voyage AI key. |
| `VOYAGE_MODEL` | Embedding model (default `voyage-4`). Changing it invalidates every indexed vector — they are not comparable across models, so re-run `make embed` from scratch. |
| `AGENT_MAX_TURNS` | Tool-calling turns the agent may take (default 6). It always gets one further, tool-free call to answer. |
| `OTEL_ENABLED` | Export OpenTelemetry traces (default off). See `make db-up` for a local Jaeger at :16686. |

The frontend reads `VITE_API_BASE` (see `frontend/.env.example`); it defaults to
`/api`, which the dev server proxies to the backend — no change needed for local
development.

## Documentation

- `doc/user-manual.md` — task-oriented guide: setup, asking questions, training models, the review queue, troubleshooting
- `doc/architecture.md` — student-oriented architecture overview with diagrams, covering both the analysis and experiment halves
- `doc/deploy-runbook.md` — how the live Render + R2 deploy was done, in order, including the failures worth not repeating
- `backend/eval/results/` — committed retrieval-quality reports: `baseline.md` and the pre-registered `sweep.md`
- `doc/project-1-csv-analysis-assistant-design.md` — approved design + decisions
- `frontend/README.md` — frontend-specific dev notes
- `CLAUDE.md` — guidance for working in this repo
