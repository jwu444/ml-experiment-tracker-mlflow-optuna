# Project 2 — ML Experiment Tracker: Overall Implementation Plan

> **Scope:** This is the *program-level* plan for all of Project 2. It divides the work into
> four phases and fixes their dependency order. Each phase spawns its own detailed,
> task-by-task plan in this folder (`doc/plans/YYYY-MM-DD-<topic>.md`) before that phase's
> code is written — the same pattern Project 1 used.

**Design spec:** `doc/project-2-ml-experiment-tracker-design.md`, amended by
`doc/plans/2026-08-10-project-2-phases-2-4-design.md` (D12–D21)
**Program spec:** `ai-engineering-workshop/doc/workshop-program-overview.md` §3.2 (private repo)
**Timeline:** 4 working weeks — Phase 1 in Week 5, Phases 2–4 over the following three. Phase 2
was split into **2a** and **2b** on 2026-08-11 (§9); both sit inside Week 6, and §7 records what
gets cut if they do not both fit.

---

## 1. Dependency map

The single hard constraint driving phase order: **nothing can be retrieved, evaluated, or
reasoned about until real experiment history exists.** That pushes training + tuning early
and retrieval + agent late, regardless of which is more interesting to build.

```
Phase 1 — Foundations
  CI ──────────────────────────────┐  (gates every later phase's "done")
  Docker/infra (pgvector, Jaeger)  │
      └─► Alembic migration        │
             (experiments,         │
              experiment_note_     │
              chunks)              │
  Domain dataset ingest ───────────┤
  Doc sync (stale auth line)       │
                                   │
Phase 2a — Dataset, training, MLflow, Optuna
  prepare_dataset.py ─► the modelling panel ─┐  (D18: it does not exist yet)
                                             ▼
  training.py ─┬─► POST /experiments/train ─┐
               └─► tuning.py ─► POST /experiments/tune
                                            ├─► GET /experiments[/{id}]
                                            │        └─► ExperimentsPage
                                            │              └─► PATCH /experiments/{id}
                                            │                    (note review, D20)
                                            └─► REAL EXPERIMENT HISTORY (drafts)
                                                        │
Phase 2b — EDA, diagnostics, chunk source types         │
  EDA over the prepared panel ──────────┐               │
  Diagnostics vs. a persistence baseline┤               │
  experiment_note_chunks.source_type ───┤               │
                                        ▼               ▼
                              HUMAN APPROVAL ◄── the gate (D20)
                                        │
Phase 3 — Retrieval + agent + tracing   │
  D6 merge strategy decided ─┐          │
  tracing.py ────────────────┤          │
  embeddings.py ◄────────────┴──────────┘  (approved rows only)
      └─► agent.py (search_experiments, get_experiment_detail)
             └─► POST /experiments/chat
                     │
Phase 4 — Agent UI, evals, ship
  ExperimentChatPage ◄─┘
  Retrieval evals (needs approved history + agent retrieval)
  README architecture diagram + deploy
```

**Why CI is task #1:** every subsequent phase's exit criterion is "CI green." Building it
last means four weeks of unverified merges and one enormous red build at the end.

**Why `tracing.py` precedes `agent.py`:** instrumenting the agent loop as it is written is
one task; retrofitting spans into a finished loop is a second, avoidable one. The retrofit
into Project 1's `loop.py` is cheap once the helpers exist.

**Why `embeddings.py` lands in Phase 3, not Phase 1:** it embeds `experiments.notes`. Notes
do not exist until Flow A runs, which is Phase 2a, and per D20 they are not *eligible* until a
human approves them, which is the end of 2b. Building it earlier means testing it against
fabricated rows and rewriting it against real ones.

**Why `prepare_dataset.py` precedes everything model-related (D18):** the training task has no
table to point at. SEC revenue facts are cumulative year-to-date, restatements overlap, and the
market and macro sources sit on four different frequencies — the modelling panel is something
we build, offline and deterministically, before a model can be fitted at all.

---

## 2. Phase 1 — Foundations and domain data *(Week 5, this week)*

**Goal:** a green, instrumented, migrated repo with a real computer-components dataset
loaded — nothing model-related yet.

