# Project 2, Phase 4 — Evaluation, Recommendations, and Deploy

**Status:** approved design, not yet planned
**Date:** 2026-08-28
**Supersedes, where they conflict:** `doc/plans/2026-08-05-project-2-overall-implementation-plan.md` §5 and
`doc/plans/2026-08-10-project-2-phases-2-4-design.md` §5, §7. Both were written before Phase 3 shipped;
this document states current project state, and where the two disagree, this one wins.

---

## 1. Scope

Four workstreams and a doc-sync, landing as a stack of PRs the way Phase 3 did.

| # | Workstream | Deliverable |
|---|---|---|
| 4.1 | Corpus curation | ~23 approved sources spanning both experiments and all four model types; the rest rejected with a recorded reason; index reconciled by `make embed` |
| 4.2 | Eval harness | `make eval` reports precision@k / recall@k / MRR over a committed golden set |
| 4.3 | Retrieval tuning | A pre-registered configuration grid, swept, with the full result table committed |
| 4.4 | Agent recommendations | A third read-only tool over the ranked leaderboard, plus the prompt rule that uses it |
| 4.5 | Deploy | Dockerfile, `render.yaml`, managed Postgres with pgvector, MLflow artifacts on S3-compatible storage |
| 4.6 | Doc sync | README, CLAUDE.md, and the design docs reconciled |

New decisions: **D43**–**D48**. D42 is the highest number previously in use.

---

## 2. What this supersedes

Six statements in the existing documents are false as of today. Each is recorded here so that no
future reader has to work out which of two disagreeing documents describes the shipped system.

1. **`ExperimentChatPage` (outline 4.1) is already shipped**, as `AskPage`, in 3.6b. The outline's
   first Phase 4 task was complete before Phase 4 began.

2. **The eval's ground-truth unit is a source, not an experiment id.** The outline says "known-relevant
   experiment ids", written before D33 split *experiment* (an investigation) from *run* (one attempt).
   `retrieval.search_runs` returns `(source_type, source_id)` spanning `note`, `diagnostic` and `eda`;
   the last is keyed to a dataset and has no experiment id at all. See D43.

3. **`k` counts sources, not chunks** (3.4b). Precision@k is therefore a precision over *answers*, not
   over passages. The outline's `k` predates that change.

4. **CLAUDE.md's `make eval` description is wrong.** It describes Project 1's prose-keyword grader —
   tool selection, columns passed, keyword presence in the interpretation — over a golden set of chart
   questions. That suite was never built; the Makefile target is a bare `@echo`. Phase 4 repurposes the
   target for retrieval evaluation, and the paragraph must be rewritten in the same PR that lands 4.2,
   at which point it becomes actively misleading rather than merely aspirational.

5. **Design-doc open risk #2 — "model artefacts do not survive a deploy" — is resolved, not accepted.**
   D48 moves the artifact store to object storage. The risk register should record the resolution.

6. **Design-doc open risk #4 — "set branch protection on `main`" — is impossible, not deferred.** The
   repository is private on a free plan; the branch-protection API returns HTTP 403. It closes as
   won't-fix with that reason recorded, rather than being carried into a fifth phase as an open action.

---

## 3. Corpus curation (D45)

### 3.1 Current state

Measured against the live development database on 2026-08-28:

| Table | Rows | Approved |
|---|---|---|
| `app.runs` (notes) | 34 | **0** |
| `app.findings` | 6 (3 `eda`, 3 `diagnostic`) | 2 |
| `app.experiment_note_chunks` | 8 chunks | from 2 sources |

Run distribution: `revenue-nowcast` — ridge 8, gradient_boosting 8, random_forest 8, persistence 2;
`pc-part-video-card` — ridge 8. Note length averages 635–759 characters, except persistence at 90.

### 3.2 D45 — Approve a curated subset; reject the rest

**Approve all 6 findings.** Each addresses a distinct thing and none is redundant. The 3 EDA findings
are the only route to dataset-level questions: D30 expands every matching run to three chunk keys,
including `("eda", experiment.dataset_id)`, so without them "what do we know about this data" reaches
run notes only.

**Approve 17 of 34 run notes, stratified:** both persistence runs, 4 each of ridge / gradient_boosting /
random_forest in `revenue-nowcast`, and 3 of the 8 `pc-part-video-card` ridge runs. Reject the other 17.

