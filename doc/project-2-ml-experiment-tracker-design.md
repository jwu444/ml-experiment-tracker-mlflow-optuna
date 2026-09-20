# Project 2 — ML Experiment Tracker: Architecture Design

**Status:** Approved (brainstorm), 2026-08-04. Forks Project 1 (CSV Analysis Assistant).
**Scope:** Weeks 5–8 of the workshop (§3.2 of `workshop-program-overview.md`).

---

## 1. Summary

Project 2 extends the Project 1 fork with an ML experiment tracker: the student trains
models (domain of their own choosing — classification, regression, etc.), logs every run
to MLflow, tunes hyperparameters with Optuna, and can ask natural-language questions over
their experiment history ("which model performed best on dataset X?", "what hyperparameter
ranges have I tried?"). A hand-rolled retrieval-augmented agent answers those questions and
suggests next experiments. Everything is instrumented with OpenTelemetry and gated by CI.

This document's architecture is **domain-agnostic by design**, but §2 below names a
concrete candidate domain — computer component market pricing/demand — to ground the
experiment schema and retrieval design in something real ahead of the student's own Week 5
scoping (§3.2: "Intern Student picks the ML domain"). Nothing architectural here should
need to change if that candidate is refined or replaced, as long as the domain stays
tabular/scikit-learn-shaped.

---

## 2. Problem Space & Project Domain

**Candidate domain:** computer component (GPU, CPU, RAM, storage, etc.) pricing and
demand — market trends and consumer behavior in the PC-hardware market.

**Driving question:** what events, developments, variables, or trends dictate the price
and demand for specific types of computer components? Sub-questions a student could turn
into concrete experiments (each a candidate feature set / label for a model in D1's
generic `fit(X, y) → metrics` loop):

- How do supply-side shocks (foundry capacity constraints, tariffs, chip shortages,
  crypto-mining demand surges) move component prices over time?
- Does consumer-side signal (Steam Hardware Survey adoption trends, search interest) lead
  or lag price movements for a given component category?
- Can historical price series + macro/demand signals predict near-term price direction or
  magnitude for a component category (e.g. "will GPU prices for this tier rise next
  month")?

This is a **candidate** domain — concrete enough to ground the experiment schema and
retrieval design in something real, but the architecture (D1) stays generic so a different
dataset within this domain, or a different domain entirely, doesn't require a redesign.

### 2.1 Candidate public data sources

**Component pricing & specs (historical, downloadable)**
- [Historical GPU Prices — NVIDIA and AMD](https://www.kaggle.com/datasets/mannacharya/historical-gpu-prices-nvidia-and-amd/data) (Kaggle)
- [GPU Price dataset](https://www.kaggle.com/datasets/hchsmost/gpu-price) (Kaggle)
- [CPU and GPU Product Data](https://www.kaggle.com/datasets/michaelbryantds/cpu-and-gpu-product-data) (Kaggle)
- [GPU Specs, 1986–2026](https://www.kaggle.com/datasets/ellimaaac/gpus-specs-from-1986-to-2026) (Kaggle)
- [PC Part Dataset / docyx/pc-part-dataset](https://github.com/docyx/pc-part-dataset) (GitHub, **MIT**) —
  PCPartPicker component tables as plain CSV: `video-card.csv` (6,636 rows) and
  `cpu.csv` (1,413 rows), each with `price` plus spec columns. **This is the
  dataset Phase 1 actually ingests** (`make data-fetch`) and Phase 2 trains on;
  the entries above remain reference alternatives. No API credentials needed, and
  the MIT license makes redistribution unambiguous.

  **Caveat on usable rows.** `price` is sparse: null in 5,361 of 6,636 video-card
  rows (80.8%) and 866 of 1,413 CPU rows (61.3%), leaving **1,275 and 547 rows**
  with a usable regression target. `boost_clock` is also 38% null on video cards.
  The row counts above describe the files, not the trainable data — Phase 2 must
  either drop null-target rows explicitly or pick a denser source. Treated as an
  example dataset, not a committed one.
- [Features and Price of Computer Components](https://www.kaggle.com/datasets/mohanedalsuwaigh/features-and-price-of-computer-components) (Kaggle)

**Live/interactive price-trend references (browse only, no bulk export)**
- [PCPartPicker Trends](https://pcpartpicker.com/trends/) — category-level price trend
  charts, e.g. [video cards](https://pcpartpicker.com/trends/price/video-card/),
  [memory](https://pcpartpicker.com/trends/price/memory/). No official bulk-download API —
  useful for eyeballing/validating a trend, not as a direct training-data feed.

**Consumer demand / adoption proxies**
- [Steam Hardware & Software Survey](https://store.steampowered.com/hwsurvey/Steam-Hardware-Software-Survey-Welcome-to-Steam) (current, Valve's own page)
- Historical Steam HSS archives (community-scraped): [myagues/steam-hss-data](https://github.com/myagues/steam-hss-data) (2004–2021), [jdegene/steamHWsurvey](https://github.com/jdegene/steamHWsurvey)

**Macro / supply-side market signals**
- [FRED — Producer Price Index, semiconductor manufacturing](https://fred.stlouisfed.org/series/PCU334413334413M) (St. Louis Fed; browse the same FRED category for related component-adjacent industry PPI series)
- [Semiconductor Industry Association — market data](https://www.semiconductors.org/data-resources/market-data/)
- [World Semiconductor Trade Statistics (WSTS)](https://www.wsts.org/) — industry billings/shipments; headline releases are public, more detail is behind a paid subscription

**Search-interest demand signal**
- [Google Trends](https://trends.google.com/trends/) — free, per-query CSV export (e.g.
  search interest for "GPU price" or "graphics card shortage") as a leading/lagging
  demand-interest feature

**Caveat:** check each Kaggle dataset's individual license before redistribution, and note
that PCPartPicker/Newegg/Amazon restrict automated scraping in their terms of service —
the static Kaggle/GitHub snapshots above are fine for coursework; live scraping of those
sites is not something this project should do without checking ToS compliance first.

---

## 3. Key decisions (and why)

**D1 — Candidate domain identified (§2); architecture stays generic.** §2 names a concrete
candidate domain and driving question, but the experiment schema, training module, and
retrieval design still assume only a generic scikit-learn-style `fit(X, y) → metrics`
loop — nothing here is hard-coded to computer-component data. The design holds even if
Week 5 scoping narrows to a specific component category, swaps in a different dataset
within this domain, or shifts to a different domain entirely.

**D2 — No auth; stays single-tenant.** Project 1's D4 ("no users table, no auth") carries
forward. Project 1's `CLAUDE.md` currently has a stale note claiming "Project 2 forks this
repo to add a real agent loop and auth" — that line is wrong per this decision and gets
corrected as part of the Project 2 doc sync (§13 amendment).

**D3 — The app runs its own training, not just ingestion.** `app/training.py` contains the
actual model-fitting code, invoked via an API endpoint. This is the more hands-on-ML option
and keeps training, tuning, and logging in one code path (D4 below) rather than treating
this app as a read-only layer over externally-produced MLflow runs.

**D4 — MLflow backend: same Postgres instance, separate schema; local artifact dir.**
`MLFLOW_TRACKING_URI` points at the existing Postgres database under a dedicated `mlflow`
schema (MLflow manages its own tables there — not modeled by our ORM). Artifacts (model
pickles, plots) go to a local `mlruns/` directory (gitignored). No new paid service, and it
keeps one Postgres instance as the source of truth for both the app's own tables and
MLflow's, echoing Project 1's D5 "no object store" philosophy. Trade-off: `mlruns/` is
ephemeral on Render/Fly free-tier filesystems — acceptable since MLflow's own UI is only
ever run locally/on demand for development inspection, never as a public-facing service
(see D10; the public-facing experience lives in the app's own frontend, D9).

**D5 — Dataset linkage: reuse Project 1's `Dataset` table, with a fallback.**
`experiments.dataset_id` is a **nullable** FK into the existing `datasets` table (works
cleanly for a tabular/CSV domain — the common case for §3.2's examples). A
`dataset_version` free-text column supplements or substitutes it if the eventual domain
isn't CSV-shaped. This is a fallback, not a redesign trigger.

**D6 — Retrieval is RAG-style, two-path** (per explicit instructor steer). Free-text
`notes` are chunked and embedded into `experiment_note_chunks` (pgvector); structured
fields (`model_type`, `hyperparams`, `metrics`) are queried via ordinary SQL, not embedded.
**Explicitly left open:** the exact strategy for reconciling/merging the two result sets
inside the agent — resolved during Week 5–6 detailed design, not here. **Now resolved
(2026-08-10) as pre-filter-then-rank — see D15 in
`doc/plans/2026-08-10-project-2-phases-2-4-design.md`.**

**D7 — Agent is a hand-rolled tool-calling loop, not a framework.** `app/agent.py` mirrors
`app/loop.py`'s shape: a plain Anthropic tool-calling loop (no LangChain/LangGraph). Keeps
the mechanics visible per §3.2's "Tool use (function calling, schemas, error handling)"
topic, and stays consistent with Project 1's existing style.

**D8 — Observability: homegrown OpenTelemetry, not LangSmith.** Spans wrap each Claude
call, each tool call, and each retrieval in both `agent.py` and (retroactively) `loop.py`.
Viewed via a local Jaeger instance (docker-compose, free). No external vendor/account
dependency.

**D9 — Frontend: extend the existing React app, not a second Streamlit dashboard.** New
pages (`ExperimentsPage`, `ExperimentChatPage`) reuse Project 1's Radix + CSS-token UI
system. `ExperimentsPage` also owns run browsing/comparison for end users — it queries
MLflow's tracking store via its SDK/REST API and renders params/metrics itself, rather than
sending users to MLflow's own UI. MLflow's own UI stays a local/dev inspection tool only.

**D10 — Resolved: MLflow UI never needs public hosting.** Superseded by D9. Since
experiment browsing/comparison is built into the application's own frontend, MLflow's
standalone UI (`mlflow ui`/`mlflow server`) is only ever run locally/on demand for
development inspection — no public-hosting decision needed, and D4's ephemeral-filesystem
trade-off on Render/Fly free tier doesn't apply to it.

**D11 — Optional commercial-tool extensions are out of scope.** §3.2 lists Snowflake,
Databricks SQL Warehouse, Tableau, Power BI, and BigQuery as optional stretch extensions.
None are designed against here (see §11).

### Known simplifications / revision points

- D5's dataset FK assumes a CSV-shaped domain; if the student picks a non-tabular domain,
  expect a follow-up doc (same pattern as Project 1's issue-specific design docs).
- D6's merge strategy is open by design — expect an amendment once resolved.

---

## 4. Architecture

```
frontend/ (React + Vite, extended)
  UploadPage, ChatPage            (existing, unchanged)
  ExperimentsPage                 (new: list/filter logged experiments)
  ExperimentChatPage              (new: NL query -> agent -> recommendation + trace)
        │  HTTPS/JSON
        ▼
backend/app/ (FastAPI, extended)
  training.py   -- train(model_type, hyperparams, dataset) -> fits model, logs to MLflow
  tuning.py     -- Optuna study wrapping training.objective()
  embeddings.py -- chunk + embed experiment notes -> pgvector (D6)
  agent.py      -- hand-rolled tool-calling loop (D7): search_experiments, get_experiment_detail
  tracing.py    -- OTel span helpers, used by agent.py + (retrofit) loop.py
        │
        ├──────────────────────────────┬───────────────────────────┐
        ▼                              ▼                           ▼
┌───────────────────┐        ┌──────────────────┐        ┌──────────────────┐
│ Postgres           │        │ mlruns/ (local)  │        │ Jaeger (local,   │
│  app schema:        │        │  MLflow artifact │        │  docker-compose) │
│   datasets, chats   │        │  store (models,  │        │  OTel trace      │
│   (existing)        │        │  plots)          │        │  viewer          │
│   experiments (new) │        └──────────────────┘        └──────────────────┘
│   experiment_note_  │
│    chunks (new)     │        ┌──────────────────┐
│  mlflow schema:      │◀──────│ MLflow tracking  │
│   (owned by MLflow,  │       │ (runs, params,   │
│    not our ORM)      │       │  metrics) via SDK│
└───────────────────┘        └──────────────────┘
```

**Deployment note:** the main FastAPI+React app deploys the same way Project 1 does
(Render/Fly free tier), and it's the only thing that needs a public URL. MLflow's tracking
store lives in the same Postgres instance (D4), so no second database to provision, and
per D9/D10 its own UI never needs public hosting — only its local artifact directory
matters, and only for local/dev runs.

---

## 5. Components

1. **Training module (`app/training.py`)** — the actual `fit`/`predict`/`score` code for
   whatever domain the student picks (D1, D3). Exposes an `objective(trial_params) ->
   metrics` shape so Optuna can drive it directly. Every call logs params/metrics/artifacts
   to MLflow via its SDK, against the Postgres-backed tracking store (D4).
2. **Tuning module (`app/tuning.py`)** — an Optuna `Study` whose objective is
   `training.objective()`. Each trial is itself an MLflow run — tuning and single-run
   training share one logging path.
3. **Embeddings module (`app/embeddings.py`)** — chunks and embeds `experiments.notes`
   text into `experiment_note_chunks` (D6). Structured fields are never embedded; they're
   queried via SQL by the agent directly.
4. **Agent (`app/agent.py`)** — hand-rolled tool-calling loop (D7). Tools:
   `search_experiments` (vector search over note chunks + SQL filter over structured
   fields — merge logic open per D6) and `get_experiment_detail` (full run by id). Loops
   until Claude returns a final answer or `max_turns` is hit. Returns the answer, the
   retrieved experiments, and a full per-step trace (rendered in `ExperimentChatPage`, same
   spirit as Project 1's `PassTrace`).
5. **Tracing (`app/tracing.py`)** — OTel span helpers (D8) wrapping every Claude call, tool
   call, and retrieval in both `agent.py` and (retrofit) `loop.py`. Exported to a local
   Jaeger instance.
6. **Persistence layer (extended)** — Postgres `app` schema gains `experiments` and
   `experiment_note_chunks`; MLflow owns its own tables in a separate `mlflow` schema,
   accessed only through its SDK, never through our ORM.

---

## 6. Data flow

### Flow A — Log a single training run
```
POST /experiments/train {model_type, hyperparams, dataset_id | dataset_version, notes}
   1. app/training.py fits the model, logs params/metrics/artifacts to MLflow as it runs
   2. INSERT experiments row (mlflow_run_id, dataset_id nullable FK, dataset_version, notes)
   3. app/embeddings.py chunks + embeds `notes` -> experiment_note_chunks
        ◀─ returns experiment_id + mlflow_run_id
```

> **Amended 2026-08-10 (D17).** Step 3 is no longer inline. Embedding runs as a batched,
> idempotent backfill, and note enrichment moved into `scripts/seed_experiment_history.py`.
> Flow B creates one row per trial, so inline enrichment would have meant ~20 Claude and ~20
> Voyage calls inside one synchronous request. See
> `doc/plans/2026-08-10-project-2-phases-2-4-design.md` §D17.

### Flow B — Hyperparameter tuning (Optuna)
```
POST /experiments/tune {model_type, search_space, dataset_id | dataset_version, n_trials}
   1. Optuna Study runs n_trials, each calling training.objective(trial_params)
   2. Each trial logs to MLflow (as Flow A step 1) and gets its own `experiments` row
        ◀─ returns study summary + best trial's experiment_id
```

**Amended 2026-08-13 (Phase 2a).** The list above named four endpoints. A fifth
was needed and is now built:

```
PATCH /experiments/{id} {notes?, notes_status?}
   1. Edits the note text, or moves notes_status between draft/approved/rejected
        ◀─ returns the updated experiment
```

Splitting it out is what makes D20 enforceable. Both write flows create rows at
`notes_status = "draft"`, and this is the only route that moves one off it —
so writing note *text* is deliberately not an approval. `scripts/seed_experiment_history.py`
sends `{"notes": ...}` and nothing else, which is why machine-written notes
cannot approve themselves. An empty note cannot be approved (422); it can be
rejected. Phase 3 embeds approved notes only.

### Flow C — Ask the agent a question
```
User asks a question in ExperimentChatPage ─▶ agent endpoint
   1. app/agent.py: Claude call with search_experiments / get_experiment_detail tools
   2. search_experiments: embed query, vector search over experiment_note_chunks
        + SQL filter over structured experiment fields (merge strategy: open, D6)
   3. Claude may call tools -> results fed back -> loop continues (OTel span per step)
   4. Claude returns final answer + recommended next experiments
        ◀─ returns {answer, retrieved experiments, per-step trace} ─▶ UI renders trace
```

---

## 7. Data model (Postgres)

| Table | Schema | Key columns |
|---|---|---|
| `experiments` | `app` | `id`, `mlflow_run_id`, `dataset_id` (FK → `datasets.id`, nullable, D5), `dataset_version` (text, fallback), `model_type`, `notes`, `created_at` |
| `experiment_note_chunks` | `app` | `id`, `experiment_id` (FK → `experiments.id`), `chunk_text`, `chunk_index`, `embedding` (`vector`) |
| *(MLflow's own tables)* | `mlflow` | Owned entirely by MLflow's SDK/migrations (runs, params, metrics, tags) — not modeled by our ORM, never queried directly; always accessed via `mlflow` SDK calls (D4) |

- `hyperparams` and `metrics` values live in MLflow's own tables (params/metrics), **not**
  duplicated into the `experiments` row — the app queries MLflow's SDK for those, joining
  by `mlflow_run_id`, to avoid two sources of truth for the same numbers.
- No `users` table (D2) — `experiments` has no owner/user FK.

---

## 8. Error handling & guardrails

- Training failures (bad hyperparams, model fit errors) are caught in `app/training.py`
  and logged as a failed MLflow run (status=`FAILED`) rather than a silent 500 — the
  `experiments` row still gets created so the failure itself is queryable history.
- The agent validates tool-call args before executing (same pattern as Project 1's
  `validate_tool_call()` for chart tools) — never passes raw Claude output straight into a
  DB query.
- Optuna studies run with a bounded `n_trials` cap and per-trial timeout, so a runaway
  search space can't hang the endpoint indefinitely.

---

## 9. Testing & eval

- **Unit/integration (`make test`)** — training module tested with a tiny synthetic
  dataset (fast, deterministic), agent's tool-arg validation and merge logic (once decided,
  D6) tested against a fixed fixture set of experiments, same isolated-SQLite pattern as
  Project 1.
- **Retrieval evals** — precision@k, recall@k, MRR against a curated experiment query set
  the student builds once real experiment history exists (same eval-discipline pattern as
  Project 1's `make eval` golden set, retrieval-scoped instead of end-to-end).
- **CI (new, D-none — genuinely new capability, no prior Project 1 equivalent)** —
  `.github/workflows/ci.yml` runs `make check` (lint + format-check + type-check + test)
  and the frontend equivalent (`npm run type-check && npm test`) on every push/PR to
  `main`. Nothing like this exists yet in the forked repo.

---

## 10. Spec coverage (§3.2)

### 10.1 Acceptance criteria
- Log experiments, ask "which model performed best" / "what hyperparameter ranges have I
  tried" → Flow C (agent + retrieval)
- MLflow UI shows params/metrics/artifacts → D4 (Postgres-backed tracking store); the
  public-facing equivalent is `ExperimentsPage` (D9), which reads the same tracking store
- At least one Optuna study, logged to MLflow → Flow B
- Agent retrieves + recommends next experiments → Flow C, `agent.py`
- Retrieval quality measured → §9 retrieval evals
- Agent traces inspectable → D8 (OTel + Jaeger)
- CI passes on every PR → §9 CI
- README updated with new architecture diagram → doc-sync step, same as Project 1's
  document-sync requirement

### 10.2 Topics introduced
RAG (chunking/embeddings/retrieval — D6), ML experiment tracking (MLflow), Optuna
hyperparameter tuning, single-agent loop + tool use (D7), observability/tracing (D8),
retrieval-specific evals (§9), CI automation (§9).

---

## 11. Out of scope for Project 2

- **Snowflake, Databricks SQL Warehouse, Tableau, Power BI, BigQuery** (D11) — §3.2's
  optional stretch extensions for additional commercial-tool exposure. Not designed
  against; may be revisited as a genuinely separate stretch effort if time allows.
- **Auth / multi-tenancy** (D2) — still deferred, same as Project 1's D4.
- **Multi-agent coordination, text-to-SQL, production guardrails** — Project 3's scope
  (§3.3), not touched here.

---

## 12. Tech stack

React + Vite (extended) · FastAPI (extended) · Postgres (single instance, `app` +
`mlflow` schemas) · pgvector · MLflow · Optuna · Anthropic Claude API (hand-rolled tool
loop) · OpenTelemetry + Jaeger (local) · GitHub Actions (new CI) · pyenv + Poetry · ruff +
black + mypy · Render/Fly.io (deployment, same as Project 1).

---

## 13. Amendments

- **2026-08-04:** Initial design approved. Flags a required follow-up: Project 1's
  `CLAUDE.md` line "Project 2 forks this repo to add a real agent loop and auth" is stale
  per D2 (no auth) — correct it as part of this repo's doc sync before/alongside Week 5
  work landing.
- **2026-08-04:** Added §2 (Problem Space & Project Domain) — a candidate domain (computer
  component market pricing/demand) and curated public data sources, per instructor request.
  D1 updated to reference it; architecture itself is unchanged (still generic).
- **2026-08-04:** D10 resolved (no longer open): MLflow's standalone UI never needs public
  hosting because run browsing/comparison is built into the application's own frontend
  (D9, `ExperimentsPage`), per instructor confirmation. D9, D4, and the deployment note
  updated to match.
- **2026-08-09:** Phase 1 picked `docyx/pc-part-dataset` (MIT) as the working dataset over
  the other §2.1 entries — the Kaggle ones need per-account API tokens, which no script or
  CI job can assume. Ingested by `make data-fetch`; §2.1 records the choice and its
  null-`price` caveat. The dataset is an example to build against, not a frozen commitment.
- **2026-08-10:** Phases 2–4 design brainstormed against the shipped Phase 1 repo, not this
  document alone: `doc/plans/2026-08-10-project-2-phases-2-4-design.md`. Five decisions
  resolved there. **D12** — the ML task is hybrid: Phase 2 ships cross-sectional
  `price ~ specs` regression, because the ingested dataset has no date column and so cannot
  answer §2's temporal driving question; a temporal model follows as an additional
  `model_type`, and §2's question stays open rather than being quietly retired. **D13** —
  one data path: `training.py` reads only `datasets.data_csv`, and `make data-fetch` is
  repointed at the committed `data-sources/` snapshots, closing the duplication CLAUDE.md
  flags. **D14** — embeddings come from Voyage AI (Anthropic publishes no embeddings API);
  `EMBEDDING_DIM` stays 512, so no migration. **D15** — D6 resolved as pre-filter-then-rank.
  **D16** — a third CI job with a pgvector service container covers the Postgres-only `<=>`
  path, which the SQLite-only Phase 1 CI cannot reach. **D17 amends Flow A (§6):** embedding
  moves from inline to a batched backfill, and note enrichment moves out of the endpoints
  into `scripts/seed_experiment_history.py`. Flow B creates one row per trial, so inline
  enrichment would have put ~20 Claude calls and ~20 Voyage calls inside a single synchronous
  request and made two API keys a prerequisite for training a model.