| # | Deliverable | Depends on |
|---|---|---|
| 1.1 | `.github/workflows/ci.yml` — `make check` + `npm run type-check && npm test` on push/PR to `main` | — |
| 1.2 | Doc sync: correct Project 1's stale `CLAUDE.md` line ("…and auth" — false per D2); reframe this repo's `README.md`/`CLAUDE.md` as Project 2 | — |
| 1.3 | `docker-compose.yml`: Postgres **with pgvector**, plus a local Jaeger all-in-one service | — |
| 1.4 | MLflow tracking store provisioned against the same Postgres instance in an `mlflow` schema (D4); local `mlruns/` artifact dir gitignored | 1.3 |
| 1.5 | Alembic migration: `CREATE EXTENSION vector`, `experiments`, `experiment_note_chunks` (§7 columns exactly); SQLAlchemy models in `app/models.py` | 1.3 |
| 1.6 | Ingest one §2.1 dataset (computer-component pricing/specs) through Project 1's **existing** upload pipeline, producing a real `datasets` row for D5's FK | 1.5 |

**Exit criteria:** CI green on a PR. `make migrate` applies cleanly and rolls back. `docker
compose up` gives Postgres+pgvector and a reachable Jaeger UI. At least one real dataset row
exists and `GET /datasets` returns it.

**Notes:** 1.6 uses the existing `data-collection` branch's work. Per §2.1, use the static
Kaggle/GitHub snapshots — do **not** add live scraping of PCPartPicker/Newegg/Amazon.

---

## 3. Phase 2a — Dataset, training, MLflow, and Optuna *(Week 6)*

**Goal:** the system can run and log real experiments on a defensible dataset, and a human can
browse and review them.

Detailed plan: `doc/plans/2026-08-10-project-2-phase-2-training-mlflow-optuna.md`.

| # | Deliverable | Depends on |
|---|---|---|
| 2.1 | `scripts/prepare_dataset.py` + `data-sources/prepared/` — builds the candidate-#4 revenue-nowcast panel offline and deterministically from the committed snapshots (D18). Verified: 224 rows across AMD, DELL, HPQ, INTC, NVDA, 2011-08 → 2026-05 | 1.2 |
| 2.2 | **Single data path (D13):** `make data-fetch` uploads the prepared panel and the two pc-part tables; the duplicate access path is deleted | 2.1 |
| 2.3 | `app/training.py` — task-typed (`regression` \| `classification`) and time-aware: `ModelSpec` carries `objective_metric`, `direction`, and `cv_scoring` per registry entry; chronological holdout + `TimeSeriesSplit` when a `time_column` is given (D19); failed fits recorded as MLflow `status=FAILED` **and** still insert an `experiments` row (§8) | 1.4, 1.5, 1.6, 2.1 |
| 2.4 | `app/experiment_log.py` — the only module importing `mlflow`; `log_run` / `fetch_runs` / `search_runs` | 2.3 |
| 2.5 | `POST /experiments/train` — Flow A: fit → MLflow run → `experiments` INSERT → return `{experiment_id, mlflow_run_id}`. A typo'd `time_column` is a **422**, never a silent leaky random split | 2.3, 2.4 |
| 2.6 | `app/tuning.py` + `POST /experiments/tune` — Flow B: Optuna `Study` with a per-spec `direction`; one MLflow run **and** one `experiments` row per trial; bounded `n_trials` + per-trial timeout (§8) | 2.3 |
| 2.7 | `GET /experiments` (filterable by model type, task type, and review status) and `GET /experiments/{id}` — structured fields from our table, params/metrics joined from MLflow's SDK by `mlflow_run_id` (never duplicated, §7); degrades rather than 500s when the store is down | 2.5 |
| 2.8 | `PATCH /experiments/{id}` — edit a note, or move it to `approved`/`rejected`. Writing text is **not** approving it (D20) | 2.7 |
| 2.9 | `ExperimentsPage` — list, filter by task type, side-by-side compare, and the draft-note review panel; the app's public equivalent of the MLflow UI (D9/D10) plus D20's human half | 2.7, 2.8 |
| 2.10 | **Seed real history:** genuine Optuna studies over the prepared panel and one cross-sectional contrast, with meaningful free-text `notes` per run — all written as drafts | 2.6 |
| 2.11 | **Human review pass:** ≥20 of those notes read and approved (or rejected) in `ExperimentsPage` | 2.9, 2.10 |