Both persistence runs are approved deliberately. D25 makes the baseline a real logged run precisely so
it anchors comparisons; a corpus that omits it cannot answer "what's the baseline", which is the
question the baseline exists to make answerable.

**Within a stratum, select for outcome diversity, never for note quality.** Take the best run, the
worst, and middling ones. Approving the well-written notes instead would build an unrepresentatively
clean corpus, and every retrieval number measured against it would be optimistic in a way nothing about
the number reveals. It would also delete the failures from the history — the half the agent most needs
in order to recommend against repeating them (§5).

### 3.3 The curation is a committed manifest

`backend/eval/curation.yaml` lists `run_id → decision → reason`. A script applies it through
`PATCH /runs/{id}`, because scripts go through the API (D13) and must not bypass route validation.

Two reasons for the file rather than a review session:

- The corpus becomes reproducible from a clean database. The golden set (§4) is keyed by these ids, so
  a corpus that cannot be rebuilt is a golden set that cannot be trusted.
- The rejection reasons are recorded. `RunPatchRequest` has no reason field, and adding a column to
  `app.runs` to hold an evaluation artifact would put curation metadata in the application schema.

### 3.4 Projected corpus

**23 sources, approximately 41 chunks.** Notes at ~700 characters produce roughly one chunk each;
findings at 2,700–3,400 characters produce 3–5 rather than the naive 3, because a blank line is a hard
chunk boundary (D29) and these documents are section-structured.

### 3.5 The reap needs its own verification step

`backfill()` reaps by comparing *currently approved* against *currently indexed*. A note moving
`draft → rejected` was never indexed, so nothing is reaped — the 17 rejections in §3.2 do **not**
exercise the reap path. Only `approved → rejected` does.

Therefore, as an explicit step: approve one note, `make embed`, confirm its chunks are present; reject
it, `make embed`, confirm they are gone. This is the reap's only end-to-end exercise outside unit tests.

---

## 4. The eval harness (D43, D44)

### 4.1 D43 — Ground truth is `(source_type, source_id)`

The unit `search_runs` actually returns. Not experiment ids (see §2.2), and not chunk ids: `k` counts
sources, so a chunk-level ground truth would measure something the system does not return.

### 4.2 D44 — Queries are blind-drafted from structured data

Eval queries are written reading **only** the leaderboard, params and metrics — never the note prose —
and labelled for relevance afterwards.

The hazard this addresses is circularity, already flagged for note generation in
`doc/plans/2026-08-10-project-2-phases-2-4-design.md` §3.11 and sharper here: Claude wrote the draft
notes, so a query written while reading a note largely measures whether retrieval can find the document
the query was copied from. That is a real property, but a much weaker one than semantic retrieval, and
the resulting numbers would not distinguish the two.

The residual weakness is stated rather than hidden: the same author wrote both the notes and the
queries, so shared vocabulary survives blind drafting. The stronger design — queries written by someone
who has not read the corpus — remains available if the numbers ever need to bear more weight.

**This is a rule binding whoever extends the golden set, not a description of how the first 20 happened
to be written.** A set that is blind for its first 20 queries and note-derived for its next 20 reports a
single number over two incomparable halves.

### 4.3 The golden set

`backend/eval/golden_set.yaml`:

```yaml
- id: best-model-revenue
  query: "which model performed best on the revenue nowcast?"
  relevant:
    - [note, 3f2a...]
    - [note, 91bc...]
  notes: "drafted from leaderboard rank 1-2 only"
```

Approximately 20 queries across four shapes:

- **Which model won** — the workshop acceptance criterion's own words.
- **What ranges have I tried** — parameter-space questions.
- **What went wrong** — failure and diagnostic questions, answerable only because §3.2 curated for
  outcome diversity.
- **Dataset questions** that must reach an EDA finding, exercising the D30 key expansion.

### 4.4 Layout

`backend/eval/` as a package:

| File | Contents |
|---|---|
| `golden_set.yaml` | The queries and their labelled relevant sources |
| `curation.yaml` | The approval/rejection manifest (§3.3) |
| `metrics.py` | Pure: relevant set + ranked set in, precision@k / recall@k / MRR out |
| `cache.py` | The query-vector cache (§4.5) |
| `runner.py` | Loads the golden set, calls `retrieval.search_runs`, reports |
| `results/` | Committed sweep outputs (§5.3) |

`make eval` invokes the runner.

`metrics.py` is pure so that the arithmetic gets ordinary unit tests inside `make check` — no API key,
no Postgres. The metric computation is the part most worth pinning and the part a real-API suite tests
worst, because a real run's numbers have no independently known correct value.

### 4.5 The query-vector cache

A JSON file keyed by `(voyage_model, input_type, sha256(text))` → vector.

The Voyage free tier allows **3 requests per minute**. An uncached 20-query run therefore costs roughly
seven minutes of forced backoff, which means it does not get run, which means the harness does not do
its job. Cached, the first run pays that cost once and every rerun is free — which is what makes the
configuration sweep in §5 tractable at all, since query text is identical across configurations.

The model name is *in the key*. Changing `voyage_model` therefore misses and refetches rather than
serving stale vectors, and CLAUDE.md's rule that two models' vectors are not comparable holds without
anyone having to remember to clear a cache.

The cache is `.gitignore`d — it is a derived artifact and it is per-key. `--no-cache` forces a live run.

### 4.6 The harness never mutates the index

It reads through `retrieval.search_runs`, exactly as `POST /agent/chat` does. What it measures is the
production path, not a reimplementation that can drift from it.

---

## 5. Retrieval tuning (D46)

### 5.1 The knobs, and why they are not equivalent

`DEFAULT_MAX_CHARS` is a module constant in `app/embeddings.py`, not a setting. It is promoted to
`Settings.chunk_max_chars`.

**`backfill()` must thread that setting into both its indexing call and its skip check.** The skip check
is `current == chunk_text(source.text)` — it re-chunks the source with the *current* parameters and
compares — so a chunk-size change is correctly detected as "edited" and re-indexed, with no extra
machinery. Passing the setting to only one of the two call sites would make every source compare
unequal forever, re-indexing the entire corpus on every run.

The two classes of knob have very different costs:

| Knob | When it applies | Cost to change |
|---|---|---|
| `chunk_max_chars` | Index time | Full re-index: ~23 sources ≈ 8 minutes at 3 RPM |
| `chunk_overfetch` | Query time | Free — cached query vectors |

### 5.2 D46 — The grid and the selection rule are pre-registered

Written into this document before any of it runs:

| Knob | Candidates (default in bold) |
|---|---|
| `chunk_max_chars` | 600, **1000**, 1600 |
| `chunk_overfetch` | 2, **4**, 8 |

Nine configurations.

**`retrieval_top_k` is deliberately not in the grid.** It is the reporting parameter — precision@k — so
sweeping it changes what the metric *means* rather than improving the system.

Instead, retrieval runs at the default `retrieval_top_k = 8` for every configuration, and the metrics
truncate that one ranked source list at k ∈ {3, 5, 8}. Every configuration therefore issues exactly one
search per query, and the three cutoffs are three readings of the same result rather than three searches.

**The selection metric is MRR.** With 23 sources and 2–3 relevant per query, recall@8 will sit near 1.0
for nearly every configuration and discriminate nothing; reporting it as the headline would produce a
table of 0.95s and an arbitrary winner. MRR still moves. This is stated in advance so that the choice
cannot be made after seeing which metric favours which configuration.

**The adoption rule:** compute per-query paired MRR differences against the default configuration —
one difference per golden-set query. Adopt a challenger only if the mean of those differences is
positive **and** exceeds their standard error, `stdev(differences) / sqrt(n)`. Otherwise keep the
default and report that the sweep found nothing outside the spread.

This is the project's existing honesty convention applied to its own tuning: D38 already reports a
leaderboard win smaller than the leader's `cv_std` as "within noise". Nine configurations scored on
twenty queries, with the winner picked after the fact, would find a "winner" from pure noise
essentially every time. Pre-registration makes "no configuration beat the default" a reportable
*result* rather than an embarrassment to be avoided.

### 5.3 Output

`backend/eval/results/YYYY-MM-DD-sweep.md` — the full nine-row grid, committed, **including the losers**.
A sweep that reports only its winner is unfalsifiable.

