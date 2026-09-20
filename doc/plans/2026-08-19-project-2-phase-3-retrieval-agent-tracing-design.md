# Project 2 — Phase 3 Design: Retrieval, Agent, and Tracing

> **SUPERSEDED 2026-08-25 by
> [`2026-08-25-project-2-phase-3-retrieval-agent-tracing-design.md`](2026-08-25-project-2-phase-3-retrieval-agent-tracing-design.md).**
> Two things landed after this document was written that change its ground
> rather than its details: the run hierarchy (D33–D40, issue #54) redefined
> "experiment", and the navigation refactor removed the `/review` queue that
> §5.5 and §8 assume exists. The replacement re-derives the design from the
> code and databases as they now are, splits this document's two conflicting
> `D41`s into **D41** (tool naming) and **D42** (route prefix), and adds
> deliverable 3.0. This file is left unedited below this banner so existing
> references resolve to the text they cited.

**Status:** Approved (brainstorm), 2026-08-19. **Superseded — see banner above.**
**Parent design:** `doc/project-2-ml-experiment-tracker-design.md` (approved 2026-08-04).
**Amended by:** `doc/plans/2026-08-10-project-2-phases-2-4-design.md` (D12–D21).
**Program plan:** `doc/plans/2026-08-05-project-2-overall-implementation-plan.md` §4.
**Preceding phases:** 2a (`…phase-2-training-mlflow-optuna.md`), 2b (`…phase-2b-eda-diagnostics.md`) — both complete and merged.

This document specifies Phase 3 at the level the Phases 2–4 design deliberately
left generic. That document said Phase 3's detail "depends on artefacts that do
not exist yet (real experiment notes, real retrieval failures), and a plan
written against guesses is worse than one written on time." Those artefacts now
exist — 33 logged runs, 5 findings, a persistence baseline nothing beat —
and §1 below records what they change.

New decisions are numbered **D28–D32**, continuing from Phase 2b's D27.

> **REVISED 2026-08-24 for the run hierarchy (D33–D40, issue #54).** This design
> was written on 2026-08-19, when `app.experiments` meant *one training run*.
> Issue #54 split that table: `app.runs` is now one training run, and
> `app.experiments` is the **investigation** that contains many runs. Every
> reference below has been re-pointed at the table that now holds the data —
> most importantly the note and diagnostic source keys, which are `runs.id`
> and not `experiments.id`. Where the rename forced a genuine design choice
> rather than a substitution, it is called out inline as **D41**.

---

## 1. What Phases 2a/2b changed

Six facts from the shipped repo that the 2026-08-10 design could not have known.

1. **The corpus is empty and the approval gate is untouched.** `app.runs`
   holds 33 rows, **all `notes_status = 'draft'`**. `app.findings` holds 5 rows,
   of which **2 are approved** (1 `eda`, 1 `diagnostic`). `app.experiment_note_chunks`
   holds **0 rows**. D20 permits only approved text to be embedded, so an index
   built today would contain two items. See D28.

2. **Note and finding lengths are the reverse of what §4 predicted.** That
   section said "these notes are a paragraph… `chunk_index = 0` will dominate in
   practice — the column earns its keep only for the longer hand-written notes."
   Measured: run notes average **693 characters** (one chunk each), while
   findings average **2,704–4,022 characters** and will split into three or four.
   The chunk index earns its keep on *findings*, not on notes. See D29.

3. **`experiment_note_chunks` already carries D21's shape**, shipped in Phase 2b:
   `source_type` + `source_id` + `status` + `chunk_index`, unique on
   `(source_type, source_id, chunk_index)`, no foreign key, and
   `Vector(512).with_variant(JSON(), "sqlite")`. **No migration is required by
   this phase** — but only because of D30 below.

4. **`source_id` shipped as `NOT NULL`**, and the model docstring names three
   source types (`note`, `eda`, `diagnostic`). D21's fourth type —
   "research-question candidates (the five README entries)", global and
   source-less — has no place to live and no source list to draw from. See D30.

5. **`experiment_log.search_runs()` exists and is D15's structured stage**,
   built in Phase 2a exactly so Phase 3 reuses it rather than reaching for the
   MLflow SDK. Its docstring says so. Phase 3 honours that.

6. **`cv_std` is logged by the tuning path only.** 32 of 35 runs carry it;
   the three that do not include **the persistence baseline**, the reference
   every other run is measured against. `/train` logs holdout metrics and
   nothing else (`tune_run()` in `routes/experiments.py` is the only writer). See
   D32 and deliverable 3.0.

7. **The Jaeger container runs but instruments nothing.** `docker-compose.yml`
   exposes it on :16686; `opentelemetry` appears nowhere in `pyproject.toml` or
   `backend/app/`. Both `doc/architecture.md` and `doc/user-manual.md` now say
   so explicitly, because the misleading reading costs an afternoon.

**One correction to the program plan.** `doc/plans/2026-08-05-project-2-overall-implementation-plan.md`
lists deliverable 3.1 as "Resolve D6 — decide how vector hits reconcile with SQL
filters." **D6 was already resolved by D15** (pre-filter, then rank) in the
2026-08-10 design. Deliverable 3.1 is therefore not work; the numbering below
reassigns it.

---

## 2. Deliverables

| # | Deliverable | Depends on |
|---|---|---|
| 3.0 | `/experiments/{id}/train` logs `cv_<metric>` and `cv_std`, as `/tune` already does; re-run the persistence baseline | — |
| 3.1 | `app/tracing.py` — OTel span helpers, OTLP exporter, **off by default** | — |
| 3.2 | Retrofit spans into `app/loop.py` | 3.1 |
| 3.3 | `app/embeddings.py` + `scripts/backfill_embeddings.py` + `make embed` | — |
| 3.4 | `app/retrieval.py` — D15's pipeline | 3.3 |
| 3.5 | `app/agent.py` — hand-rolled tool loop (D7), two tools | 3.0, 3.2, 3.4 |
| 3.6 | `POST /agent/chat` + `AskPage` | 3.5 |
| 3.7 | D16's `backend-postgres` CI job | 3.4 |

**Out of scope, deferred to Phase 4:** the curated retrieval eval set and
`make eval` (4.2), polished per-step trace rendering, and any deployment work.

**Preconditions.** Neither blocks the code from running; both block it from
being meaningful:

- **≥20 approved run notes** before 3.3 is executed. This is deliverable
  2.7's exit criterion as amended on 2026-08-11 — currently unmet at 0 of 33.
  Run notes are approved per run through `ExperimentDetailPage`'s review
  dialog (the standalone `/review` queue was removed in the navigation
  refactor), so this is reviewing work, not missing machinery.
- `VOYAGE_API_KEY` present in `.env`. Never in CI.

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
fine"; D26's opened-rows gate exists for the same reason.

The cost is honest and stated: **Phase 3 cannot demonstrate anything until the
33 draft run notes are reviewed.** That is scheduling work, not engineering work, and it
belongs in front of deliverable 3.3 rather than hidden inside it.

### D29 — Chunking: size threshold with sentence-boundary breaks, ~1000 characters.

A plain splitter, as §4 of the Phases 2–4 design specified — no recursive
splitter, no token-aware packing, no overlap.

The sizing is set by fact 2 above rather than by the prediction it corrects.
At ~1000 characters a run note (mean 693) stays a single chunk, and a
finding (mean 2,704–4,022) splits into three or four at sentence boundaries.
That is the right granularity: a finding is a multi-topic document — a
distribution observation, a correlation observation, a missingness observation —
and retrieving the whole thing for a question about one of them buries the
match.

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
`app.runs` (`runs.notes`, `runs.notes_status`), and D37 moved diagnostic
findings onto `runs.id` as well — a diagnostic is scored against one trained
run, not against the investigation it belongs to. Neither is keyed by
`experiments.id`: an investigation has many runs, so an `experiments.id` would
not identify which run's note was retrieved. `app/findings.py` enforces this at
write time (`Dataset` for `eda`, `Run` for `diagnostic`), so a chunk keyed the
old way fails validation rather than dangling.

D21's fourth type — static, global "research-question candidates (the five
README entries)" — is dropped, for three reasons:

1. **The source does not exist.** No README in this repo carries such a list.
   The closest thing is **three** sub-questions in the parent design §2, not
   five, and they are in a design document rather than a README.
2. **They describe a modelling task the project no longer runs.** All three
   concern component *prices*. Phase 2a's prepared panel is
   `revenue_nowcast.csv` with target `revenue_next_usd` — semiconductor revenue
   nowcasting. Embedding questions about a different problem would return
   confident, irrelevant hits.
3. **It would force a migration for nothing.** `source_id` shipped `NOT NULL`,
   so a global chunk needs a schema change against a table that is currently
   empty. Cheap, but not free, and bought with no content.

Rejected alternative: rewriting the questions for revenue nowcasting and
indexing those. It is defensible, but it puts *authored* text in an index whose
entire value proposition is that everything in it was observed and reviewed —
and Phase 4 could not score retrieval against it, because no experiment is
"known-relevant" to a question nobody ran.

**Consequence:** no migration in Phase 3. `source_id` stays `NOT NULL` and the
model docstring's three types are already correct.

### D31 — Retrieval is its own module, not part of the agent.

The Phases 2–4 design §4 assigns `search_runs` and
`get_run_detail` to `app/agent.py`. This design splits them into
`app/retrieval.py`.

Left as written, `agent.py` would import `anthropic`, `voyageai` (transitively),
pgvector SQL, and the MLflow seam in one file. That is precisely the condition
§3.1 cites when it split `training.py` from `experiment_log.py`: "a module
touching sklearn, MLflow, and the DB at once cannot be tested without all
three."

The concrete payoff is Phase 4's. **The eval harness imports
`retrieval.search_runs` and scores precision@k, recall@k, and MRR with no
Anthropic mock at all.** With retrieval inside `agent.py`, every eval query would
drag the LLM loop along — slower, non-deterministic, and measuring two things
at once when the number is supposed to be about retrieval.

### D32 — The agent gets two thin tools; reasoning stays in the model.

`search_runs` and `get_run_detail` — the two tools the program plan specifies,
under the names D41 corrects them to. Claude does the comparing and the "what
should I try next" reasoning in prose from what it retrieved.

**Amendment:** `get_run_detail` returns every metric **with its
cross-validation standard deviation**. Per D12's sizing the test split is ~30
rows, so two models routinely differ on RMSE while being statistically
indistinguishable. Without `cv_std` in the tool result the agent will name a
winner whose margin sits inside the fold spread, and nothing about that answer
will look wrong — which is the same failure D18's 422 and §3.6's `cv_std`
reporting were built to prevent, arriving through a new door.

**This amendment does not work against the history as logged**, which is why
deliverable 3.0 exists. Measured in the tracking store:

| `model_type` | runs | missing `cv_std` |
|---|---|---|
| ridge | 16 | 0 |
| gradient_boosting | 8 | 0 |
| random_forest | 8 | 0 |
| **persistence** | **1** | **1** |

`cv_std` is logged in the tuning path only (`tune_run()` in
`routes/experiments.py`, which now serves `POST /experiments/{id}/tune`);
`/train` logs holdout metrics and nothing else. The persistence baseline was
trained, not tuned — so **the one run with no noise band is the reference every
other run is compared against**. An agent asked "did anything actually beat the
baseline?" would get mean±std for all 32 challengers and a bare point estimate
for the baseline, which is exactly the comparison this amendment exists to make
safe.

Deliverable 3.0 fixes the cause rather than the instance: `/train` computes and
logs `cv_<metric>` and `cv_std` the way `/tune` does, reusing the pure
`training.cv_objective` that already exists, and the baseline is re-run so the
leaderboard is uniform. Rejected: logging the baseline's spread as a one-off
(leaves `/train` producing bandless runs forever), and leaving the gap for the
prompt to narrate (it makes the project's headline result permanently the
weakest-supported one).

Rejected: a third `compare_experiments(ids)` aggregator (N calls to
`get_run_detail` already yield the same information; add it later if
comparisons prove clumsy), and a single `answer_question` tool doing retrieval
and synthesis internally (it collapses the agent into a function and leaves D7's
hand-rolled loop with nothing to demonstrate).

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

`routes/experiments.py` is already six routes and ~510 lines, and the agent
route is the only one needing an Anthropic key. It gets its own file.

---

## 5. Embeddings (3.3)

### 5.1 Provider

Voyage `voyage-3.5` with `output_dimension=512` (D14). Matryoshka truncation
means the existing column width stands and **no migration is written**.

The exact model name is the one detail here that should be confirmed against
Voyage's current model list at implementation time rather than taken from this
document. D14's decision is the *provider* and the 512-dimension requirement;
if `voyage-3.5` has been superseded, pick its successor that still supports a
512 output dimension. Anything that does not keeps D14 but costs a migration.

Indexing passes `input_type="document"`; querying passes `input_type="query"`.
These models are trained with that asymmetry and omitting it costs recall — the
kind of defect that surfaces only as mediocre Phase 4 numbers, where it is hard
to attribute.

`VOYAGE_API_KEY` cannot live in CI, so Voyage is mocked in every test — the same
pattern the repo already uses for `ANTHROPIC_API_KEY`.

### 5.2 Chunking

Per D29: split on sentence boundaries, accumulating until ~1000 characters, no
overlap. Pure function of a string — no I/O, no config lookup — so it is tested
directly.

### 5.3 The backfill is a reconciliation, not an append

The unique constraint on `(source_type, source_id, chunk_index)` makes a re-run
safe. Safety is not sufficiency: an append-only backfill gets two cases wrong,
and both put text in front of a user that no human currently endorses.

`backfill()` therefore computes the **desired** set — every currently-approved
note and finding — diffs it against what is indexed, and applies three
operations:

| Case | Detected by | Action |
|---|---|---|
| Newly approved | approved source with no chunks | chunk, embed, insert |
| Edited after approval | re-chunked text differs from stored `chunk_text` | delete that source's chunks, re-insert |
| **No longer approved** | indexed `source_id` absent from the approved set | **delete that source's chunks** |

The third row is the one an append-only design misses, and it is not
hypothetical. `routes/experiments.py:352` moves `notes_status` to any value the
caller names, with no transition guard — so `approved → rejected` is a live
path. Without reaping, those chunks persist **carrying
`status = 'approved'`** and keep ranking. Serving rejected text labelled as
approved is worse than serving nothing, and it quietly defeats D28, which is
this phase's central claim.

The second row needs no content-hash column: the stored `chunk_text` is already
the record of what was indexed. Delete-then-insert also handles shrinkage —
text edited from four chunks down to two leaves no orphan at
`chunk_index = 2..3`, which a plain upsert would.

**Deletion is by source, never by row.** Partial repair of a source's chunks is
how an index ends up holding half of one revision and half of another.

### 5.4 Eligibility, and what the `status` column is actually for

Only `runs.notes_status == 'approved'` and `findings.status == 'approved'`
are indexed. The status is **denormalised onto the chunk row** — as the shipped
model's comment explains — so the similarity query filters in one pass rather
than UNIONing back to two tables.

Worth stating plainly, because it looks like redundancy: with §5.3's reaping in
place, every row in the table is approved, so `WHERE status = 'approved'` never
excludes anything. It is kept anyway. It costs nothing on a sequential scan, it
documents the invariant at the point of use, and if reaping ever regresses it
turns a silent correctness failure into a query that simply returns less. That
is the right way round for this particular bug.

### 5.5 Invocation

`make embed` runs `scripts/backfill_embeddings.py`. **No route calls Voyage**,
preserving D17.

Rejected: embedding inline when `PATCH` flips a status to `approved`. It keeps
the index fresh, but D26's bulk-approve path would then fire one Voyage call per
row inside a loop of PATCHes — 33 sequential network calls behind one click,
with a partial-failure mode that leaves some rows indexed and others not. The
same reasoning D17 applied to `/train` and `/tune` applies here unchanged.

Accepted cost: **the index is stale between an approval and the next
`make embed`.** Nothing detects this in between.

---

## 6. Retrieval (3.4) — D15 made concrete

```
filters ──▶ SQL over app.runs ⋈ app.experiments ─┐
                                                 ├──▶ candidate run_ids
filters ──▶ experiment_log.search_runs()  ───────┘         │
            (reused, not reimplemented)                     │
                                                      ▼
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
`mlflow_run_id` — not one SQL query." That is true in general and misleading for
the filters this agent exposes. Checked against `models.py`:

| Filter | Resolves in | Why |
|---|---|---|
| `dataset_id` | SQL — `app.experiments.dataset_id` | real column, **on the parent** (D37) |
| `task_type` | SQL — `app.experiments.task_type` | real column, **on the parent** (D37) |
| `model_type` | SQL — `app.runs.model_type` | real column, on the run |
| `experiment_id` | SQL — `app.runs.experiment_id` | real column, `NOT NULL` (D34) |
| `status` | **MLflow** — `experiment_log.search_runs(statuses=[…])` | no column of ours; it lives in the run |

The hierarchy split these across two tables: D37 moved `dataset_id` and
`task_type` up to the investigation, while `model_type` stayed on the run,
because what varies *between* runs of one investigation is the model, not the
data. So the structured stage is a join, not a single-table scan — but it is
still one query, and `runs.experiment_id` is indexed and `NOT NULL`, so the join
is cheap and total. The new `experiment_id` filter is the one the hierarchy
adds for free, and it is the sharpest of the four: scoping to an investigation
is exactly the "compare like with like" that D38 makes the leaderboard obey.

So **only `status` costs a round trip**, and a query filtering on any
combination of the others is a single indexed join. This is the same
asymmetry `GET /runs` already lives with (`routes/runs.py`),
and Phase 3 reuses that resolution rather than reimplementing it.

Consequence worth planning for: when the tracking store is unreachable, a
`status` filter cannot be honoured. `GET /runs` returns 503 in that case.
The agent's tool should instead return a **structured tool error** — "status
filter unavailable, tracking store down" — so Claude can retry without it and
still answer from the other filters. A 503 out of the agent route would fail the
whole question over one optional filter.

### 6.2 Chunks are ranked; sources are returned

The vector stage ranks **chunks**, but a caller wants experiments. A bare
`LIMIT k` over chunks conflates the two: eight chunks can belong to two
experiments, and the agent then sees two results when it asked for eight.

So the query over-fetches chunks (`k * chunk_overfetch`, default **4**), groups
by `(source_type, source_id)`, scores each source by its **single best chunk**,
and returns the top `k` sources with that chunk as the matched snippet.

**Best-chunk, not mean and not sum.** Mean penalises a long finding where one
section matches exactly and three do not — which is the normal case for a
multi-topic EDA write-up. Sum rewards length, which would make findings
outrank notes for reasons unrelated to relevance.

**This reintroduces an over-fetch factor**, and it is worth saying so out loud:
D15 rejected post-filtering partly because "tuning the over-fetch factor is the
fragile part." That objection was about *filters* discarding results after
ranking, where the discard rate is unbounded and query-dependent. Grouping is
bounded — the worst case is every chunk sharing one source, and chunks-per-source
is 1 for notes and 3–4 for findings (§1 fact 2), so a factor of 4 covers it. The
factor is a setting rather than a constant so it can be raised if Phase 4 shows
truncation.

### 6.3 The key-expansion step D15 does not mention

The structured stage yields **experiment** ids. Chunks are keyed three ways, and
one of them is not an experiment:

- `note` chunks → `source_id` is a `runs.id`
- `diagnostic` chunks → `source_id` is a `runs.id`
- **`eda` chunks → `source_id` is a `datasets.id`**

So the candidate set must expand to include the `dataset_id` of each candidate
run before the vector stage runs. The hierarchy makes this *cheaper* rather than
harder: D37 moved `dataset_id` off the run and onto its investigation, and the
structured stage already joins `app.runs` to `app.experiments` to resolve the
`dataset_id` and `task_type` filters — so the parent row carrying the id is
in hand, and the expansion still costs no extra query.

It also collapses a duplicate: every run in an investigation shares one
`dataset_id`, so N candidate runs expand to far fewer than N dataset ids. The
pre-D33 shape had that id repeated on every run row and no structural guarantee
they agreed.

Omitting it does not error. It makes **every EDA finding unreachable whenever
any filter is applied**, and the symptom reads as "EDA text just doesn't
retrieve well" — a prose-quality problem, which is where nobody will look.

### 6.4 Degradation

As D15 promises, at both ends:

- **No filters** → the pre-filter is skipped, and the query ranks over all
  approved chunks. Pure semantic search.
- **No query** → the vector stage is skipped entirely and the structured result
  is returned as a listing. "What hyperparameter ranges have I tried" is
  answered here, with no embedding call.

### 6.5 No ANN index

A few hundred chunks means a sequential scan with exact distances, in
milliseconds. An HNSW or IVFFlat index would trade correctness for speed the
project does not need — and would make Phase 4's recall numbers a property of
the index's parameters rather than of the embeddings. Revisit above ~50k chunks,
which this project will not reach.

### 6.6 Known cost, carried from D15

A strongly relevant note inside a filtered-out run is invisible. Accepted
in D15; Phase 4's evals are where it shows up if it bites.

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
missing or mistyped argument, unknown filter field, `k` outside its range. A bad
call becomes a **structured error in the tool result** — Claude sees it and
corrects — rather than an exception or a 500. Raw model output never reaches the
executor. This is the same discipline the chart tools have had since Project 1.

### 7.2 Hitting the cap forces an answer

On the final turn the loop makes one more call **with the tools removed**,
obliging Claude to answer in prose from what it already retrieved. Without this,
a loop that stalls in tool calls returns an empty answer, which reads to a user
as a bug rather than as a limit.

**That call is extra — it does not count against `agent_max_turns`.** The cap
bounds tool-using turns; the closing call executes no tools and cannot extend
the loop. Counting it would mean `agent_max_turns = 6` silently allows only five
turns of work, and the off-by-one would be invisible in the trace.

### 7.3 Tools

| Tool | Arguments | Returns |
|---|---|---|
| `search_runs` | `query`; optional `model_type`, `dataset_id`, `task_type`, `experiment_id`, `status`, `k` | ranked runs with their matched note snippets |
| `get_run_detail` | `run_id` | one merged run — params, metrics **each with `cv_std`**, notes, and its parent experiment's name and objective |

**D41 — the tools are named for runs, because that is what they always
returned.** Pre-D33 these were `search_experiments` and
`get_experiment_detail`, and the second one's return column read "one merged
run" even then. The tools were run-shaped from the start; the hierarchy just
supplied the right word. Renaming them is therefore a correction, not a change
of behaviour — and leaving them named for experiments would be actively
misleading now that an experiment is a container of many runs and `get_…_detail`
would plainly not return one.

`get_run_detail` additionally returns the parent's `name` and `objective`. A run
in isolation no longer says what question it was trying to answer — D34 moved
that to the investigation — and an agent explaining *why* a run was performed
needs the objective its author wrote.

`search_runs` gains an `experiment_id` filter for the same reason the structured
stage did: "how did the models in *this* investigation compare" is the question
D38's leaderboard answers in the UI, and the agent should be able to ask it too.

One naming collision to keep straight: `app/retrieval.py`'s `search_runs()` is
the two-stage retrieval (vector **and** structured), while
`app/experiment_log.py`'s existing `search_runs()` is the MLflow-only structured
stage that the former calls. They are one layer apart, always qualified by
module at the call site, and renaming either to something artificial to avoid a
qualified-name overlap would cost more clarity than it buys.

`cv_std` is nullable in the return shape even after deliverable 3.0, because a
run logged before 3.0 has none and re-running history is out of scope. The tool
returns `null` rather than omitting the key, and `prompts/agent.md` instructs
the agent to say a comparison is unquantified rather than to treat a missing
spread as a tight one.

Both acceptance-criteria questions map directly: "which model performed best on
dataset X" is `search_runs` with a `dataset_id` filter; "what
hyperparameter ranges have I tried" is the structured stage alone.

---

## 8. API and UI (3.6)

`POST /agent/chat`

**D41 — the route moves off the `/experiments` prefix.** Earlier documents place
it at `POST /experiments/chat`. That was unambiguous when `/experiments` was a
flat collection, but the hierarchy gave that prefix a path parameter and two
nested actions (`/experiments/{id}`, `/experiments/{id}/train`,
`/experiments/{id}/tune`). A literal `chat` segment sitting beside
`{experiment_id}` is a shadowing hazard that depends on route declaration order
to stay correct — and it is not even accurate any more, since this endpoint
asks across the whole history rather than within one investigation. It lives in
`app/routes/agent.py`, so `/agent/chat` names it after what it is. No live
route is broken by this: the endpoint does not exist yet.

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
already performs, so neither costs a query. Before D33 there was one id here and
it was called `experiment_id` — the field would have kept its name while the
thing it identified silently became a different table, which is the drift this
revision exists to remove.

This matters beyond the response shape. **Phase 4's eval set maps queries to
known-relevant *runs***, so it must decide what an EDA hit counts as.
The honest options are to score EDA hits separately, or to exclude `eda` from
the ranked set for eval purposes and measure it on its own. Phase 4 picks one;
this design's job is to make sure the data needed for either is present in the
response rather than flattened away here.

**Single-shot and stateless.** No session id, no conversation table. Every
acceptance-criteria question is a single question, and Phase 4's harness scores
retrieval per query — which assumes exactly this shape. The UI keeps a
transcript client-side for display only.

Rejected: client-supplied history (muddies the trace and the eval story for
follow-ups nothing requires) and persisted conversations mirroring `/chats` (a
schema change and a route surface no acceptance criterion asks for).

**The system prompt is never exposed** — not returned, not stored, no UI toggle.
The same constraint the loop trace carries, for the same reason: it can leak
guardrail language, so it never leaves the backend.

**Trace shape**, in the spirit of `PassTrace`: one entry per step, each
`{type: "llm" | "tool", model?, tokens_in?, tokens_out?, latency_ms, tool_name?,
tool_args?, result_summary?, error?}`.

**Frontend.** `AskPage` at `/ask`: question input, answer prose,
retrieved-run cards linking into the run, and a collapsed `<details>`
trace. `api.ts` gains `askAgent`; `NavRail` gains the nav entry.

Deliberately thin — Phase 4 (4.1) owns polish and full per-step trace rendering.
It exists in this phase because Phase 2b shipped with `runEda`/`runDiagnostics`
as dead code and `/review` routed but unlinked: the whole phase was curl-only,
and D26's gate was guarding an unreachable page. That was caught by the
whole-branch review and fixed inside the phase. Building the entry point with
the feature is cheaper than discovering it is missing.

---

## 9. Tracing (3.1, 3.2)

`configure_tracing()` is called from `create_app()` and is a **no-op when
`otel_enabled = False`**, which is the default. `make test` needs no Jaeger and
CI is unaffected.

Export is OTLP over HTTP to `otel_exporter_otlp_endpoint`
(default `http://localhost:4318`). The compose file already runs Jaeger with
those ports and its UI on :16686 — instrumented by nothing, which is what this
deliverable fixes.

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

**`VOYAGE_API_KEY` is needed by more than the backfill.** Every
`search_runs` call embeds its query, so it is required by the agent route
at request time and by Phase 4's `make eval`. D31's payoff is that the eval
harness needs no *Anthropic* mock — it still makes one real Voyage call per
query, and `make eval` joins `make embed` and `/agent/chat` on the list of
things that do not run without the key. `make test` and CI remain keyless
because Voyage is mocked there.

Cost note: the embed call is **per tool call, not per request**. With
`agent_max_turns = 6` a single question can embed up to five queries. Negligible
at this size, but it is the reason the cap is a setting.

---

## 11. Testing and CI (3.7)

D16's third job, `backend-postgres`, with a `pgvector/pgvector:pg16` service
container running `pytest -m postgres`. The `postgres` marker is registered in
`pyproject.toml`. `make check` and local `make test` stay on SQLite and are
untouched — the zero-setup default survives.

| Module | Approach |
|---|---|
| `embeddings.py` | Voyage mocked; `chunk_text()` tested as a pure function; **all three reconciliation cases** covered — newly approved, edited-after-approval, and un-approved-after-indexing (§5.3) |
| `retrieval.py` | key expansion and source grouping on SQLite against a fake vector stage; the real `<=>` query under `@pytest.mark.postgres` |
| `agent.py` | Anthropic mocked; validation cases exhaustive, including unknown tool, bad args, and cap-reached |
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
D28 rests on, and it is the one an append-only implementation passes every other
test without.

Two things this phase must not do, both learned the expensive way in Phase 2b:

- **Do not test the vector path only on SQLite.** `<=>` does not exist there. A
  test that passes on SQLite and was never run against Postgres is the shape of
  the skops bug — green unit tests, 500 against a real store.
- **Do not let `make check` be the only gate.** It still does not lint
  `scripts/`, where `backfill_embeddings.py` lands.

---

## 12. Risks

1. **The corpus gate is the real risk.** 0 of 33 run notes are approved.
   Every module below is correct and empty until that is worked. Named as a
   precondition in §2 rather than discovered during 3.3.
2. **pgvector on Render's free tier is still unverified.** Carried since the
   Phases 2–4 design §7.1, which said to "check before Phase 4 starts, not
   during it." Phase 3 is when it becomes load-bearing.
3. **`make check` does not lint `scripts/`**, where the backfill script lands.
   Carried from Phase 2b's follow-ups.
4. **The index lags approval** — a window between an approval decision and the
   next `make embed` during which newly approved text is missing and newly
   rejected text is still being served. §5.3's reconciliation closes both on the
   next run; **nothing detects the gap in between**, and the rejected-text half
   is the worse direction. Mitigations available if it proves annoying, neither
   in scope here: run `make embed` on a timer, or surface an "N sources pending
   indexing" count beside the approve action so the lag is at least visible.
5. **Thin statistical power meets a confident narrator.** The agent will be
   asked to rank models whose differences sit inside the fold spread. Mitigated
   by D32's `cv_std` in every tool result and by an explicit instruction in
   `prompts/agent.md`; not eliminated. Phase 4's evals measure retrieval, not
   this.

---

## 13. Traceability

| Program-overview §3.2 criterion | Lands in |
|---|---|
| Agent retrieves relevant experiments and recommends next ones | 3.4, 3.5, 3.6 — see below |
| Agent traces inspectable | 3.1, 3.2, 3.5 |
| Ask "which model performed best" / "what ranges have I tried" | 3.4 (§6.2 covers both ends) |
| CI passes on every PR | 3.7 extends `.github/workflows/ci.yml` |
| Retrieval quality measured | **Phase 4** (4.2) — out of scope here |

**On "recommends next ones", which the table above asserts rather than argues.**
D30 removed the static research-question chunks, so nothing in the index is a
suggestion. The recommendation is grounded instead in what the history shows:
`search_runs` surfaces the notes for prior runs, `get_run_detail`
returns each run's params, and a study's tried values are therefore visible as
data. "You have swept `alpha` over 0.01–10 on ridge and the best sits at the
low edge, so extend downward" is a claim about retrieved history, not about
prior knowledge.

Two honest limits. The agent can only recommend within the `MODEL_REGISTRY`
that exists, and — per risk 5 — a recommendation resting on differences inside
the fold spread is a guess wearing a number. `prompts/agent.md` must require
that a recommendation cite the runs it came from, so a reviewer can check it
against the same leaderboard the agent read.

---

## 14. Amendments to earlier documents

To be applied during Phase 3's doc-sync task:

- **D21** — the fourth content type (`research_question`) is retired by **D30**.
  The index holds three types.
- **Phases 2–4 design §4** — `search_runs` moves from `agent.py` to a new
  `app/retrieval.py` per **D31**.
- **Phases 2–4 design §4** — the prediction that `chunk_index = 0` "will
  dominate in practice" is corrected by §1 fact 2; it holds for notes and is
  wrong for findings.
- **Overall implementation plan §4** — deliverable 3.1 ("Resolve D6") is not
  work; D6 was resolved by D15 on 2026-08-10. Deliverables are renumbered, and
  a new 3.0 is inserted for the `cv_std` gap in `/train` (D32).
- **Overall implementation plan §4 and Phases 2–4 design §4** — the
  agent-chat response field `retrieved_experiments` becomes
  `retrieved`, with a `source_type` discriminator. Both documents predate D21's
  three content types (§8).
- **Both documents, throughout** — the tools they call `search_experiments` and
  `get_experiment_detail`, and the route they place at `POST /experiments/chat`,
  are renamed by **D41** to `search_runs`, `get_run_detail`, and
  `POST /agent/chat`. They were written before the run hierarchy (D33–D40) gave
  "experiment" its current meaning.
- **Overall implementation plan §7.4** — "Branch protection on `main` is still
  unset" is **not an outstanding action item**. `gh api
  repos/:owner/:repo/branches/main/protection` returns 403, "Upgrade to GitHub
  Pro or make this repository public." It is unavailable on this account tier
  and has been miscarried as a to-do since Phase 1.
- **`CLAUDE.md`** — code layout gains the four new modules; the design-decisions
  section gains D28–D32.
