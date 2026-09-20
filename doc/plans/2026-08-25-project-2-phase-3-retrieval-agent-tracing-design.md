# Project 2 — Phase 3 Design: Retrieval, Agent, and Tracing

**Status:** approved, 2026-08-25.
**Supersedes:** `doc/plans/2026-08-19-project-2-phase-3-retrieval-agent-tracing-design.md`.
**Parent design:** `doc/project-2-ml-experiment-tracker-design.md` (approved 2026-08-04).
**Phase design it refines:** `doc/plans/2026-08-10-project-2-phases-2-4-design.md`.
**Program plan it schedules against:** `doc/plans/2026-08-05-project-2-overall-implementation-plan.md` §4.

This document covers Phase 3: the embedding pipeline, retrieval over approved
experiment history, the hand-rolled agent that queries it, and the
OpenTelemetry tracing that makes both inspectable. It adds decisions
**D28–D42**, continuing the numbering from Phase 2b's D27.

## Why this document exists rather than an edit to the 08-19 one

Two things landed after 2026-08-19 and neither is a patch to that document's
argument — they change the ground it stands on.

**The run hierarchy (D33–D40, #54, merged 2026-08-24.)** Before it,
`app.experiments` meant one training run. It now means an *investigation*
containing many runs, and the old rows live in `app.runs`. Everywhere the
08-19 design says "experiment" in a retrieval sense, it means what is now a
run. Its §1 is titled "What Phases 2a/2b changed" — a section that cannot
absorb "and then the schema changed underneath all of it" as an amendment.

**The navigation and inline-review refactor.** `/review` is gone. Findings are
approved beside their own text through `FindingsPanel`, mounted on
`DatasetPage` for EDA findings and under the leaderboard on
`ExperimentDetailPage` for diagnostic ones. `NavRail` is now the single
navigation surface, category → entity. The 08-19 design assumed the `/review`
queue existed, and one of its arguments (§5.5's case against embedding on
approval) rests entirely on a bulk-approve loop that no longer exists.

The 08-19 document is left in place, unedited apart from a banner pointing
here, so that pull requests and commit messages citing "the 08-19 design"
still refer to text that says what it said.

---

## 1. What changed since the 08-19 design

**1. The run hierarchy (D33–D40).** Concretely, for this phase:

- `runs.notes` (not `experiments.notes`) is the note corpus.
- Findings with `source_type = "diagnostic"` key on `runs.id` (D37), not on
  the investigation.
- `dataset_id`, `dataset_version`, `target_column` and `task_type` live on the
  **parent**, so a filter on any of them resolves through `app.experiments`
  and then down to its runs (§6.1).
- The agent's tools are named `search_runs` / `get_run_detail` (**D41**) and
  its route is `POST /agent/chat` (**D42**). The 08-19 document assigned the
  number `D41` to both of those decisions; they are split here.

**2. The navigation and inline-review refactor.** `/review` removed;
`NavRail`, `FindingsPanel` and `DatasetPage` added; `GET /findings` gained a
`source_id` filter; `GET /models` added so the run form never restates
`MODEL_REGISTRY`. §5.5 and §8 below are rewritten around this rather than
patched.

**3. The corpus is still empty, and more so than the 08-19 doc recorded.**
Measured against the dev database on 2026-08-25:

| | count |
|---|---|
| `app.runs` | 33 — **all `notes_status = 'draft'`**, all with non-empty note text |
| `app.findings` | 6 — `eda` 1 approved / 2 draft, `diagnostic` 1 approved / 2 draft |
| `app.experiment_note_chunks` | **0** |
| `app.experiments` | 2 |
| `app.datasets` | 3 |

The 08-19 document recorded 5 findings with 2 approved. The approved-note
count is unchanged at zero.

**4. Deliverable 3.0 is still real work.** Verified rather than assumed:
`train_run` (`backend/app/routes/experiments.py:155`) calls
`training.fit_and_score`, which returns holdout metrics only. `cv_<metric>`
and `cv_std` are written by `tune_run` alone (`:255`, `:257`, `:318`, `:320`).
`app/ranking.py` already reads `cv_std` (`:52`, `:63`, `:75`) and receives
`None` for every trained run.

**5. Chunk-size inputs, carried forward.** Mean run-note length is 693
characters; mean finding length is 2,704–4,022 characters depending on type.
These set D29's threshold and correct the Phases 2–4 design's prediction that
`chunk_index = 0` "will dominate in practice" — true for notes, false for
findings.

**6. One incidental finding, recorded so it is not later read as a bug.** The
tracking store holds **35** runs against 33 rows in `app.runs`: two MLflow runs
have no app row, because `train_run` calls `log_run` before inserting the
`Run`. Retrieval drives from `app.runs`, which is where notes live, so orphans
are invisible to it and need no handling.

---

## 2. Deliverables

| # | Deliverable | Depends on |
|---|---|---|
| 3.0 | `POST /experiments/{id}/train` logs `cv_<metric>` and `cv_std`, as `/tune` already does; then launch fresh persistence-baseline runs through the fixed route so each investigation has a banded baseline | — |
| 3.1 | `app/tracing.py` — OTel span helpers, OTLP exporter, **off by default** | — |
| 3.2 | Retrofit spans into `app/loop.py` | 3.1 |
| 3.3 | `app/embeddings.py` + `scripts/backfill_embeddings.py` + `make embed` | — |
| 3.4 | `app/retrieval.py` — D15's two-stage pipeline | 3.3 |
| 3.5 | `app/agent.py` — hand-rolled tool loop (D7), two tools | 3.0, 3.2, 3.4 |
| 3.6 | `POST /agent/chat` + `AskPage` + the **Agent** nav category | 3.5 |
| 3.7 | D16's `backend-postgres` CI job | 3.4 |

Two orderings are load-bearing rather than arbitrary. **3.2 lands before 3.5**,
because retrofitting spans into `loop.py` proves the exporter against shipped,
well-understood code — debugging the exporter and the agent at the same time is
how a tracing layer ends up permanently disabled. And **3.0 gates 3.5** rather
than 3.4: `get_run_detail` returns each metric with its `cv_std`, and if
`/train` still logs none, the agent's only quantitative guard against
over-confident ranking is `null` for every trained run.

3.0's second half is narrower than it reads. Re-launching **only the persistence
baseline** is deliberate — and it is a new run through the fixed `/train`, not
a rewrite of the three existing MLflow runs, which stay as they are: it is the anchor D38's leaderboard exists to provide,
and it is a small number of runs. The other historical runs keep their missing
`cv_std` — re-running history is out of scope, which is why `cv_std` stays
nullable all the way out through the tool result (§7.3).

**Out of scope, deferred to Phase 4:** the curated retrieval eval set and
`make eval` (4.2), polished per-step trace rendering, and any deployment work.

### Preconditions

Neither blocks the code from running; both block it from being meaningful.

- **≥20 approved run notes before 3.3 is executed.** This is deliverable 2.7's
  exit criterion as amended on 2026-08-11 — **currently unmet at 0 of 33**,
  though all 33 carry real generated text, so this is reviewing work rather
  than missing machinery. Notes are approved one run at a time through
  `ExperimentDetailPage`'s review dialog; the standalone `/review` queue that
  used to batch this was removed in the navigation refactor, and per **D28**
  that is not a thing to work around.
- **`VOYAGE_API_KEY` present in `.env`.** Never in CI. It is needed by more
  than the backfill: every `search_runs` call embeds its query, so the agent
  route needs it at request time too, and so does Phase 4's `make eval`.

---

## 3. Decisions

### D28 — The approval gate holds; the corpus is a precondition, not a workaround.

D20 stands unamended: only `approved` text is embedded. Phase 3 does **not**
relax it to draft-inclusive indexing, and does not add a "draft" tier to
retrieval.

The tempting alternative — embed drafts, tag them, filter or down-rank at query
time — unblocks immediately and costs nothing visible. It is rejected because
Phase 4's harness treats approved rows as known-relevant ground truth. Draft
text in the index makes precision@k a measurement of unreviewed model output
against itself, and the resulting numbers look entirely normal. The Phases 2–4
design already flagged this as the failure that is "meaningless while looking
fine."

The cost is honest and stated: **Phase 3 cannot demonstrate anything until the
33 draft run notes are reviewed.** That is scheduling work, not engineering
work, and it belongs in front of deliverable 3.3 rather than hidden inside it.

### D29 — Chunking: size threshold with sentence-boundary breaks, ~1000 characters.

A plain splitter, as §4 of the Phases 2–4 design specified — no recursive
splitter, no token-aware packing, no overlap.

The sizing is set by §1 fact 5 rather than by the prediction it corrects. At
~1000 characters a run note (mean 693) stays a single chunk, and a finding
(mean 2,704–4,022) splits into three or four at sentence boundaries. That is
the right granularity: a finding is a multi-topic document — a distribution
observation, a correlation observation, a missingness observation — and
retrieving the whole thing for a question about one of them buries the match.

**No overlap between chunks.** Overlap exists to stop a sentence spanning a
boundary from being unretrievable; breaking on sentence boundaries already
guarantees that. Adding overlap here would duplicate text in the index and
inflate Phase 4's recall by counting the same passage twice.

### D30 — D21's fourth content type is retired.

The vector index holds exactly three content types, all human-approved:

| Content | `source_type` | Keyed by | Gate |
|---|---|---|---|
| Run notes | `note` | `runs.id` | `runs.notes_status = 'approved'` |
| EDA findings | `eda` | `datasets.id` | `findings.status = 'approved'` |
| Diagnostic interpretations | `diagnostic` | `runs.id` | `findings.status = 'approved'` |

All three keys point at the row that actually holds the text. Notes live on
`app.runs`, and D37 moved diagnostic findings onto `runs.id` as well — a
diagnostic is scored against one trained run, not against the investigation it
belongs to. Neither is keyed by `experiments.id`: an investigation has many
runs, so an `experiments.id` would not identify which run's note was
retrieved. `app/findings.py` enforces this at write time (`Dataset` for `eda`,
`Run` for `diagnostic`), so a chunk keyed the old way fails validation rather
than dangling.

D21's fourth type — static, global "research-question candidates (the five
README entries)" — is dropped, for three reasons:

1. **The source does not exist.** No README in this repo carries such a list.
   The closest thing is **three** sub-questions in the parent design §2, not
   five, and they are in a design document rather than a README.
2. **They describe a modelling task the project no longer runs.** All three
   concern component *prices*. Phase 2a's prepared panel is
   `revenue_nowcast.csv` with target `revenue_next_usd` — semiconductor
   revenue nowcasting. Embedding questions about a different problem would
   return confident, irrelevant hits.
3. **It would force a migration for nothing.** `source_id` shipped `NOT NULL`,
   so a global chunk needs a schema change against a table that is currently
   empty. Cheap, but not free, and bought with no content.

Rejected alternative: rewriting the questions for revenue nowcasting and
indexing those. It is defensible, but it puts *authored* text in an index whose
entire value proposition is that everything in it was observed and reviewed —
and Phase 4 could not score retrieval against it, because no run is
"known-relevant" to a question nobody ran.

**Consequence:** no migration in Phase 3. `source_id` stays `NOT NULL`.

**Correction to the 08-19 document**, which concluded here that "the model
docstring's three types are already correct." The three *types* are; the prose
around them is not. `backend/app/models.py:250–257` still describes the chunk
table as "read by the agent's `search_experiments` tool" and keys notes to
"`experiments.notes`" — both pre-D33 wording. Fixed in the doc-sync task
(§14).