---

## 6. The leaderboard tool (D47)

### 6.1 Shape

`get_leaderboard(experiment_id, limit=10)` — a third entry in `agent.TOOLS`, validated by the existing
`validate_tool_call` like the other two. Raw model output never reaches a function unchecked.

**Naming.** It operates on one investigation and returns that investigation's ranked *runs*.
"Leaderboard" is already this codebase's word for exactly that object — `GET /experiments/{id}/runs`
returns `LeaderboardOut`, and `ExperimentDetailPage` renders it — so the tool name matches vocabulary
the application already commits to. Under D41's rule, the model reads the tool name as part of its
contract, and a third word for an object that already has one is a prompt bug that presents as a
retrieval bug.

### 6.2 Implementation

Reuses `ranking.rank_runs` and `routes/shared.merge_runs` **directly, not over HTTP** — the same code
path the leaderboard page gets, so the agent and the UI cannot disagree about what rank 1 is.

Returns per row: rank, `run_id`, `model_type`, the run's params, the holdout primary metric, and
`cv_<metric>` with `cv_std`.

**A missing `cv_std` is `None`, never `0.0`** (D32). It matters more here than anywhere else: a
fabricated zero band makes every gap look decisive to a model that is about to recommend an experiment
on the strength of it.

**`limit` is bounded 1–50 and rejected, not clamped** — the same reasoning as `agent_max_k` (3.5).
Answering a request for 500 with 26 rows tells the model the investigation holds 26, and it will then
report that. The default of 10 keeps ordinary answers cheap; 50 covers `revenue-nowcast`'s 26 runs
whole, which "what ranges have I tried" genuinely needs.

**An unreachable tracking store returns a `tool_result` string, never a raise** — `_execute` never
raises (3.5). Unlike `get_run_detail` (D32), a degraded answer is meaningful here, because the ranks
come from our own rows.

### 6.3 Known limitation

`experiment_id` is required, so the model reaches a leaderboard *through* a search hit. An investigation
whose notes were all rejected in curation cannot have its numbers reached. This is accepted: the
alternative — enumerating experiments — adds a fourth tool for a two-experiment corpus.

### 6.4 Prompt

`prompts/agent.md` gains one rule: when asked what to try next, call `get_leaderboard` before
recommending; ground the recommendation in ranks and parameters actually tried; never propose a
configuration the leaderboard already shows losing; and when the gap between two runs is smaller than
the leader's `cv_std`, say the difference is within noise rather than naming a winner.

### 6.5 Tracing

A `tool.get_leaderboard` span carrying `experiment_id`, `limit`, `rows` — ids, counts and durations, no
row contents. Same rule as the retrieval spans (3.1).

---

## 7. Deploy (D48)

### 7.1 Topology: two Render services

A static site for the built SPA, a web service for the API, plus managed Postgres.

**Not a single origin.** `/experiments/:experimentId` is *both* a React Router path and a real API route
returning JSON. Serving the SPA from FastAPI requires a catch-all that would shadow or be shadowed by
the API, and the only clean fix is prefixing every backend route under `/api` — which changes
`/agent/chat`, the path D42 argues for by name. Two origins avoids the problem entirely, and
`Settings.cors_allow_origins` already exists for it, with a comment reading "prod only; dev uses the
Vite /api proxy".

### 7.2 Database

`CREATE EXTENSION IF NOT EXISTS vector` is already in migration `0b3ce28d4c61`, and `init_db()` runs
`alembic upgrade head` on Postgres at startup. pgvector needs no manual step on Render.

**MLflow's `mlflow db upgrade` is a release step, not a startup step.** It is another tool's migrations
against a shared database; running it in the application's startup path means every cold start races it.

### 7.3 D48 — Artifacts move to object storage

`mlflow_artifact_root` moves from `./mlruns` to an `s3://` URI on Cloudflare R2 (free tier 10 GB against
a current 126 MB). Adds `boto3` and `MLFLOW_S3_ENDPOINT_URL`.

This resolves design-doc open risk #2, which had accepted artifact loss on deploy. Without it,
`POST /runs/{id}/diagnostics` returns 409 forever on the deployed instance by design, since D24
refuses to refit from logged params.