**Exit criteria:** the panel rebuilds byte-identically; a tuning study of ≥20 trials is visible
in `ExperimentsPage` and in the MLflow store; every trial has params, metrics with `cv_std`,
and notes; ≥20 notes are approved. CI green. This satisfies §3.2's "at least one Optuna study,
logged to MLflow" acceptance criterion.

**2.10 + 2.11 are the phase gate for Phase 3** — deliverables, not a demo. Skipping 2.10 leaves
Phase 3 with nothing to embed; skipping 2.11 leaves it with nothing *eligible* to embed, since
D20 admits only approved rows.

---

## 3b. Phase 2b — EDA, diagnostics, and chunk source types *(Week 6, after 2a)*

**Goal:** the other two content types D21 requires, and an honest read on whether the models
are worth anything.

Detailed plan: `doc/plans/2026-08-14-project-2-phase-2b-eda-diagnostics.md` (10 tasks), against
the design at `doc/plans/2026-08-14-project-2-phase-2b-eda-diagnostics-design.md`. Split out on
2026-08-11 (§9); **implemented 2026-08-15/16**.

| # | Deliverable | Depends on | Status |
|---|---|---|---|
| 2b.1 | **EDA over the prepared panel** — distributions, per-ticker coverage, the correlation structure between market features and the target, written up as reviewable findings keyed by `dataset_id` | 2.1 | ✅ `POST /datasets/{id}/eda` |
| 2b.2 | **Diagnostics** — residuals against `quarter_end`, per-ticker error, learning curves, and a naive persistence baseline (`revenue_next = revenue`) that any model must beat before it is reported | 2.10 | ✅ `POST /runs/{id}/diagnostics` (shipped as `/experiments/{id}/diagnostics`; moved by the run-hierarchy split, D33/D37) + `MODEL_REGISTRY["persistence"]` |
| 2b.3 | `experiment_note_chunks.source_type` + migration — lets Phase 3 tell a note chunk from an EDA finding from a diagnostic interpretation (D21) | 1.6 | ✅ migration `9bb02e2c7392` |
| 2b.4 | Richer review — bulk approval and a draft-vs-edit diff. One-row-at-a-time is tolerable for 32 runs and not for 2b's output on top of them | 2.9 | ✅ `/review` (D26 opened-rows gate) |

### The baseline result — nothing beat it

Recorded here because 2b.2 exists to make this answerable, and the answer is not the
flattering one. On the shipped revenue panel (`revenue_nowcast.csv`, 224 rows, ~30-row
chronological holdout, target `revenue_next_usd`):

| Rank | Model | RMSE | R² |
|---|---|---|---|
| **1** | **persistence (baseline)** | **4,063,899,217** | 0.9389 |
| 2 | ridge (tuned) | 4,115,520,137 | 0.9374 |
| 3 | ridge (tuned) | 4,121,364,356 | 0.9372 |

**0 of 25 runs on this dataset beat "predict last quarter's revenue".** The best tuned
ridge is 1.3% *worse*, well inside the cross-validation fold spread, so the tuned models
are not distinguishable from the naive baseline on this panel. The generated EDA finding
independently explains why: `revenue_usd` correlates with `revenue_next_usd` at **r =
0.98**, and no other feature exceeds 0.33 — there is very little signal left for a model
to add once the lag is in the feature set.

This is the deliverable working as intended, not a failure of it. A working
experiment-tracking system that reports an unflattering result is worth more than a
winning number nobody can reproduce, and it is exactly why 2b.2 specifies that the
baseline is a logged run on the leaderboard rather than a figure quoted in prose (D25).

**Exit criteria:** EDA findings and diagnostic interpretations exist as approved rows; the
persistence baseline is recorded next to the tuned models, whether or not they beat it;
`source_type` is migrated. CI green.