### D31 — Retrieval is its own module, not part of the agent.

The Phases 2–4 design §4 assigns `search_runs` and `get_run_detail` to
`app/agent.py`. This design splits them into `app/retrieval.py`.

Left as written, `agent.py` would import `anthropic`, `voyageai`
(transitively), pgvector SQL, and the MLflow seam in one file. That is
precisely the condition §3.1 of the parent design cites when it split
`training.py` from `experiment_log.py`: "a module touching sklearn, MLflow, and
the DB at once cannot be tested without all three."

The concrete payoff is Phase 4's. **The eval harness imports
`retrieval.search_runs` and scores precision@k, recall@k, and MRR with no
Anthropic mock at all.** With retrieval inside `agent.py`, every eval query
would drag the LLM loop along — slower, non-deterministic, and measuring two
things at once when the number is supposed to be about retrieval.

### D32 — The agent gets two thin tools; reasoning stays in the model.

`search_runs` and `get_run_detail` — the two tools the program plan specifies,
under the names D41 corrects them to. Claude does the comparing and the "what
should I try next" reasoning in prose from what it retrieved.

**Amendment:** `get_run_detail` returns every metric **with its
cross-validation standard deviation**. Per D12's sizing the test split is ~30
rows, so two models routinely differ on RMSE while being statistically
indistinguishable. Without `cv_std` in the tool result the agent will name a
winner whose margin sits inside the fold spread, and nothing about that answer
will look wrong — which is the same failure D18's 422 and the parent design §3.6's `cv_std`
reporting were built to prevent, arriving through a new door.

**This amendment does not work against the history as logged**, which is why
deliverable 3.0 exists. Re-measured against the tracking store on 2026-08-25:

| `model_type` | runs | missing `cv_std` |
|---|---|---|
| ridge | 16 | 0 |
| gradient_boosting | 8 | 0 |
| random_forest | 8 | 0 |
| **persistence** | **3** | **3** |

The 08-19 document recorded persistence as 1 run of 1 missing; the gap has
widened rather than closed. The shape of the problem is unchanged and worse:
`cv_std` is logged in the tuning path only, the persistence baseline is trained
and never tuned (its `search_space` is empty and `/tune` 422s on it, D25), so
**the only runs with no noise band are the reference every other run is
compared against**. An agent asked "did anything actually beat the baseline?"
would get mean±std for all 32 challengers and bare point estimates for the
baseline — exactly the comparison this amendment exists to make safe.

Deliverable 3.0 fixes the cause rather than the instance: `/train` computes and
logs `cv_<metric>` and `cv_std` the way `/tune` does, reusing the pure
`training.cv_objective` that already exists, and the baseline is re-run so the
leaderboard is uniform. Rejected: logging the baseline's spread as a one-off
(leaves `/train` producing bandless runs forever), and leaving the gap for the
prompt to narrate (it makes the project's headline result permanently the
weakest-supported one).