**The migration is the non-obvious part.** MLflow stores absolute artifact URIs —
`mlflow.experiments.artifact_location` and `mlflow.runs.artifact_uri` — so syncing `mlruns/` to R2 is
not sufficient; those columns still name a local path that does not exist on Render.

The tempting alternative is to start the deployed store fresh and re-run training there. Training is
LLM-free (D17) so it is cheap, but it mints **new run ids**, and both `curation.yaml` and
`golden_set.yaml` are keyed by the existing ones. The corpus and its ground truth would silently stop
referring to anything that exists.

Therefore: `pg_dump` both schemas → restore to Render → sync `mlruns/` to R2 → a one-shot SQL script
rewriting those two columns. Ids are preserved and the golden set stays valid. It is a script in
`scripts/`, not an ORM change — D4's "never model MLflow tables in `app/models.py`" holds.

### 7.4 Configuration

New or changed environment: `DATABASE_URL`, `CORS_ALLOW_ORIGINS`, `MLFLOW_TRACKING_URI`,
`MLFLOW_ARTIFACT_ROOT`, `MLFLOW_S3_ENDPOINT_URL`, R2 access keys, `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`.
`.env.example` gains every one of them.

OpenTelemetry stays **off**: there is no collector, and Jaeger remains a local tool.

### 7.5 Free-tier caveats, documented in the README

Render free web services sleep after inactivity, so the first request after a quiet period takes roughly
50 seconds. Free managed Postgres expires after 30 days. A visitor should read this rather than
discover it.

---

## 8. Testing

### 8.1 In `make check` (offline, SQLite, no API keys)

- **`metrics.py`** — precision@k, recall@k and MRR against hand-computed ranked lists, including the
  degenerate cases: nothing relevant retrieved, a relevant source at rank 1, and `k` larger than the
  result set.
- **The curation applier** — through the existing `client` fixture, confirming it PATCHes rather than
  writing to the database directly.
- **`get_leaderboard`** — the `limit` bound rejected not clamped, an unknown `experiment_id` returning a
  string rather than raising, and an unreachable tracking store doing the same.

### 8.2 Not in `make check`

The eval runner. It needs a real `VOYAGE_API_KEY` (at least on a cold cache) **and Postgres with
pgvector** — the similarity query has no SQLite equivalent, so unlike `make test` the harness cannot
run on the default backend at all. Deliberately non-hermetic, and kept out of `make check` for the
same reason `make eval` always has been.

### 8.3 Unchanged

`pytest -m postgres` and the `backend-postgres` CI job. The sweep adds no SQL.

### 8.4 Deploy

No automated test; a documented smoke checklist. One item on it is the actual proof: **run diagnostics
on a run whose artifact now lives in R2.** Health checks and page loads pass with a broken artifact
store.

---

## 9. Document sync

Performed in the PR that causes each change, not as a cleanup at the end.

| Document | Change |
|---|---|
| `CLAUDE.md` | Rewrite the `make eval` paragraph (§2.4 — it becomes actively wrong when 4.2 lands); add sections for D43–D48 |
| `README.md` | Architecture diagram, the eval workflow, the deploy and its caveats |
| `doc/plans/2026-08-10-project-2-phases-2-4-design.md` | Risk #2 closed as resolved (§7.3); risk #4 closed as won't-fix with the 403 reason recorded |
| Traceability table | Point "recommends next ones" and "retrieval quality measured" at real code |

---

## 10. Decisions introduced

| ID | Decision |
|---|---|
| **D43** | Eval ground truth is `(source_type, source_id)` — the unit retrieval returns — not experiment ids and not chunk ids |
| **D44** | Eval queries are blind-drafted from leaderboard, params and metrics only, never from note prose; the rule binds anyone extending the set |
| **D45** | A curated, outcome-diverse subset is approved and the rest rejected, driven by a committed manifest applied through the API |
| **D46** | The tuning grid, the selection metric and the adoption rule are pre-registered; the full grid including losers is committed |
| **D47** | `get_leaderboard` is the agent's third tool, reusing `rank_runs` + `merge_runs` in-process |
| **D48** | MLflow artifacts move to S3-compatible object storage, migrated by rewriting absolute artifact URIs rather than by re-running training |