**On the baseline:** 224 rows is a small panel. If nothing beats persistence, that is the
finding, and it gets written down rather than buried — the project's deliverable is a working
experiment-tracking system, not a winning model.

---

## 4. Phase 3 — Retrieval, agent, and tracing *(Week 7)*

**Goal:** natural-language questions over experiment history, fully traced.

| # | Deliverable | Depends on |
|---|---|---|
| 3.1 | **Resolve D6** — decide how vector hits over note chunks reconcile with SQL filters over structured fields (pre-filter / post-filter / score-fuse). Record as a design-doc amendment | 2.10 |
| 3.2 | `app/tracing.py` — OTel span helpers, Jaeger exporter wiring | 1.3 |
| 3.3 | Retrofit spans into Project 1's `app/loop.py` — proves the helpers on existing code before the agent depends on them | 3.2 |
| 3.4 | `app/embeddings.py` — chunk + embed the D21 content set (approved experiment notes, EDA findings, diagnostic interpretations, plus the five static research-question candidates) → `experiment_note_chunks`, tagged by `source_type`. **Only `notes_status == "approved"` rows are eligible (D20)**, which also means embedding cannot be called inline by Flow A — it runs on approval and as a backfill over reviewed history | 3.1, 2.11, 2b.3 |
| 3.5 | `app/agent.py` — hand-rolled tool loop (D7): `search_experiments` (per 3.1's merge strategy) and `get_experiment_detail`; **tool-arg validation before execution** (§8, mirrors Project 1's `validate_tool_call()`); `max_turns` cap; spans on every Claude call, tool call, and retrieval | 3.1, 3.2, 3.4 |
| 3.6 | `POST /experiments/chat` — Flow C: returns `{answer, retrieved_experiments, trace}` | 3.5 |

**Exit criteria:** "which model performed best?" and "what hyperparameter ranges have I
tried?" both return correct, grounded answers over the approved Phase-2 history, and the full
agent run is inspectable as a span tree in Jaeger. CI green.

**"Best" is now task-scoped.** `experiments.task_type` exists precisely because an `rmse` and
an `f1_macro` do not belong in one ranking, so `search_experiments` must not compare across
task types — and the agent's answer to "which model performed best?" has to say *at what*.

---

## 5. Phase 4 — Agent UI, evals, and ship *(Week 8)*

**Goal:** close every remaining §3.2 acceptance criterion.