Also rejected: a third `compare_experiments(ids)` aggregator (N calls to
`get_run_detail` already yield the same information; add it later if
comparisons prove clumsy), and a single `answer_question` tool doing retrieval
and synthesis internally (it collapses the agent into a function and leaves
D7's hand-rolled loop with nothing to demonstrate).

### D41 — The agent's tools are named for runs, because that is what they always returned.

`search_runs` and `get_run_detail`, not `search_experiments` and
`get_experiment_detail`. Pre-D33 these were run-shaped already — the older
document's return column read "one merged run" even then — so this is a
correction rather than a change of behaviour, and leaving them
experiment-named would be actively misleading now that an experiment is a
container of many runs and `get_…_detail` would plainly not return one.

One naming collision to keep straight: `app/retrieval.py`'s `search_runs()` is
the two-stage retrieval (vector **and** structured), while
`app/experiment_log.py`'s existing `search_runs()` is the MLflow-only
structured stage that the former calls. They are one layer apart, always
qualified by module at the call site, and renaming either to something
artificial to avoid a qualified-name overlap would cost more clarity than it
buys.

*(The 08-19 document assigned `D41` to this decision and to D42 below. This
document splits them; the numbering here is authoritative.)*

### D42 — The agent route moves off the `/experiments` prefix.

`POST /agent/chat`. Earlier documents place it at `POST /experiments/chat`.
That was unambiguous when `/experiments` was a flat collection, but the
hierarchy gave that prefix a path parameter and two nested actions
(`/experiments/{id}`, `/experiments/{id}/train`, `/experiments/{id}/tune`). A
literal `chat` segment sitting beside `{experiment_id}` is a shadowing hazard
that depends on route declaration order to stay correct — and it is not even
accurate any more, since this endpoint asks across the whole history rather
than within one investigation. It lives in `app/routes/agent.py`, so
`/agent/chat` names it after what it is. No live route is broken: the endpoint
does not exist yet.

---

## 4. Module boundaries

| File | Responsibility | External boundary |
|---|---|---|
| `app/embeddings.py` | `chunk_text()`, `embed_texts()`, `index_source()`, `backfill()` | **the only module importing `voyageai`** |
| `app/retrieval.py` | `search_runs()`, `get_run_detail()` | pgvector SQL + `experiment_log` — **no Anthropic** |
| `app/agent.py` | tool schemas, `validate_tool_call()`, `run_agent()` | **anthropic** |
| `app/tracing.py` | `configure_tracing()`, `span()` | **opentelemetry** |
| `app/routes/agent.py` | `POST /agent/chat` | — |
| `scripts/backfill_embeddings.py` | `make embed` | — |

`routes/experiments.py` is already six routes and ~530 lines, and the agent
route is the only one needing an Anthropic key. It gets its own file.

---

## 5. Embeddings (3.3)

### 5.1 Provider

Voyage `voyage-3.5` with `output_dimension=512` (D14). Matryoshka truncation
means the existing column width (`EMBEDDING_DIM` in `app/models.py`) stands and
**no migration is written**.

The exact model name is the one detail here that should be confirmed against
Voyage's current model list at implementation time rather than taken from this
document. D14's decision is the *provider* and the 512-dimension requirement;
if `voyage-3.5` has been superseded, pick its successor that still supports a
512 output dimension. Anything that does not keeps D14 but costs a migration.

Indexing passes `input_type="document"`; querying passes `input_type="query"`.
These models are trained with that asymmetry and omitting it costs recall — the
kind of defect that surfaces only as mediocre Phase 4 numbers, where it is hard
to attribute.

`VOYAGE_API_KEY` cannot live in CI, so Voyage is mocked in every test — the
same pattern the repo already uses for `ANTHROPIC_API_KEY`.

### 5.2 Chunking

Per D29: split on sentence boundaries, accumulating until ~1000 characters, no
overlap. A pure function of a string — no I/O, no config lookup — so it is
tested directly.

### 5.3 The backfill is a reconciliation, not an append

Each run compares the eligible sources against the chunks already indexed and
handles three cases:

| Case | Action |
|---|---|
| Newly approved | chunk, embed, insert |
| Edited after approval | delete every chunk for that `source_id`, re-chunk, re-insert |
| No longer approved (rejected, or moved back to draft) | **reap** — delete its chunks |

The third case is the one that matters and the one an append-only
implementation passes every other test without. Approval is not a one-way door:
`PATCH /runs/{id}` (`backend/app/routes/runs.py:109–112`) moves `notes_status`
in either direction whenever the caller names it, and `PATCH /findings/{id}`
does the same for findings. If the backfill only ever adds, rejected text stays
retrievable forever, and D28's whole argument — that the index contains only
reviewed text — quietly stops being true while every test stays green.

*(The 08-19 document cited `routes/experiments.py:352` as the unguarded
`notes_status` writer. That code moved to `routes/runs.py` in the hierarchy
split; the line reference above is the current one.)*

One consequence of D30's keying needs stating, because the table's unique
constraint makes it a hard requirement rather than a preference: a key can have
**more than one source row behind it**. `POST /datasets/{id}/eda` may be run
twice on the same dataset, producing two findings that both key to
`("eda", dataset_id)`; the same holds for two diagnostics on one run. The
backfill therefore concatenates every approved finding for a key, oldest first,
separated by a blank line, and chunks the result as one document. That is the
honest reading of the key — all reviewed EDA text about a dataset is that
dataset's reviewed EDA knowledge — and it keeps a retrieved `source_id` a link
to a page rather than to one of several write-ups. Keying chunks on
`findings.id` instead would break §6.3's expansion and §8's id table, and taking
only the newest approved finding would silently discard reviewed text.

Chunk identity is `(source_type, source_id, chunk_index)`, which is already a
unique constraint on the table (`uq_note_chunks_source_chunk_index`), so
re-indexing an edited source is a delete-then-insert rather than an upsert
dance — and a partial failure leaves the source unindexed rather than half
indexed.

### 5.4 Eligibility and the denormalised status column

`experiment_note_chunks.status` is denormalised from the source row so a
similarity search can filter to approved text in one query, without a UNION
back to two tables. Because it is a copy, it can go stale, and §5.3's
reconciliation is what keeps it honest — the reap case exists precisely
because a stale `approved` here is the failure mode with no symptom.

Eligibility is therefore evaluated against the **source** tables on every
backfill run, never against the chunk table's own `status`.

### 5.5 Invocation: `make embed`, not inline on approval

Indexing runs from `scripts/backfill_embeddings.py` behind `make embed`, not
from inside the approval routes.

**The 08-19 document's first argument here no longer applies and is retired.**
It rejected inline embedding partly because D26's bulk-approve path would fire
33 Voyage calls behind a single click. That path does not exist: `/review` was
removed in the navigation refactor, and approval now happens one row at a time
in `FindingsPanel` and in `ExperimentDetailPage`'s review dialog. The
thundering-herd objection is gone.

The decision survives on the remaining reason, which was always the stronger
one: **D17 — the training and review paths never call Voyage or Claude.** An
embedding call inside `PATCH /runs/{id}` means an approval fails when Voyage is
down or the key is unset, turning a local bookkeeping action into something
that needs a vendor to be up. It would also make the two generation endpoints'
carefully bounded LLM exception (D23) stop being an exception.

The cost is honest and is carried as risk 4: the index lags approval, and
nothing detects the gap.

---

## 6. Retrieval (3.4) — D15 made concrete

```
filters ──▶ SQL over app.runs ⋈ app.experiments ─┐
                                                 ├──▶ candidate run_ids
filters ──▶ experiment_log.search_runs()  ───────┘         │
            (reused, not reimplemented)                    ▼
                                        expand to eligible chunk keys (§6.3)
                                                           │
                                                           ▼
query ──▶ embed ──▶ SELECT … ORDER BY embedding <=> :q
                    WHERE status = 'approved' AND (source_type, source_id) IN (…)
                    LIMIT :k * chunk_overfetch
                                                           │
                                                           ▼
                              group by source, score by best chunk, take k (§6.2)
```

### 6.1 Where each filter actually resolves

D15 describes the structured stage as "an intersection of two sources joined on
`mlflow_run_id` — not one SQL query." That is true in general and misleading
for the filters this agent exposes. Checked against `app/models.py` and
`app/experiment_log.py` on 2026-08-25:

| Filter | Resolves in | Why |
|---|---|---|
| `dataset_id` | SQL — `app.experiments.dataset_id` | real column, **on the parent** (D37) |
| `task_type` | SQL — `app.experiments.task_type` | real column, **on the parent** (D37) |
| `model_type` | SQL — `app.runs.model_type` | real column, on the run |
| `experiment_id` | SQL — `app.runs.experiment_id` | `NOT NULL`, indexed, FK CASCADE (`models.py:218`) |
| `status` | **MLflow** — `experiment_log.search_runs(statuses=[…])` | no column of ours; it lives in the run |

The hierarchy split these across two tables: D37 moved `dataset_id` and
`task_type` up to the investigation, while `model_type` stayed on the run,
because what varies *between* runs of one investigation is the model, not the
data. So the structured stage is a join, not a single-table scan — but it is
still one query, and `runs.experiment_id` is indexed and `NOT NULL`, so the
join is cheap and total. The `experiment_id` filter is the one the hierarchy
adds for free, and it is the sharpest of the four: scoping to an investigation
is exactly the "compare like with like" that D38 makes the leaderboard obey.

`experiment_log.search_runs()` takes `metric_filters`, `param_filters`,
`statuses` and `max_results` — and no `dataset_id` or `model_type` — which is
what forces the split above rather than merely permitting it.

So **only `status` costs a round trip**, and a query filtering on any
combination of the others is a single indexed join. This is the same asymmetry
`GET /runs` already lives with, and Phase 3 reuses that resolution rather than
reimplementing it.

Consequence worth planning for: when the tracking store is unreachable, a
`status` filter cannot be honoured. `GET /runs` returns 503 in that case
(`routes/runs.py:74`, `:151`). The agent's tool should instead return a
**structured tool error** — "status filter unavailable, tracking store down" —
so Claude can retry without it and still answer from the other filters. A 503
out of the agent route would fail the whole question over one optional filter.

### 6.2 Chunks are ranked; sources are returned

The vector stage ranks **chunks**, but a caller wants sources. A bare `LIMIT k`
over chunks conflates the two: eight chunks can belong to two runs, and the
agent then sees two results when it asked for eight.

So the query over-fetches chunks (`k * chunk_overfetch`, default **4**), groups
by `(source_type, source_id)`, scores each source by its **single best chunk**,
and returns the top `k` sources with that chunk as the matched snippet.

**Best-chunk, not mean and not sum.** Mean penalises a long finding where one
section matches exactly and three do not — which is the normal case for a
multi-topic EDA write-up. Sum rewards length, which would make findings
outrank notes for reasons unrelated to relevance.

**This reintroduces an over-fetch factor**, and it is worth saying so out loud:
D15 rejected post-filtering partly because "tuning the over-fetch factor is the
fragile part." That objection was about *filters* discarding results after the
vector search, where the discard rate is unbounded and data-dependent. Here the
over-fetch covers only chunk-to-source grouping, whose worst case is bounded by
how many chunks one source has — three or four for a finding, one for a note
(§1 fact 5). A factor of 4 covers it; it is a setting rather than a constant so
Phase 4 can measure rather than guess.

Both acceptance-criteria questions land on this stage. "Which model performed
best on dataset X" is `search_runs` with a `dataset_id` filter; "what
hyperparameter ranges have I tried" is answerable from the structured stage
alone, without the vector half.

### 6.3 Key expansion

The structured stage yields candidate `run_id`s. The vector stage filters on
`(source_type, source_id)` pairs, and the three content types key differently
(D30), so the candidate set is expanded before the vector query:

- each candidate run contributes `("note", run.id)` and `("diagnostic", run.id)`;
- each candidate run's parent contributes `("eda", experiment.dataset_id)`.

The EDA expansion is deliberately one-directional. A dataset's EDA write-up is
relevant to a question about runs over that dataset, so it is pulled in; but a
question filtered to a `model_type` should not be answered by an EDA finding
that predates any model. Since the expansion goes through the parent's
`dataset_id`, an EDA finding only enters the candidate set when at least one
run matching the filters was trained on that dataset.

When no filters are supplied, the expansion is skipped entirely and the vector
query runs against every approved chunk — the common case, and the cheapest.

### 6.4 Degradation

An empty index is not an error. When the vector stage returns nothing —
because nothing is approved yet, or because the filters exclude everything —
`search_runs` returns an empty list and the agent is expected to say so. A
question that retrieves nothing must produce "I have no reviewed history
matching that", never an answer synthesised from the model's own priors, and
`prompts/agent.md` carries that instruction.

If Voyage itself is unavailable, the tool returns a structured error the same
way the tracking-store case does (§6.1); the agent can still answer from
`get_run_detail` on a run it already retrieved, and says what it could not do.

### 6.5 No ANN index

No `ivfflat` or `hnsw` index in Phase 3. At Phase 4's projected corpus scale a
sequential scan over 512-dimension vectors is fast enough, and an approximate
index built and tuned over a nearly-empty table would be tuned against nothing.
It is a one-line addition later, when there is a corpus to measure it against.

### 6.6 Known cost, carried from D15

Two Postgres round trips plus one Voyage call per `search_runs`, and a third
round trip to MLflow when a `status` filter is present. This is stated rather
than optimised: the corpus is small, and the alternative — denormalising
MLflow status into `app.runs` — would put a mirror of someone else's mutable
state in our schema, which D4 exists to prevent.

---

## 7. The agent (3.5)

```python
def run_agent(question: str, session: Session, client: Any | None = None) -> AgentResult
```

Mirrors `loop.py`'s shape, but is a genuine tool-result loop rather than a
render-and-judge loop:

1. Assemble the system prompt from a new `prompts/agent.md`.
2. Call Claude with both tool schemas.
3. `stop_reason != "tool_use"` → done; the answer is the text block.
4. Otherwise: validate each tool call, execute, append a `tool_result`, repeat.
5. Capped at `agent_max_turns` (default **6**).

### 7.1 Validation before execution

Mirroring `validate_tool_call()` (§8 of the parent design): unknown tool name,
missing or mistyped argument, unknown filter field, `k` outside its range. A
bad call becomes a **structured error in the tool result** — Claude sees it and
corrects — rather than an exception or a 500. Raw model output never reaches
the executor. This is the same discipline the chart tools have had since
Project 1, and the same mechanism §6.1's tracking-store-down case and §6.4's
Voyage-down case reuse.

### 7.2 Hitting the cap forces an answer

On the final turn the loop makes one more call **with the tools removed**,
obliging Claude to answer in prose from what it already retrieved. Without
this, a loop that stalls in tool calls returns an empty answer, which reads to
a user as a bug rather than as a limit.

**That call is extra — it does not count against `agent_max_turns`.** The cap
bounds tool-using turns; the closing call executes no tools and cannot extend
the loop. Counting it would mean `agent_max_turns = 6` silently allows only
five turns of work, and the off-by-one would be invisible in the trace.

### 7.3 Tools

| Tool | Arguments | Returns |
|---|---|---|
| `search_runs` | `query`; optional `model_type`, `dataset_id`, `task_type`, `experiment_id`, `status`, `k` | ranked runs with their matched note snippets |
| `get_run_detail` | `run_id` | one merged run — params, metrics **each with `cv_std`**, notes, and its parent experiment's `name` and `objective` |

`get_run_detail` additionally returns the parent's `name` and `objective`. A
run in isolation no longer says what question it was trying to answer — D34
moved that to the investigation — and an agent explaining *why* a run was
performed needs the objective its author wrote.

`search_runs` carries an `experiment_id` filter for the same reason the
structured stage does: "how did the models in *this* investigation compare" is
the question D38's leaderboard answers in the UI, and the agent should be able
to ask it too.

`cv_std` is **nullable in the return shape even after deliverable 3.0**,
because a run logged before 3.0 has none and re-running history is out of
scope. The tool returns `null` rather than omitting the key, and
`prompts/agent.md` instructs the agent to say a comparison is unquantified
rather than to treat a missing spread as a tight one.

---

## 8. API and UI (3.6)

`POST /agent/chat` (D42).

```
Request:  { "question": "..." }
Response: { "answer": "...",
            "retrieved": [ { "source_type": "note" | "eda" | "diagnostic",
                             "source_id":     "...",
                             "run_id":        "..." | null,
                             "experiment_id": "..." | null,
                             "dataset_id":    "..." | null,
                             "snippet": "...", "score": 0.0 } ],
            "trace": { "steps": [...] },
            "tokens_in": …, "tokens_out": …, "cost_usd": …, "latency_ms": … }
```

**The field is `retrieved`, not `retrieved_experiments`.** The program plan and
the Phases 2–4 design both name it `retrieved_experiments`, written before D21
gave the index three content types keyed two different ways. An `eda` chunk's
`source_id` is a `datasets.id`; there is no experiment to put in an
experiment-shaped slot, and forcing one — say, by expanding to every experiment
trained on that dataset — invents relevance the retrieval never asserted.

So each hit carries its own `source_type` and its id fields, populated per type:

| `source_type` | `source_id` is | `run_id` | `experiment_id` | `dataset_id` |
|---|---|---|---|---|
| `note` | `runs.id` | set | set (the run's parent) | null |
| `diagnostic` | `runs.id` | set | set (the run's parent) | null |
| `eda` | `datasets.id` | null | null | set |

`run_id` is the id the citation is *about*; `experiment_id` is its parent,
carried alongside so the UI can link a cited note to the investigation it came
from without a second request. Both come from the join the structured stage
already performs, so neither costs a query. Before D33 there was one id here
and it was called `experiment_id` — the field would have kept its name while
the thing it identified silently became a different table, which is the drift
this revision exists to remove.

This matters beyond the response shape. **Phase 4's eval set maps queries to
known-relevant *runs***, so it must decide what an EDA hit counts as. The
honest options are to score EDA hits separately, or to exclude `eda` from the
ranked set for eval purposes and measure it on its own. Phase 4 picks one; this
design's job is to make sure the data needed for either is present in the
response rather than flattened away here.

**Single-shot and stateless.** No session id, no conversation table. Every
acceptance-criteria question is a single question, and Phase 4's harness scores
retrieval per query — which assumes exactly this shape. The UI keeps a
transcript client-side for display only.

Rejected: client-supplied history (muddies the trace and the eval story for
follow-ups nothing requires) and persisted conversations mirroring `/chats` (a
schema change and a route surface no acceptance criterion asks for).

**The system prompt is never exposed** — not returned, not stored, no UI
toggle. The same constraint the loop trace carries, for the same reason: it can
leak guardrail language, so it never leaves the backend.

**Trace shape**, in the spirit of `PassTrace`: one entry per step, each
`{type: "llm" | "tool", model?, tokens_in?, tokens_out?, latency_ms,
tool_name?, tool_args?, result_summary?, error?}`.

### 8.1 Frontend

`AskPage` at `/ask`: a question input, the answer prose, retrieved-source
cards, and a collapsed `<details>` trace. `api.ts` gains `askAgent`.

**`NavRail` gains a third top-level category, `Agent`, holding `Ask`**, beside
`Data` and `Machine learning`. It is not filed under either existing category
because it belongs to neither: the agent retrieves EDA findings keyed to
datasets *and* notes and diagnostics keyed to runs. A third category also gives
Phase 4's polish somewhere to land without restructuring the rail again. The
group is collapsible and persisted through the same `wp-rail-collapsed` key as
the other two.

```
DATA                        MACHINE LEARNING            AGENT
  + New upload                ▾ Experiments      2        ▸ Ask
  ▾ Datasets           3          All experiments
      revenue_nowcast.csv         nowcast
      video-card.csv              gpu-price
      cpu.csv
```

**Every `source_type` now has a page that renders the text it was cut from**,
which the 08-19 design could not specify because those pages did not exist. An
`eda` hit deep-links to `/datasets/{dataset_id}`, where `FindingsPanel` shows
the finding; a `note` or `diagnostic` hit links to
`/experiments/{experiment_id}`, where the leaderboard row, its review dialog,
and its diagnostic findings panel live. A citation the reader cannot open is a
citation they have to take on faith, and the navigation refactor removed the
reason to be vague here.

The page is deliberately thin — Phase 4 (4.1) owns polish and full per-step
trace rendering. It exists in **this** phase because Phase 2b shipped
`runEda`/`runDiagnostics` as dead code behind no UI at all, so the whole phase
was curl-only until a whole-branch review caught it. Building the entry point
with the feature is cheaper than discovering it is missing.

---

## 9. Tracing (3.1, 3.2)

`configure_tracing()` is called from `create_app()` and is a **no-op when
`otel_enabled = False`**, which is the default. `make test` needs no Jaeger and
CI is unaffected.

Export is OTLP over HTTP to `otel_exporter_otlp_endpoint` (default
`http://localhost:4318`). The compose file already runs Jaeger with those ports
and its UI on :16686 — instrumented by nothing, which is what this deliverable
fixes.

**Span attributes carry ids, counts, and durations — never payloads.** No
embedding vectors (they are 512 floats), no note text.

**3.2 lands before 3.5.** Retrofitting spans into `loop.py` — one per analyst
call, one per judge call, one per render — proves the helpers against shipped,
well-understood code. Debugging the exporter and the agent at the same time is
how a tracing layer ends up permanently disabled.

Agent instrumentation: one root span per request, children per Claude call, per
tool call, and per retrieval (with `k`, candidate count, and hit count as
attributes).

---

## 10. Configuration

New `Settings` fields, all defaulted so CI continues to need no secrets:

| Field | Default | Note |
|---|---|---|
| `voyage_api_key` | `""` | never hardcoded; `.env` only |
| `voyage_model` | `"voyage-3.5"` | 512-dim output via Matryoshka (D14) |
| `retrieval_top_k` | `8` | default `k`, counted in **sources** (§6.2) |
| `chunk_overfetch` | `4` | chunks fetched per source slot before grouping (§6.2) |
| `agent_max_turns` | `6` | D7's cap |
| `otel_enabled` | `False` | tracing off unless asked for |
| `otel_exporter_otlp_endpoint` | `"http://localhost:4318"` | Jaeger's OTLP/HTTP port |

New dependencies: `voyageai`, `opentelemetry-sdk`,
`opentelemetry-exporter-otlp-proto-http`. New `.env.example` entries:
`VOYAGE_API_KEY`, `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`.

**`VOYAGE_API_KEY` is needed by more than the backfill.** Every `search_runs`
call embeds its query, so it is required by the agent route at request time and
by Phase 4's `make eval`. D31's payoff is that the eval harness needs no
*Anthropic* mock — it still makes one real Voyage call per query, and
`make eval` joins `make embed` and `/agent/chat` on the list of things that do
not run without the key. `make test` and CI remain keyless because Voyage is
mocked there.

Cost note: the embed call is **per tool call, not per request**. With
`agent_max_turns = 6` a single question can embed up to five queries.
Negligible at this size, but it is the reason the cap is a setting.

---

## 11. Testing and CI (3.7)

CI has two jobs today, `backend` and `frontend`. 3.7 adds D16's third,
`backend-postgres`, with a `pgvector/pgvector:pg16` service container running
`pytest -m postgres`. The `postgres` marker is registered in `pyproject.toml`.
`make check` and local `make test` stay on SQLite and are untouched — the
zero-setup default survives.

| Module | Approach |
|---|---|
| `embeddings.py` | Voyage mocked; `chunk_text()` tested as a pure function; **all three reconciliation cases** covered — newly approved, edited-after-approval, and un-approved-after-indexing (§5.3) |
| `retrieval.py` | key expansion and source grouping on SQLite against a fake vector stage; the real `<=>` query under `@pytest.mark.postgres` |
| `agent.py` | Anthropic mocked; validation cases exhaustive, including unknown tool, bad args, cap-reached, and the tracking-store-down structured error (§6.1) |
| `tracing.py` | asserts no-op when disabled; in-memory span exporter asserts spans when enabled |
| `routes/agent.py` | `run_agent` stubbed, as `routes/chats.py` stubs `run_loop` |

**Vector fixtures are hand-constructed, never random.** Voyage is mocked, so
embeddings in tests are fabricated. A ranking assertion built on random
512-vectors asserts nothing — it passes or fails on the seed. The Postgres
fixtures use deliberately-ordered vectors (e.g. unit vectors at known angles
from the query) so an assertion about *which* chunk ranks first is an assertion
about the SQL, which is the only part of that path worth testing here.
Embedding *quality* is Phase 4's measurement, against the real provider.

The un-approved-after-indexing case deserves naming as a test rather than
leaving to the row above: index an approved note, `PATCH` it to `rejected`,
re-run the backfill, and assert the chunks are **gone**. That is the assertion
D28 rests on, and it is the one an append-only implementation passes every
other test without.

Two things this phase must not do, both learned the expensive way in Phase 2b:

- **Do not test the vector path only on SQLite.** `<=>` does not exist there. A
  test that passes on SQLite and was never run against Postgres is the shape of
  the skops bug — green unit tests, 500 against a real store.
- **Do not let `make check` be the only gate.** Verified again on 2026-08-25:
  `lint`, `format-check` and `type-check` all target `backend` only, so
  `scripts/` — where `backfill_embeddings.py` lands — is unlinted, unformatted
  and untyped.

---

## 12. Risks

1. **The corpus gate is the real risk.** 0 of 33 run notes are approved. Every
   module below is correct and empty until that is worked. Named as a
   precondition in §2 rather than discovered during 3.3.
2. **pgvector on Render's free tier is still unverified.** Carried since the
   Phases 2–4 design §7.1, which said to "check before Phase 4 starts, not
   during it." Phase 3 is when it becomes load-bearing.
3. **`make check` does not lint `scripts/`**, where the backfill script lands.
   Carried from Phase 2b's follow-ups.
4. **The index lags approval** — a window between an approval decision and the
   next `make embed` during which newly approved text is missing and newly
   rejected text is still being served. §5.3's reconciliation closes both on
   the next run; **nothing detects the gap in between**, and the rejected-text
   half is the worse direction. Mitigations available if it proves annoying,
   neither in scope here: run `make embed` on a timer, or surface an "N sources
   pending indexing" count beside the approve action so the lag is at least
   visible.
5. **Thin statistical power meets a confident narrator.** The agent will be
   asked to rank models whose differences sit inside the fold spread — and the
   baseline every challenger is measured against is now **3 runs with no band
   at all**, up from 1 when the 08-19 design was written. Mitigated by
   deliverable 3.0, by `cv_std` in every tool result, and by an explicit
   instruction in `prompts/agent.md`; not eliminated. Phase 4's evals measure
   retrieval, not this.

---

## 13. Traceability

| Program-overview §3.2 criterion | Lands in |
|---|---|
| Agent retrieves relevant experiments and recommends next ones | 3.4, 3.5, 3.6 — see below |
| Agent traces inspectable | 3.1, 3.2, 3.5 |
| Ask "which model performed best" / "what ranges have I tried" | 3.4 (§6.2 covers both ends) |
| CI passes on every PR | 3.7 extends `.github/workflows/ci.yml` |
| Retrieval quality measured | **Phase 4** (4.2) — out of scope here |

**On "recommends next ones", which the table above asserts rather than
argues.** D30 removed the static research-question chunks, so nothing in the
index is a suggestion. The recommendation is grounded instead in what the
history shows: `search_runs` surfaces the notes for prior runs,
`get_run_detail` returns each run's params, and a study's tried values are
therefore visible as data. "You have swept `alpha` over 0.01–10 on ridge and
the best sits at the low edge, so extend downward" is a claim about retrieved
history, not about prior knowledge.

Two honest limits. The agent can only recommend within the `MODEL_REGISTRY`
that exists, and — per risk 5 — a recommendation resting on differences inside
the fold spread is a guess wearing a number. `prompts/agent.md` must require
that a recommendation cite the runs it came from, so a reviewer can check it
against the same leaderboard the agent read.

---

## 14. Amendments to earlier documents

To be applied during Phase 3's doc-sync task:

- **`doc/plans/2026-08-19-project-2-phase-3-retrieval-agent-tracing-design.md`**
  is superseded by this document. A banner at its head points here; the rest of
  it is left unedited so existing references still resolve to the text they
  cited.
- **D21** — the fourth content type (`research_question`) is retired by
  **D30**. The index holds three types.
- **Phases 2–4 design §4** — `search_runs` and `get_run_detail` move from
  `agent.py` to a new `app/retrieval.py` per **D31**.
- **Phases 2–4 design §4** — the prediction that `chunk_index = 0` "will
  dominate in practice" is corrected by §1 fact 5; it holds for notes and is
  wrong for findings.
- **Overall implementation plan §4** — deliverable 3.1 ("Resolve D6") is not
  work; D6 was resolved by D15 on 2026-08-10. Deliverables are renumbered, and
  a new 3.0 is inserted for the `cv_std` gap in `/train` (D32).
- **Overall implementation plan §4 and Phases 2–4 design §4** — the agent-chat
  response field `retrieved_experiments` becomes `retrieved`, with a
  `source_type` discriminator. Both documents predate D21's three content
  types (§8).
- **Both documents, throughout** — the tools they call `search_experiments` and
  `get_experiment_detail`, and the route they place at
  `POST /experiments/chat`, are renamed by **D41** and **D42** to
  `search_runs`, `get_run_detail`, and `POST /agent/chat`. They were written
  before the run hierarchy (D33–D40) gave "experiment" its current meaning.
- **Overall implementation plan §7.4** — "Branch protection on `main` is still
  unset" is **not an outstanding action item**. `gh api
  repos/:owner/:repo/branches/main/protection` returns 403, "Upgrade to GitHub
  Pro or make this repository public." It is unavailable on this account tier
  and has been miscarried as a to-do since Phase 1.
- **`backend/app/models.py:250–257`** — `ExperimentNoteChunk`'s docstring still
  says the table is "read by the agent's `search_experiments` tool" and keys
  note text to "`experiments.notes`". Both are pre-D33 wording; correct them to
  `retrieval.search_runs` and `runs.notes`.
- **`CLAUDE.md`** — code layout gains the five new modules
  (`embeddings.py`, `retrieval.py`, `agent.py`, `tracing.py`,
  `routes/agent.py`); the design-decisions section gains **D28–D42**.