| # | Deliverable | Depends on |
|---|---|---|
| 4.1 | `ExperimentChatPage` — NL input, answer, retrieved-experiment cards, per-step trace rendering (same spirit as Project 1's `PassTrace`) | 3.6 |
| 4.2 | Curated retrieval eval set — hand-labelled queries with known-relevant experiments, drawn from real Phase-2 history. D20's approval state gives "known-relevant" a defensible definition: a human already read those notes | 3.6 |
| 4.3 | `make eval` (replacing the current stub) — precision@k, recall@k, MRR; reports per-query and aggregate | 4.2 |
| 4.4 | Tune retrieval against 4.3's numbers — chunk size, `k`, and the D6 merge strategy are the knobs; record the before/after in a design-doc amendment | 4.3 |
| 4.5 | `README.md` new architecture diagram + `CLAUDE.md` sync (doc-sync rule) | 4.1 |
| 4.6 | Deploy the app (Render/Fly, as Project 1). MLflow's own UI is **not** deployed (D10) | 4.1 |

**Exit criteria:** all eight §3.2 acceptance criteria demonstrable. `make eval` prints real
retrieval numbers. CI green on `main`.

---

## 6. Acceptance-criteria traceability (§3.2)

| §3.2 acceptance criterion | Lands in |
|---|---|
| Log experiments; ask "which model performed best" / "what ranges have I tried" | 2.5, 3.6 |
| MLflow UI shows params/metrics/artifacts | 1.4, 2.9 (app-side equivalent per D9/D10) |
| At least one Optuna study, logged to MLflow | 2.6, 2.10 |
| Agent retrieves relevant experiments and recommends next ones | 3.5, 3.6 |
| Retrieval quality measured | 4.2, 4.3, 4.4 |
| Agent traces inspectable | 3.2, 3.3, 3.5 |
| CI passes on every PR | 1.1 |
| README updated with new architecture diagram | 4.5 |

---

## 7. Risks and the slip order

If the schedule compresses, cut in this order — later items are load-bearing for the
acceptance criteria, earlier ones are not:

1. **`ExperimentsPage` compare view** (2.9) — degrade to a plain list; the acceptance
   criterion only needs params/metrics visible. The review panel in the same deliverable is
   **not** cuttable — without it nothing is approved and Phase 3 has no corpus.
2. **Richer note review** (2b.4) — bulk approval and the draft-vs-edit diff are conveniences;
   32 rows can be reviewed one at a time.
3. **EDA and diagnostic content types** (2b.1, 2b.2) — D21 wants three content types in the
   index; Phase 3 works with experiment notes alone. Cutting these narrows the corpus and
   makes the retrieval evals less interesting, but breaks no acceptance criterion. Keep the
   persistence baseline even if the write-up goes: knowing whether the models beat it is worth
   an hour.
4. **`loop.py` span retrofit** (3.3) — nice proof, but D8's criterion is satisfied by agent
   traces alone.
5. **Retrieval tuning pass** (4.4) — measuring (4.3) is the criterion; improving is not.

Do **not** cut: CI (1.1), the prepared dataset (2.1), the seeded history (2.10), the approval
pass (2.11), or the eval harness (4.3).

**Known risks:**
- *The 2a/2b split adds a phase without adding a week.* Both sit in Week 6. If they do not
  both fit, the slip order above cuts into 2b, not into 2a's gate — 2.10 and 2.11 are what
  Phase 3 consumes.
- *The panel is 224 rows, ~45 in the chronological holdout.* Differences smaller than the
  cross-validation fold spread are noise, which is why every metric is reported with its
  `cv_std` and why 2b.2 pins a persistence baseline. A tuned model that does not beat
  `revenue_next = revenue` is a finding to report, not a failure to hide.
- *MLflow + Alembic sharing one Postgres.* MLflow runs its own migrations in the `mlflow`
  schema. Verify in 1.4 that our Alembic autogenerate does **not** try to drop MLflow's
  tables — restrict `target_metadata` / `include_object` to the `app` schema.
- *D6 is still open.* 3.1 is scheduled as its own deliverable rather than a decision made
  mid-implementation. If it slips, 3.4 and 3.5 both stall.
- *Embedding cost and model choice.* Not yet decided; settle it inside 3.4's detailed plan.
- *Approval is a human bottleneck.* D20 makes a person the gate between Phase 2 and Phase 3.
  Budget the time explicitly — 32 notes read against their params is an hour, not a minute —
  and do not let "approve everything unread" become the workaround, since that voids the eval
  set's definition of known-relevant in 4.2.

---

## 8. Out of scope

Per design §11: Snowflake/Databricks/Tableau/Power BI/BigQuery (D11), auth and
multi-tenancy (D2), and Project 3's multi-agent / text-to-SQL / production-guardrail scope.

---

## 9. Amendments

- **2026-08-05:** Initial overall plan written from the approved design.
- **2026-08-10:** Phase 1 complete. Detailed plan:
  `doc/plans/2026-08-05-project-2-phase-1-foundations.md`. Two decisions the plan
  forced and resolved: the embedding column width is pinned at 512 with the
  provider still open (the table is empty, so it is cheap to change), and
  `docyx/pc-part-dataset` (MIT) was selected over the §2.1 Kaggle sources, which
  all require a per-account API token that no script or CI job can assume.
  Two items carried into Phase 2: branch protection on `main` is still unset, and
  `data-sources/` duplicates the `make data-fetch` snapshot (see `CLAUDE.md`).
- **2026-08-11:** Mentor review of the Phases 2–4 design and the Phase 2 plan. Design amended
  with D18–D21 (`doc/plans/2026-08-10-project-2-phases-2-4-design.md`); this document updated
  to match. What changed here:
  - **Phase 2 split into 2a and 2b** (§3, §3b). 2a is the pipeline through to reviewed
    history; 2b is EDA, diagnostics, chunk source types, and richer review. Both are in
    Week 6 — the split reorders work, it does not buy time, and §7 records what gets cut.
  - **New deliverable 2.1, `prepare_dataset.py` (D18).** The modelling table was assumed to
    exist and does not: SEC revenue is cumulative year-to-date, restatements overlap, and the
    market and macro sources sit on four frequencies. Verified output: 224 rows across AMD,
    DELL, HPQ, INTC, NVDA, 2011-08 → 2026-05. This also amends D12, which assumed three
    tickers — `sec-edgar-revenue/` holds six, and AAPL is unusable for lack of a stock file.
  - **New deliverables 2.8 and 2.11 (D20).** Generated notes are drafts; a human approves them
    through `PATCH /experiments/{id}`, and only approved rows are eligible for embedding.
  - **3.4 can no longer embed inline from Flow A.** That was the plan when notes were final at
    creation. Under D20 they are drafts at creation, so embedding runs on approval and as a
    backfill over reviewed history.
  - **Renumbering.** Old 2.1→2.3, 2.2→2.5, 2.3+2.4→2.6, 2.5→2.7, 2.6→2.9, 2.7→2.10, with 2.1,
    2.2, 2.4, 2.8, and 2.11 new. §6's traceability table and Phase 3's dependencies follow.
  - Deliverable 2.2 closes the `data-sources/` versus `make data-fetch` duplication carried
    from Phase 1 (D13). Branch protection on `main` is **still** unset.
- **2026-08-13:** Phase 2a complete. Detailed plan:
  `doc/plans/2026-08-10-project-2-phase-2-training-mlflow-optuna.md` (11 tasks, PRs #31–#42).
  Phase 2b (EDA, diagnostics, the note-chunk source-type migration) is deliberately **not**
  covered here and gets its own plan, written now that 2a has landed. What the phase actually
  produced: a 224-row prepared panel, `/experiments/{train,tune}` over a `MODEL_REGISTRY`,
  MLflow-backed run storage, an `/experiments` page, and 32 seeded runs with reviewed notes.
  What diverged from the detailed plan:
  - **The seeding script's note comparator had to be re-keyed** from `task_type` to
    `(task_type, target_column)`. Every run in the seeded history is `regression`, but on two
    targets eight orders of magnitude apart — revenue in raw dollars against component price.
    Comparing across them told the note writer a panel run was "eight orders of magnitude
    worse than the best regression run", and it invented a target transformation to explain
    the gap rather than doubting the comparison. Generated commentary is only as good as the
    comparison it is handed, and a bad comparator produces confident fiction rather than a
    visible error.
  - **Pass 1 of the seeding script needed an idempotency guard.** Nothing dedupes an Optuna
    study, so a second `make seed-history` would have silently doubled the history into 64
    near-duplicate runs — invisible in the UI, corrosive to Phase 4's retrieval evals.
  - **Truncated LLM responses had to be rejected explicitly.** Checking that a response is
    non-empty does not catch a `max_tokens` cut, which yields *partial* text; 7 of the first
    32 notes landed stopping mid-word.
  - **`ui/Button` became a `forwardRef` component.** Radix's `asChild` slots hand the child a
    ref and use it to return focus when a dialog closes; a plain function component drops it
    and strands keyboard focus on `<body>`.
  - **Task 9's test harness departs from the plan's literal code.** The plan rendered
    `ExperimentsPage` bare, but the repo convention is that a page renders its own `AppShell`,
    whose sidebar uses router hooks and renders its own checkboxes. Tests wrap in
    `ThemeProvider` + `MemoryRouter` and stub `listDatasets`; every assertion is preserved.
  - **`experiment_log.search_runs` took a `max_results` bound.** MLflow's own default is 100k,
    which for an unfiltered call means materialising the whole store in one go.
  - **Three defects came out of PR review, not testing** — worth noting because none
    would have failed a test. `optuna_trial_timeout_s` was declared in `Settings` and
    passed nowhere, so the phase shipped a config knob that looked like a guard and
    was not one (removed; Optuna's `timeout=` bounds a study, not a trial).
    `study.optimize(catch=(Exception,))` swallowed failures of the persistence
    callback — a bad hyperparameter draw was already handled as `TrialPruned`, so the
    only thing `catch=` caught was the caller's DB write failing, which could leave
    the response naming one trial in `best_experiment_id` and another in
    `best_metrics` (dropped). And `/experiments`'s Reject button sent only the status,
    silently discarding whatever the reviewer had typed — the action most likely to
    be carrying an explanation. The pattern across all three: a guard that is absent,
    over-broad, or dropping input reads exactly like one that works.
  - Carried into Phase 2b: **branch protection on `main` is still unset** — now the third
    phase in a row. pgvector on Render's free tier remains unverified and blocks Phase 3 if
    it fails. `make check` still does not lint `scripts/`.
  - **Resolved 2026-08-14.** CI's `pull_request.branches` filter listed only `main` and
    `phase2a/**`, which would have left every Phase 2b stack PR unchecked. The filter is
    gone rather than extended: enumerating phases means each new one is unguarded until
    someone remembers it, and an unrun workflow is indistinguishable from a queued one.

- **2026-08-16:** Phase 2b complete. Detailed plan:
  `doc/plans/2026-08-14-project-2-phase-2b-eda-diagnostics.md`. All four deliverables
  (2b.1–2b.4) landed. The phase's shape held; what it added beyond the plan was
  `MODEL_REGISTRY["persistence"]` as a **real logged run** rather than a number quoted in
  prose (D25) — which forced `ModelSpec.preprocess = False` and an entry in
  `log_run`'s `skops_trusted_types`, neither of which the plan anticipated.

- **2026-08-23:** **"Experiment" was redefined** (issue #54, D33–D40). Detailed plan:
  `doc/plans/2026-08-22-project-2-experiment-run-hierarchy.md`; design at
  `…-experiment-run-hierarchy-design.md`. This is a rework, not a phase — it sits between
  2b and Phase 3 and is not in §1's dependency map, which predates it.
  - **What changed.** `app.experiments` meant one training run; it now means an
    *investigation*, and the runs moved to `app.runs` with a `NOT NULL` `experiment_id`.
    `dataset_id`, `dataset_version`, `target_column` and `task_type` moved up to the
    parent, so runs in one investigation are comparable by construction. Launching is
    nested (`POST /experiments/{id}/train|tune`) and there is deliberately no default
    experiment. Diagnostics re-keyed onto `runs.id` (D37) — a diagnostic scores one
    trained run, not the investigation containing it.
  - **Why it had to happen before Phase 3.** Note chunks carry `(source_type, source_id)`;
    keying them on the old `experiments.id` would have pointed retrieval at investigations
    once the split landed, and the table is empty until Phase 3 — so the cost of moving was
    a migration, not a backfill.
  - **What it cost.** A three-step migration chain (rename → add parent → contract) rather
    than one, because `ALTER TABLE … RENAME TO` leaves indexes under their old names and
    Alembic batch mode then trips over them in the *next* migration. Also: every document
    written before 2026-08-22 uses "experiment" in the old, single-run sense. That is
    signposted in `CLAUDE.md`, not retroactively rewritten.

- **2026-08-24:** Four UI issues closed on top of the rework, as a PR stack (#57–#60).
  None were planned deliverables; all four came out of using the app.
  - **#49 `/review` read/edit split.** An expanded row renders Markdown; **Edit** swaps in a
    textarea over the **raw source**. The status tabs re-issue the query rather than
    filtering client-side.
  - **#50 optimistic chat turns.** The question renders on submit and says "Not sent" if it
    fails, instead of vanishing for the length of a multi-pass loop.
  - **#51 the leaderboard's model filter.** Its options are derived from the loaded rows.
    The hardcoded `MODEL_TYPES` array it replaced had silently stopped covering
    `MODEL_REGISTRY` the moment `persistence` was added (D25).
  - **#52 launching runs from the UI** (`NewExperimentDialog`, `NewRunDialog`). Training was
    API-only until now. `GET /models` exists so the form reads the registry instead of
    restating it — #51's failure mode, prevented by construction; `ModelSpec.column_hyperparams`
    is what keeps `persistence`'s `prior_column` out of a frontend special case.
    Detailed plan: `doc/plans/2026-08-19-project-2-training-launch-ui.md`.

