# Project 2 Phase 4 — Evaluation, Recommendations, and Deploy

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure retrieval quality against a committed golden set, tune it under a pre-registered rule, give the agent the leaderboard numbers it needs to recommend next experiments, and deploy the whole thing with durable model artifacts.

**Architecture:** A new `backend/eval/` package holds pure metric arithmetic, a caching Voyage client shim, a committed golden set and curation manifest, and a runner that drives the *production* retrieval path (`retrieval.search_runs`) rather than a reimplementation. A new `app/leaderboard.py` extracts the ranking that `GET /experiments/{id}/runs` already performs so the agent's third tool and the UI cannot disagree about rank 1. Deploy is two Render services plus managed Postgres, with MLflow artifacts moved to S3-compatible object storage.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Alembic, pytest, pgvector, Voyage AI (`voyage-4`, 512-dim), MLflow 3.x, Optuna, Anthropic Messages API, React/Vite/TypeScript, Render, Cloudflare R2.

**Spec:** `docs/superpowers/specs/2026-08-28-project-2-phase-4-design.md`

## Issue map

Each task has a GitHub issue carrying its rationale. Branch per issue,
`<type>/<slug>`, stacked on the previous task's branch.

| Task | Issue | Task | Issue |
| --- | --- | --- | --- |
| 1 `chunk_max_chars` | #91 | 9 `app/leaderboard.py` | #99 |
| 2 `eval/metrics.py` | #92 | 10 `get_leaderboard` tool | #100 |
| 3 `eval/cache.py` | #93 | 11 prompt recommendation rule | #101 |
| 4 `apply_curation.py` | #94 | 12 Dockerfile + `render.yaml` | #102 |
| 5 apply curation, embed | #95 | 13 R2 + URI rewrite | #103 |
| 6 golden set + `make eval` | #96 | 14 deploy + smoke | #104 |
| 7 baseline run | #97 | 15 document close-out | #105 |
| 8 pre-registered sweep | #98 | | |

Tasks 5, 7, 8 and 14 are **operational** — they run against live Postgres,
Voyage and Render, and their deliverables are measurements and a deployed URL
rather than code. A subagent cannot verify those the way it verifies a suite.

---

## Global Constraints

- **Line length 100.** ruff and black are both configured to it. `make lint` / `make format`.
- **mypy is strict on `backend/app` only.** `backend/eval/` and `scripts/` are not type-checked; still write annotations, but a missing one there will not fail CI.
- **ruff lint selects `["E", "F", "I", "B", "UP"]`.** Import order (`I`) is enforced — run `poetry run ruff check --fix backend` after adding imports.
- **Imports are absolute from `app`** (e.g. `from app.retrieval import search_runs`). `pyproject.toml` sets `pythonpath = ["backend", "scripts"]`, so `backend/eval/` imports as `eval.*`.
- **Backend application code lives in `backend/app/` only; backend tests in `backend/tests/` only.**
- **Tests run on SQLite** via the `client` fixture in `backend/tests/conftest.py` (isolated DB per test, `tmp_path`). Postgres-only tests are marked `@pytest.mark.postgres` and skip without `POSTGRES_TEST_URL`.
- **`make check` = lint + format-check + type-check + test.** It is the CI gate and must stay green and offline: no API keys, no Postgres, no network.
- **`EMBEDDING_DIM = 512`** (`app/models.py`). Voyage free tier is **3 requests/minute**.
- **Span attributes carry ids, counts and durations — never payloads.** No note text, no query text, no vectors. (3.1)
- **`_execute` in `app/agent.py` never raises.** Every tool failure returns a `tool_result` string the model can act on.
- **A missing `cv_std` is `None`, never `0.0`.** (D32)
- **Scripts go through the API**, never straight to the database. (D13)
- **Commit style:** `feat:` / `fix:` / `docs:` / `chore:` / `review:` prefix, lowercase summary. Every commit ends with:
  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```
- **Branch per task**, stacked: each task's branch targets the previous task's branch, as Phase 3 did. Start from `design/phase-4`.
- **Doc sync happens in the PR that causes the change**, not as a cleanup at the end. Task 15 covers only the cross-cutting documents that belong to no single task.

---

## File Structure

**Created:**

| Path | Responsibility |
|---|---|
| `backend/eval/__init__.py` | Package marker; empty |
| `backend/eval/metrics.py` | Pure ranking arithmetic: precision@k, recall@k, reciprocal rank, aggregation. No I/O, no imports from `app`. |
| `backend/eval/cache.py` | `CachingVoyageClient` — a client shim satisfying Voyage's `.embed()` contract, backed by a JSON file on disk |
| `backend/eval/curation.yaml` | `run_id → decision → reason` manifest (D45) |
| `backend/eval/golden_set.yaml` | Queries with labelled relevant `(source_type, source_id)` pairs (D43/D44) |
| `backend/eval/runner.py` | Loads the golden set, drives `retrieval.search_runs`, prints and writes the report |
| `backend/eval/results/` | Committed report and sweep outputs |
| `backend/app/leaderboard.py` | `build_leaderboard()` — ranking extracted from the route so the agent and UI share it |
| `scripts/apply_curation.py` | Applies `curation.yaml` through `PATCH /runs/{id}` |
| `scripts/migrate_artifact_uris.py` | One-shot rewrite of MLflow's absolute artifact URIs after the R2 move |
| `Dockerfile` | Backend web service image |
| `render.yaml` | Two services + managed Postgres |
| `backend/tests/test_eval_metrics.py` | Metric arithmetic, offline |
| `backend/tests/test_eval_cache.py` | Cache hit/miss/key behaviour, offline |
| `backend/tests/test_curation.py` | The applier, through the `client` fixture |
| `backend/tests/test_eval_runner.py` | Runner wiring, with `search_runs` monkeypatched |
| `backend/tests/test_leaderboard.py` | `build_leaderboard` ranking, limit, and not-found |

**Modified:**

| Path | Change |
|---|---|
| `backend/app/config.py` | `chunk_max_chars`, `agent_max_leaderboard_rows` |
| `backend/app/embeddings.py` | `chunk_text` resolves its budget from settings; `DEFAULT_MAX_CHARS` removed |
| `backend/app/agent.py` | Third tool: schema, validation bound, `_execute` branch, renderer |
| `backend/app/routes/experiments.py` | Leaderboard route body moves to `app/leaderboard.py` |
| `prompts/agent.md` | The recommendation rule |
| `Makefile` | `eval` target becomes real |
| `.env.example`, `.gitignore` | New settings; cache file ignored |
| `CLAUDE.md`, `README.md`, `doc/plans/2026-08-10-project-2-phases-2-4-design.md` | Doc sync |

---

## Task 1: Make the chunk budget configurable

Sweeping `chunk_max_chars` (Task 8) needs it reachable from config. Today it is `DEFAULT_MAX_CHARS = 1000`, a module constant in `app/embeddings.py`.

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/embeddings.py:60` (`DEFAULT_MAX_CHARS`), `:86` (`chunk_text`)
- Modify: `.env.example`
- Test: `backend/tests/test_embeddings.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Settings.chunk_max_chars: int` (default `1000`); `chunk_text(text: str, max_chars: int | None = None) -> list[str]` — `None` resolves to `settings.chunk_max_chars` at call time.

**Design note — why resolve inside `chunk_text` rather than at the call sites.** `backfill()` uses `chunk_text` twice: once inside `index_source` to produce chunks, and once in its skip check (`current == chunk_text(source.text)`). Threading a `max_chars` argument to only one of the two would make every source compare unequal forever, re-indexing the whole corpus on every run and burning Voyage quota with no visible symptom. Resolving the default *inside* the function removes that failure mode by construction — there is no call site left to forget.

- [x] **Step 1: Write the failing test**

Append to `backend/tests/test_embeddings.py`:

```python
def test_chunk_text_reads_its_budget_from_settings(monkeypatch):
    """The budget is resolved at call time, so a settings change takes effect
    without any caller passing it. Task 8's sweep depends on this."""
    text = "One. " * 200  # 1000 characters of short sentences
    monkeypatch.setattr(settings, "chunk_max_chars", 100)
    narrow = chunk_text(text)
    monkeypatch.setattr(settings, "chunk_max_chars", 2000)
    wide = chunk_text(text)
    assert len(narrow) > len(wide)
    assert all(len(c) <= 100 for c in narrow)


def test_an_explicit_max_chars_still_wins():
    """Tests and callers that pass a budget are unaffected by the setting."""
    text = "One. " * 200
    assert all(len(c) <= 50 for c in chunk_text(text, max_chars=50))


def test_backfill_reindexes_when_the_chunk_budget_changes(session, fake_voyage):
    """The skip check re-chunks with the CURRENT budget, so a budget change is
    detected as an edit. If this regresses, a swept config silently evaluates
    the previous config's index."""
    _approve_one_finding(session, text="One. " * 200)
    monkeypatch_budget = 1000
    settings.chunk_max_chars = monkeypatch_budget
    first = backfill(session, client=fake_voyage)
    assert first.indexed == 1

    settings.chunk_max_chars = 200
    try:
        second = backfill(session, client=fake_voyage)
    finally:
        settings.chunk_max_chars = monkeypatch_budget
    assert second.reindexed == 1
    assert second.unchanged == 0
```

Add to that file's imports: `from app.config import settings`. Reuse the existing fake-Voyage fixture and approved-source helper in `backend/tests/test_embeddings.py`; if the helper named `_approve_one_finding` above does not exist under that name, use whatever the file already uses to create an approved `Finding` and keep the assertions unchanged.

- [x] **Step 2: Run the tests to verify they fail**

```bash
poetry run pytest backend/tests/test_embeddings.py -k "budget or reindexes" -v
```

Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'chunk_max_chars'`.

- [x] **Step 3: Add the setting**

In `backend/app/config.py`, immediately above the `# Retrieval (3.4)` block:

```python
    # Chunking (D29, 3.3). A configuration value because Phase 4's sweep needs
    # to vary it (D46) — but changing it is NOT a cheap config change: every
    # indexed vector has to be recomputed, so `make embed` must be re-run.
    chunk_max_chars: int = 1000
```

- [x] **Step 4: Resolve the budget inside `chunk_text`**

In `backend/app/embeddings.py`, delete the `DEFAULT_MAX_CHARS = 1000` line and change the signature:

```python
def chunk_text(text: str, max_chars: int | None = None) -> list[str]:
    """Split `text` into chunks of at most `max_chars`, breaking only between
    sentences and always at blank lines.

    The budget is resolved HERE rather than at the call sites. `backfill` calls
    this twice — once to build chunks, once in its skip check — and passing a
    budget to only one of the two would make every source compare unequal
    forever, re-indexing the whole corpus on every run.
    """
    max_chars = max_chars or settings.chunk_max_chars
```

Leave the rest of the body unchanged.

- [x] **Step 5: Run the full embeddings suite**

```bash
poetry run pytest backend/tests/test_embeddings.py -v
```

Expected: PASS, including the pre-existing chunking tests (they pass no `max_chars` and now resolve to the same 1000).

- [x] **Step 6: Document the setting**

Append to `.env.example`, under the Voyage block:

```
# Chunk budget in characters (D29). Changing this invalidates the whole index:
# re-run `make embed` after any change.
CHUNK_MAX_CHARS=1000
```

- [x] **Step 7: Run the gate and commit**

```bash
make check
git add backend/app/config.py backend/app/embeddings.py backend/tests/test_embeddings.py .env.example
git commit -m "$(cat <<'EOF'
feat: make the chunk budget a setting, resolved at call time (4.3)

Phase 4's pre-registered sweep (D46) varies chunk size, which needs it
reachable from config. Resolved inside chunk_text rather than threaded to
its call sites: backfill calls it twice — to build chunks and in its skip
check — and passing a budget to only one would make every source compare
unequal forever, re-indexing the corpus on every run with no symptom
beyond a Voyage bill.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `backend/eval/metrics.py` — the ranking arithmetic

**Files:**
- Create: `backend/eval/__init__.py`, `backend/eval/metrics.py`
- Test: `backend/tests/test_eval_metrics.py`

**Interfaces:**
- Consumes: nothing. This module imports nothing from `app` and touches no I/O — that is what lets it be tested offline inside `make check`.
- Produces:
  - `Source = tuple[str, str]` — `(source_type, source_id)`, the D43 ground-truth unit
  - `precision_at_k(ranked: Sequence[Source], relevant: Collection[Source], k: int) -> float`
  - `recall_at_k(ranked: Sequence[Source], relevant: Collection[Source], k: int) -> float`
  - `reciprocal_rank(ranked: Sequence[Source], relevant: Collection[Source]) -> float`
  - `QueryScore` frozen dataclass: `query_id: str`, `precision: dict[int, float]`, `recall: dict[int, float]`, `rr: float`
  - `score_query(query_id: str, ranked: Sequence[Source], relevant: Collection[Source], ks: Sequence[int]) -> QueryScore`
  - `Aggregate` frozen dataclass: `n: int`, `precision: dict[int, float]`, `recall: dict[int, float]`, `mrr: float`
  - `aggregate(scores: Sequence[QueryScore]) -> Aggregate`
  - `paired_mrr_delta(baseline: Sequence[QueryScore], challenger: Sequence[QueryScore]) -> tuple[float, float]` — returns `(mean_difference, standard_error)`, the D46 adoption rule's inputs

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_eval_metrics.py`:

```python
"""Metric arithmetic (D43). Offline: no API key, no database, no network.

These numbers are hand-computed. A real eval run's numbers have no
independently known correct value, which is exactly why the arithmetic is
pinned here instead of being trusted because a report printed something.
"""

import pytest

from eval.metrics import (
    aggregate,
    paired_mrr_delta,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    score_query,
)

A = ("note", "a")
B = ("note", "b")
C = ("eda", "c")
D = ("diagnostic", "d")


def test_precision_counts_relevant_in_the_top_k():
    # 2 of the first 4 are relevant.
    assert precision_at_k([A, C, B, D], {A, B}, 4) == 0.5


def test_precision_divides_by_k_not_by_the_result_length():
    """A search that returned 2 sources when 8 were asked for was not perfectly
    precise; dividing by len(ranked) would report 1.0 and hide the shortfall."""
    assert precision_at_k([A, B], {A, B}, 8) == pytest.approx(0.25)


def test_recall_divides_by_the_relevant_set():
    assert recall_at_k([A, C], {A, B}, 8) == 0.5


def test_recall_is_one_when_everything_relevant_is_retrieved():
    assert recall_at_k([C, A, D, B], {A, B}, 8) == 1.0


def test_k_larger_than_the_result_set_is_not_an_error():
    assert recall_at_k([A], {A}, 100) == 1.0
    assert precision_at_k([A], {A}, 100) == pytest.approx(0.01)


def test_nothing_relevant_retrieved_scores_zero_everywhere():
    assert precision_at_k([C, D], {A, B}, 8) == 0.0
    assert recall_at_k([C, D], {A, B}, 8) == 0.0
    assert reciprocal_rank([C, D], {A, B}) == 0.0


def test_reciprocal_rank_uses_the_first_relevant_position():
    assert reciprocal_rank([C, A, B], {A, B}) == pytest.approx(1 / 2)
    assert reciprocal_rank([A, C, B], {A, B}) == 1.0


def test_an_empty_relevant_set_is_a_programming_error():
    """A golden-set entry with no labelled sources is unanswerable, and
    silently scoring it 0.0 would drag the mean down for a data-entry bug."""
    with pytest.raises(ValueError):
        reciprocal_rank([A], set())


def test_score_query_reports_every_cutoff():
    score = score_query("q1", [A, C, B], {A, B}, ks=(1, 3))
    assert score.query_id == "q1"
    assert score.precision[1] == 1.0
    assert score.precision[3] == pytest.approx(2 / 3)
    assert score.recall[1] == 0.5
    assert score.recall[3] == 1.0
    assert score.rr == 1.0


def test_aggregate_means_across_queries():
    one = score_query("q1", [A], {A}, ks=(1,))
    two = score_query("q2", [C], {A}, ks=(1,))
    agg = aggregate([one, two])
    assert agg.n == 2
    assert agg.precision[1] == 0.5
    assert agg.mrr == 0.5


def test_aggregate_of_nothing_is_zero_not_a_crash():
    agg = aggregate([])
    assert agg.n == 0
    assert agg.mrr == 0.0
    assert agg.precision == {}


def test_paired_delta_is_computed_per_query_not_between_means():
    """The D46 adoption rule needs the spread of per-query differences. Taking
    the difference of two means throws that spread away and every challenger
    then looks decisive."""
    base = [score_query("q1", [C, A], {A}, ks=(2,)), score_query("q2", [A], {A}, ks=(2,))]
    chal = [score_query("q1", [A, C], {A}, ks=(2,)), score_query("q2", [A], {A}, ks=(2,))]
    mean, stderr = paired_mrr_delta(base, chal)
    # q1 improves 0.5 -> 1.0; q2 is unchanged. Mean 0.25, stdev 0.3535..., n=2.
    assert mean == pytest.approx(0.25)
    assert stderr == pytest.approx(0.25)


def test_paired_delta_requires_matching_query_ids():
    """Comparing two configs over different query sets is not a comparison."""
    base = [score_query("q1", [A], {A}, ks=(1,))]
    chal = [score_query("q2", [A], {A}, ks=(1,))]
    with pytest.raises(ValueError):
        paired_mrr_delta(base, chal)


def test_paired_delta_of_a_single_query_has_no_standard_error():
    """One sample has no spread. Reporting 0.0 would make any difference clear
    the adoption bar automatically."""
    base = [score_query("q1", [C, A], {A}, ks=(2,))]
    chal = [score_query("q1", [A, C], {A}, ks=(2,))]
    mean, stderr = paired_mrr_delta(base, chal)
    assert mean == pytest.approx(0.5)
    assert stderr == float("inf")
```

- [x] **Step 2: Run to verify they fail**

```bash
poetry run pytest backend/tests/test_eval_metrics.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'eval.metrics'`.

- [x] **Step 3: Write the implementation**

Create `backend/eval/__init__.py` (empty file), then `backend/eval/metrics.py`:

```python
"""Retrieval metrics over sources (D43).

The ground-truth unit is `(source_type, source_id)` — the unit
`retrieval.search_runs` returns. Not experiment ids (D33 split experiment from
run, and an `eda` source is keyed to a dataset and has no experiment id at
all), and not chunk ids (`k` counts sources, so a chunk-level metric would
measure something the system does not return).

Pure: no I/O, no database, no imports from `app`. That is what lets it run
inside `make check` with no key and no Postgres, and the arithmetic is the part
a real-API suite tests worst — a live run's numbers have no independently known
correct value.
"""

from __future__ import annotations

import statistics
from collections.abc import Collection, Sequence
from dataclasses import dataclass

Source = tuple[str, str]
"""(source_type, source_id) — "note" | "diagnostic" | "eda", and its row id."""


def _check_relevant(relevant: Collection[Source]) -> None:
    if not relevant:
        # A golden-set entry with no labelled sources is unanswerable. Scoring
        # it 0.0 would drag every mean down for what is really a data-entry bug.
        raise ValueError("the relevant set is empty; a golden-set entry must label at least one source")


def precision_at_k(ranked: Sequence[Source], relevant: Collection[Source], k: int) -> float:
    """Fraction of the top `k` slots filled by a relevant source.

    Divides by `k`, NOT by `len(ranked)`. A search asked for 8 sources and
    returning 2 relevant ones was not perfectly precise, and dividing by the
    result length would report 1.0 and hide the shortfall.
    """
    _check_relevant(relevant)
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")
    wanted = set(relevant)
    return sum(1 for source in ranked[:k] if source in wanted) / k


def recall_at_k(ranked: Sequence[Source], relevant: Collection[Source], k: int) -> float:
    """Fraction of the relevant sources that appear in the top `k`."""
    _check_relevant(relevant)
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")
    wanted = set(relevant)
    return sum(1 for source in ranked[:k] if source in wanted) / len(wanted)


def reciprocal_rank(ranked: Sequence[Source], relevant: Collection[Source]) -> float:
    """1 / (1-based position of the first relevant source); 0.0 if none."""
    _check_relevant(relevant)
    wanted = set(relevant)
    for position, source in enumerate(ranked, start=1):
        if source in wanted:
            return 1.0 / position
    return 0.0


@dataclass(frozen=True)
class QueryScore:
    """One golden-set query's scores, at every reported cutoff."""

    query_id: str
    precision: dict[int, float]
    recall: dict[int, float]
    rr: float


def score_query(
    query_id: str,
    ranked: Sequence[Source],
    relevant: Collection[Source],
    ks: Sequence[int],
) -> QueryScore:
    """Score one query. `ranked` is ONE search's results; the cutoffs in `ks`
    are readings of that one list, not separate searches (D46)."""
    return QueryScore(
        query_id=query_id,
        precision={k: precision_at_k(ranked, relevant, k) for k in ks},
        recall={k: recall_at_k(ranked, relevant, k) for k in ks},
        rr=reciprocal_rank(ranked, relevant),
    )


@dataclass(frozen=True)
class Aggregate:
    n: int
    precision: dict[int, float]
    recall: dict[int, float]
    mrr: float


def aggregate(scores: Sequence[QueryScore]) -> Aggregate:
    """Unweighted means across queries. MRR is the mean reciprocal rank."""
    if not scores:
        return Aggregate(n=0, precision={}, recall={}, mrr=0.0)
    ks = sorted(scores[0].precision)
    return Aggregate(
        n=len(scores),
        precision={k: statistics.fmean(s.precision[k] for s in scores) for k in ks},
        recall={k: statistics.fmean(s.recall[k] for s in scores) for k in ks},
        mrr=statistics.fmean(s.rr for s in scores),
    )


def paired_mrr_delta(
    baseline: Sequence[QueryScore], challenger: Sequence[QueryScore]
) -> tuple[float, float]:
    """(mean, standard error) of the PER-QUERY reciprocal-rank differences.

    D46's adoption rule needs the spread of the differences, so the pairing
    happens per query and not between two aggregate means — differencing two
    means discards the spread entirely, after which every challenger clears any
    bar you set.

    A single query has no spread, so the standard error is infinite rather than
    zero: reporting 0.0 would let any difference at all clear the bar.
    """
    if [s.query_id for s in baseline] != [s.query_id for s in challenger]:
        raise ValueError("paired comparison needs the same queries in the same order")
    diffs = [c.rr - b.rr for b, c in zip(baseline, challenger, strict=True)]
    if not diffs:
        raise ValueError("no queries to compare")
    mean = statistics.fmean(diffs)
    if len(diffs) < 2:
        return mean, float("inf")
    return mean, statistics.stdev(diffs) / (len(diffs) ** 0.5)
```

- [x] **Step 4: Run to verify they pass**

```bash
poetry run pytest backend/tests/test_eval_metrics.py -v
```

Expected: PASS, 14 tests.

- [x] **Step 5: Run the gate and commit**

```bash
make check
git add backend/eval/__init__.py backend/eval/metrics.py backend/tests/test_eval_metrics.py
git commit -m "$(cat <<'EOF'
feat: eval metrics over sources — precision@k, recall@k, MRR (D43)

Ground truth is (source_type, source_id), the unit search_runs returns:
not experiment ids (an eda source has none since D33) and not chunks
(k counts sources since 3.4b).

Pure and offline, so the arithmetic runs inside make check. It is the
part most worth pinning and the part a real-API suite tests worst — a
live run's numbers have no independently known correct value.

paired_mrr_delta pairs per query rather than differencing two means,
because D46's adoption rule needs the spread the latter throws away.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `backend/eval/cache.py` — the query-vector cache

The Voyage free tier allows **3 requests per minute**. An uncached 20-query eval run costs roughly seven minutes of forced backoff, which means it does not get run — and the nine-configuration sweep in Task 8 would be unusable.

**Files:**
- Create: `backend/eval/cache.py`
- Modify: `.gitignore`
- Test: `backend/tests/test_eval_cache.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `CachingVoyageClient(path: Path, inner: Any | None = None)` with `.embed(texts: list[str], *, model: str, input_type: str, output_dimension: int) -> _Response` (where `_Response.embeddings: list[list[float]]`), plus `.hits: int`, `.misses: int`, and `.save() -> None`.

**Design note — why a client shim and not a change to `retrieval`.** `retrieval.search_runs(session, query, *, filters, k, client)` already threads `client` down to `embeddings.embed_texts`, whose only requirement of that object is `.embed(texts, model=…, input_type=…, output_dimension=…) → obj.embeddings`. Satisfying that contract puts the entire cache inside `backend/eval/` and changes no production code. It also means the cached path exercises `embed_texts`' width check and its retry wrapper exactly as the live path does.

**Design note — why the model name is in the key.** Two models' vectors are not comparable (CLAUDE.md, D14). With `voyage_model` in the key, changing it misses and refetches instead of silently serving vectors from the previous model — the rule holds without anyone remembering to clear a file.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_eval_cache.py`:

```python
"""The eval's query-vector cache. Offline: the inner client is a fake."""

import json

import pytest

from eval.cache import CachingVoyageClient


class _FakeVoyage:
    """Records every call so the tests can assert on what was NOT sent."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def embed(self, texts, *, model, input_type, output_dimension):
        self.calls.append(list(texts))
        return type("R", (), {"embeddings": [[0.5] * output_dimension for _ in texts]})()


def test_a_miss_calls_through_and_a_hit_does_not(tmp_path):
    inner = _FakeVoyage()
    cache = CachingVoyageClient(tmp_path / "c.json", inner=inner)

    first = cache.embed(["ridge"], model="voyage-4", input_type="query", output_dimension=4)
    second = cache.embed(["ridge"], model="voyage-4", input_type="query", output_dimension=4)

    assert first.embeddings == second.embeddings
    assert len(inner.calls) == 1
    assert cache.hits == 1 and cache.misses == 1


def test_only_the_uncached_texts_are_sent(tmp_path):
    """A partially-cached batch must not re-send what it already holds, or the
    rate limit is hit for text the cache already has."""
    inner = _FakeVoyage()
    cache = CachingVoyageClient(tmp_path / "c.json", inner=inner)
    cache.embed(["a"], model="m", input_type="query", output_dimension=2)
    cache.embed(["a", "b"], model="m", input_type="query", output_dimension=2)
    assert inner.calls == [["a"], ["b"]]


def test_results_come_back_in_the_requested_order(tmp_path):
    """Merging cached and freshly-embedded vectors must preserve input order —
    a silent transposition would mislabel every query's vector."""
    inner = _FakeVoyage()
    cache = CachingVoyageClient(tmp_path / "c.json", inner=inner)
    cache.embed(["b"], model="m", input_type="query", output_dimension=2)

    def positional(texts, *, model, input_type, output_dimension):
        inner.calls.append(list(texts))
        return type("R", (), {"embeddings": [[float(len(t))] * output_dimension for t in texts]})()

    inner.embed = positional
    resp = cache.embed(["a", "b", "ccc"], model="m", input_type="query", output_dimension=2)
    assert resp.embeddings[0] == [1.0, 1.0]
    assert resp.embeddings[2] == [3.0, 3.0]


def test_the_model_name_is_part_of_the_key(tmp_path):
    """Two models' vectors are not comparable (D14). Changing the model must
    miss, not serve the previous model's vectors."""
    inner = _FakeVoyage()
    cache = CachingVoyageClient(tmp_path / "c.json", inner=inner)
    cache.embed(["ridge"], model="voyage-4", input_type="query", output_dimension=2)
    cache.embed(["ridge"], model="voyage-3", input_type="query", output_dimension=2)
    assert len(inner.calls) == 2


def test_the_input_type_is_part_of_the_key(tmp_path):
    """Voyage's models are trained with document/query asymmetry (D29); one
    stored under the other's key would cost recall with no symptom."""
    inner = _FakeVoyage()
    cache = CachingVoyageClient(tmp_path / "c.json", inner=inner)
    cache.embed(["ridge"], model="m", input_type="query", output_dimension=2)
    cache.embed(["ridge"], model="m", input_type="document", output_dimension=2)
    assert len(inner.calls) == 2


def test_the_cache_survives_a_reload(tmp_path):
    path = tmp_path / "c.json"
    inner = _FakeVoyage()
    first = CachingVoyageClient(path, inner=inner)
    first.embed(["ridge"], model="m", input_type="query", output_dimension=2)
    first.save()

    second = CachingVoyageClient(path, inner=inner)
    second.embed(["ridge"], model="m", input_type="query", output_dimension=2)
    assert len(inner.calls) == 1
    assert second.hits == 1


def test_a_corrupt_cache_file_is_ignored_not_fatal(tmp_path):
    """A half-written file must cost a slow run, never a crash that looks like
    a retrieval bug."""
    path = tmp_path / "c.json"
    path.write_text("{not json")
    cache = CachingVoyageClient(path, inner=_FakeVoyage())
    resp = cache.embed(["ridge"], model="m", input_type="query", output_dimension=2)
    assert len(resp.embeddings) == 1


def test_save_writes_readable_json(tmp_path):
    path = tmp_path / "c.json"
    cache = CachingVoyageClient(path, inner=_FakeVoyage())
    cache.embed(["ridge"], model="m", input_type="query", output_dimension=2)
    cache.save()
    assert len(json.loads(path.read_text())) == 1


def test_no_inner_client_and_a_miss_is_a_clear_error(tmp_path):
    """--no-cache-adjacent misuse should name the problem, not fail deep inside
    the Voyage SDK with a None."""
    cache = CachingVoyageClient(tmp_path / "c.json", inner=None)
    with pytest.raises(RuntimeError, match="no inner client"):
        cache.embed(["ridge"], model="m", input_type="query", output_dimension=2)
```

- [x] **Step 2: Run to verify they fail**

```bash
poetry run pytest backend/tests/test_eval_cache.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'eval.cache'`.

- [x] **Step 3: Write the implementation**

Create `backend/eval/cache.py`:

```python
"""A caching stand-in for the Voyage client, used only by the eval harness.

The free tier allows 3 requests per minute. An uncached 20-query run is about
seven minutes of forced backoff, which means it does not get run; the
nine-configuration sweep (D46) would be unusable. Query text is identical
across configurations, so after the first run the sweep costs no Voyage calls
at all.

This is a CLIENT SHIM, not a change to `app.retrieval`.
`retrieval.search_runs(..., client=...)` already threads its client down to
`embeddings.embed_texts`, whose only requirement is
`.embed(texts, model=, input_type=, output_dimension=) -> obj.embeddings`.
Satisfying that contract keeps the whole cache inside the eval package and
leaves the production path — including its width check and its 429 retry —
exercised exactly as it is in a live request.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Response:
    """Mimics the Voyage SDK's response object; `embed_texts` reads only this."""

    embeddings: list[list[float]]


def cache_key(model: str, input_type: str, text: str) -> str:
    """The model name is IN the key.

    Two models' vectors are not comparable (D14), so changing `voyage_model`
    must miss and refetch. Keying on the text alone would silently serve the
    previous model's vectors, and the only symptom would be eval numbers that
    nobody can attribute.

    `input_type` is in the key for the same reason: Voyage's models are trained
    with the document/query asymmetry (D29), and the two vectors for one string
    are different vectors.
    """
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{model}|{input_type}|{digest}"


class CachingVoyageClient:
    """Reads vectors from a JSON file; delegates misses to `inner`."""

    def __init__(self, path: Path, inner: Any | None = None) -> None:
        self.path = Path(path)
        self.inner = inner
        self.hits = 0
        self.misses = 0
        self._vectors: dict[str, list[float]] = self._load()

    def _load(self) -> dict[str, list[float]]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            # A half-written file must cost a slow run, never a crash that
            # presents as a retrieval bug.
            logger.warning("ignoring unreadable vector cache at %s", self.path)
            return {}
        return {k: [float(x) for x in v] for k, v in data.items()}

    def embed(
        self, texts: list[str], *, model: str, input_type: str, output_dimension: int
    ) -> _Response:
        keys = [cache_key(model, input_type, t) for t in texts]
        missing = [t for t, key in zip(texts, keys, strict=True) if key not in self._vectors]

        if missing:
            if self.inner is None:
                raise RuntimeError(
                    f"vector cache has no inner client and {len(missing)} text(s) are uncached"
                )
            fresh = self.inner.embed(
                missing, model=model, input_type=input_type, output_dimension=output_dimension
            )
            for text, vector in zip(missing, fresh.embeddings, strict=True):
                self._vectors[cache_key(model, input_type, text)] = [float(v) for v in vector]

        self.misses += len(missing)
        self.hits += len(texts) - len(missing)
        # Rebuilt from the keys so the output order matches the INPUT order; a
        # transposition here would mislabel every query's vector.
        return _Response(embeddings=[self._vectors[key] for key in keys])

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._vectors))
```

- [x] **Step 4: Run to verify they pass**

```bash
poetry run pytest backend/tests/test_eval_cache.py -v
```

Expected: PASS, 9 tests.

- [x] **Step 5: Ignore the cache file**

Append to `.gitignore`, above the `# Environments` block:

```
# Eval query-vector cache — a derived artifact, per-key, and rebuildable.
backend/eval/.vector-cache.json
```

- [x] **Step 6: Run the gate and commit**

```bash
make check
git add backend/eval/cache.py backend/tests/test_eval_cache.py .gitignore
git commit -m "$(cat <<'EOF'
feat: cache eval query vectors behind the Voyage client contract (4.2)

The free tier is 3 RPM, so an uncached 20-query run is ~7 minutes of
forced backoff and the 9-config sweep is unusable. Query text is
identical across configs, so after the first run the sweep is free.

Implemented as a client shim rather than a change to app.retrieval:
search_runs already threads `client` to embed_texts, so the cache lives
entirely in the eval package and the production path — width check and
429 retry included — is exercised exactly as in a live request.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: The curation manifest and its applier

**Files:**
- Create: `scripts/apply_curation.py`
- Test: `backend/tests/test_curation.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `QUOTAS: dict[tuple[str, str], int]` — `(experiment_name, model_type) → how many notes to approve`
  - `spread_indices(n: int, quota: int) -> list[int]` — pure; which positions in a metric-sorted stratum to approve
  - `build_manifest(runs: list[dict], findings: list[dict]) -> dict` — the YAML document
  - `apply_manifest(manifest: dict, client: Any) -> tuple[int, int]` — `(approved, rejected)`; `client` needs only `.patch(url, json=…)`, which both `httpx.Client` and FastAPI's `TestClient` satisfy
  - `backend/eval/curation.yaml` — written by `--plan` in Task 5, committed there

**Design note — why the selection rule is code, not a hand-picked list.** The corpus is the eval's ground truth. A hand-picked list cannot be rebuilt from a clean database, and a golden set keyed to ids from a corpus nobody can reproduce is a golden set nobody can check. Encoding the rule also forces the D45 property that matters: selection is by **outcome diversity** — best, worst, and evenly spaced middles — never by note quality, which would build an unrepresentatively clean corpus and delete exactly the failures the agent needs in order to recommend against repeating them.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_curation.py`:

```python
"""The curation manifest (D45): its selection rule and its applier."""

import pytest

from apply_curation import apply_manifest, build_manifest, spread_indices


def test_spread_always_takes_the_best_and_the_worst():
    """Outcome diversity is the point (D45). A rule that took the top N would
    delete every failure from the corpus, and failures are what the agent needs
    in order to recommend against repeating them."""
    picks = spread_indices(8, 4)
    assert picks[0] == 0
    assert picks[-1] == 7
    assert len(picks) == 4
    assert picks == sorted(set(picks))


def test_spread_of_two_takes_both_ends():
    assert spread_indices(8, 2) == [0, 7]


def test_spread_takes_everything_when_the_quota_covers_the_stratum():
    assert spread_indices(2, 2) == [0, 1]


def test_a_quota_larger_than_the_stratum_is_not_an_error():
    assert spread_indices(2, 5) == [0, 1]


def test_a_quota_of_one_takes_the_best():
    assert spread_indices(8, 1) == [0]


def test_spread_of_an_empty_stratum_is_empty():
    assert spread_indices(0, 4) == []


def test_the_manifest_covers_every_run_exactly_once():
    """A run missing from the manifest stays a draft forever and is silently
    absent from the corpus — invisible, because nothing errors."""
    runs = [
        {
            "id": f"r{i}",
            "model_type": "ridge",
            "experiment_name": "revenue-nowcast",
            "metrics": {"rmse": float(i)},
        }
        for i in range(8)
    ]
    manifest = build_manifest(runs, findings=[])
    ids = [entry["id"] for entry in manifest["runs"]]
    assert sorted(ids) == sorted(r["id"] for r in runs)
    assert len(ids) == len(set(ids))


def test_the_manifest_approves_the_quota_and_rejects_the_rest():
    runs = [
        {
            "id": f"r{i}",
            "model_type": "ridge",
            "experiment_name": "revenue-nowcast",
            "metrics": {"rmse": float(i)},
        }
        for i in range(8)
    ]
    manifest = build_manifest(runs, findings=[])
    approved = [e for e in manifest["runs"] if e["decision"] == "approved"]
    rejected = [e for e in manifest["runs"] if e["decision"] == "rejected"]
    assert len(approved) == 4  # QUOTAS[("revenue-nowcast", "ridge")]
    assert len(rejected) == 4
    assert all(e["reason"] for e in manifest["runs"])


def test_every_finding_is_approved():
    """All six findings are distinct sources about distinct things, and the
    three eda ones are the only route to dataset-level questions (D30)."""
    manifest = build_manifest([], findings=[{"id": "f1"}, {"id": "f2"}])
    assert [e["decision"] for e in manifest["findings"]] == ["approved", "approved"]


def test_a_run_with_no_metric_is_rejected_not_crashed():
    """A run whose tracking-store record is missing cannot be ranked within its
    stratum. Rejecting it is honest; sorting None would raise."""
    runs = [
        {"id": "r0", "model_type": "ridge", "experiment_name": "revenue-nowcast", "metrics": {}},
    ]
    manifest = build_manifest(runs, findings=[])
    assert manifest["runs"][0]["decision"] == "rejected"


def test_apply_sends_one_patch_per_entry(client):
    """Through the API (D13), so route validation is never bypassed."""
    calls: list[tuple[str, dict]] = []

    class _Recorder:
        def patch(self, url, json):
            calls.append((url, json))
            return type("R", (), {"status_code": 200, "text": ""})()

    manifest = {
        "runs": [{"id": "r1", "decision": "approved", "reason": "x"}],
        "findings": [{"id": "f1", "decision": "approved", "reason": "y"}],
    }
    approved, rejected = apply_manifest(manifest, _Recorder())
    assert approved == 2 and rejected == 0
    assert calls[0] == ("/runs/r1", {"notes_status": "approved"})
    assert calls[1] == ("/findings/f1", {"status": "approved"})


def test_apply_never_sends_note_text(client):
    """Writing text through PATCH /runs is deliberately NOT an approval (D20).
    Sending both would make the curation able to rewrite the corpus it is
    supposed to be selecting from."""
    calls: list[dict] = []

    class _Recorder:
        def patch(self, url, json):
            calls.append(json)
            return type("R", (), {"status_code": 200, "text": ""})()

    apply_manifest({"runs": [{"id": "r1", "decision": "rejected", "reason": "x"}]}, _Recorder())
    assert calls == [{"notes_status": "rejected"}]
    assert all("notes" not in call and "text" not in call for call in calls)


def test_a_failed_patch_raises_rather_than_being_counted(client):
    """A half-applied manifest is a corpus that does not match its own file.
    Failing loudly is the only way that gets noticed."""

    class _Broken:
        def patch(self, url, json):
            return type("R", (), {"status_code": 422, "text": "nope"})()

    with pytest.raises(RuntimeError, match="422"):
        apply_manifest({"runs": [{"id": "r1", "decision": "approved", "reason": "x"}]}, _Broken())
```

- [x] **Step 2: Run to verify they fail**

```bash
poetry run pytest backend/tests/test_curation.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'apply_curation'`.

- [x] **Step 3: Write the script**

Create `scripts/apply_curation.py`:

```python
"""Curate the retrieval corpus (D45).

Two modes:

    python scripts/apply_curation.py --plan    # read the API, write curation.yaml
    python scripts/apply_curation.py           # apply curation.yaml through the API

The manifest is committed so the corpus is REPRODUCIBLE from a clean database.
The golden set (D43) is keyed to these ids, so a corpus nobody can rebuild is a
golden set nobody can check.

Selection is by OUTCOME DIVERSITY, never by note quality: best, worst, and
evenly spaced middles within each (experiment, model) stratum. Approving the
well-written notes instead would build an unrepresentatively clean corpus —
every retrieval number measured against it optimistic in a way nothing about
the number reveals — and would delete the failures, which are the half of the
history the agent most needs in order to recommend against repeating them.

Everything goes through the API (D13); this script never touches the database.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

API = os.environ.get("API", "http://localhost:8000")
MANIFEST = Path(__file__).resolve().parents[1] / "backend" / "eval" / "curation.yaml"

# How many notes to approve per (experiment, model) stratum. 17 of 34 (D45).
# Both persistence runs: D25 makes the baseline a real logged run precisely so
# it anchors comparisons, and a corpus without it cannot answer "what is the
# baseline" — the question the baseline exists to make answerable.
QUOTAS: dict[tuple[str, str], int] = {
    ("revenue-nowcast", "ridge"): 4,
    ("revenue-nowcast", "random_forest"): 4,
    ("revenue-nowcast", "gradient_boosting"): 4,
    ("revenue-nowcast", "persistence"): 2,
    ("pc-part-video-card", "ridge"): 3,
}
DEFAULT_QUOTA = 2


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def spread_indices(n: int, quota: int) -> list[int]:
    """Positions to approve in a metric-sorted stratum of size `n`.

    Always includes index 0 (best) and n-1 (worst), with the remainder spread
    evenly between. Taking the top `quota` instead would delete every failure
    from the corpus.
    """
    if n <= 0 or quota <= 0:
        return []
    if quota >= n:
        return list(range(n))
    if quota == 1:
        return [0]
    step = (n - 1) / (quota - 1)
    return sorted({round(i * step) for i in range(quota)})


def build_manifest(runs: list[dict[str, Any]], findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Every run appears exactly once, approved or rejected with a reason.

    A run left out of the manifest stays a draft forever and is silently absent
    from the corpus — invisible, because nothing errors.
    """
    strata: dict[tuple[str, str], list[dict[str, Any]]] = {}
    unrankable: list[dict[str, Any]] = []
    for run in runs:
        metric = _primary_metric(run)
        if metric is None:
            unrankable.append(run)
            continue
        strata.setdefault((run["experiment_name"], run["model_type"]), []).append(run)

    entries: list[dict[str, Any]] = []
    for (experiment_name, model_type), group in sorted(strata.items()):
        group.sort(key=lambda r: (_primary_metric(r), r["id"]))
        quota = QUOTAS.get((experiment_name, model_type), DEFAULT_QUOTA)
        picks = set(spread_indices(len(group), quota))
        for position, run in enumerate(group):
            if position in picks:
                where = "best" if position == 0 else "worst" if position == len(group) - 1 else "mid"
                reason = f"{experiment_name}/{model_type}: {where} of {len(group)} by holdout metric"
                entries.append({"id": run["id"], "decision": "approved", "reason": reason})
            else:
                entries.append(
                    {
                        "id": run["id"],
                        "decision": "rejected",
                        "reason": (
                            f"{experiment_name}/{model_type}: outside the "
                            f"{quota}-of-{len(group)} outcome-diversity sample"
                        ),
                    }
                )
    for run in unrankable:
        entries.append(
            {
                "id": run["id"],
                "decision": "rejected",
                "reason": "no holdout metric; cannot be placed in its stratum",
            }
        )

    return {
        "runs": entries,
        # All six findings: each is a distinct source about a distinct thing,
        # and the three eda ones are the only route to dataset-level questions
        # (D30 expands every matching run to an ("eda", dataset_id) key).
        "findings": [
            {"id": f["id"], "decision": "approved", "reason": "distinct source; no redundancy"}
            for f in findings
        ],
    }


def _primary_metric(run: dict[str, Any]) -> float | None:
    metrics = run.get("metrics") or {}
    for name in ("rmse", "mae", "accuracy"):
        if name in metrics:
            return float(metrics[name])
    return None


def apply_manifest(manifest: dict[str, Any], client: Any) -> tuple[int, int]:
    """PATCH every entry. Returns (approved, rejected).

    Sends ONLY the status field. Writing text through PATCH /runs is
    deliberately not an approval (D20); sending both would let the curation
    rewrite the corpus it is supposed to be selecting from.

    A failed PATCH raises. A half-applied manifest is a corpus that does not
    match its own committed file, and failing loudly is the only way that gets
    noticed before it silently becomes the eval's ground truth.
    """
    approved = rejected = 0
    for entry in manifest.get("runs", []):
        _patch(client, f"/runs/{entry['id']}", {"notes_status": entry["decision"]})
        approved += entry["decision"] == "approved"
        rejected += entry["decision"] == "rejected"
    for entry in manifest.get("findings", []):
        _patch(client, f"/findings/{entry['id']}", {"status": entry["decision"]})
        approved += entry["decision"] == "approved"
        rejected += entry["decision"] == "rejected"
    return approved, rejected


def _patch(client: Any, url: str, payload: dict[str, Any]) -> None:
    response = client.patch(url, json=payload)
    if response.status_code >= 400:
        raise RuntimeError(f"PATCH {url} returned {response.status_code}: {response.text}")


def _plan(client: httpx.Client) -> None:
    experiments = client.get("/experiments").json()
    names = {e["id"]: e["name"] for e in experiments}
    runs = client.get("/runs", params={"limit": 500}).json()
    for run in runs:
        run["experiment_name"] = names.get(run["experiment_id"], "?")
    findings = client.get("/findings", params={"limit": 500}).json()

    manifest = build_manifest(runs, findings)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(yaml.safe_dump(manifest, sort_keys=False))
    approved = sum(1 for e in manifest["runs"] if e["decision"] == "approved")
    print(f"wrote {MANIFEST} — {approved} of {len(manifest['runs'])} notes approved, ")
    print(f"and all {len(manifest['findings'])} findings. Review it before applying.")


def main() -> None:
    plan = "--plan" in sys.argv
    with httpx.Client(base_url=API, timeout=60.0) as client:
        try:
            if plan:
                _plan(client)
                return
            if not MANIFEST.exists():
                fail(f"{MANIFEST} does not exist; run with --plan first")
            manifest = yaml.safe_load(MANIFEST.read_text())
            approved, rejected = apply_manifest(manifest, client)
        except httpx.HTTPError as exc:
            fail(f"cannot reach the API at {API} — is `make dev` running? ({exc})")
    print(
        f"applied: {approved} approved, {rejected} rejected.\n"
        f"The index is NOT updated by this script (D17) — run `make embed` next."
    )


if __name__ == "__main__":
    main()
```

- [x] **Step 4: Run to verify they pass**

```bash
poetry run pytest backend/tests/test_curation.py -v
```

Expected: PASS, 13 tests. If `yaml` is missing, add it: `poetry add pyyaml`.

- [x] **Step 5: Run the gate and commit**

```bash
make check
git add scripts/apply_curation.py backend/tests/test_curation.py pyproject.toml poetry.lock
git commit -m "$(cat <<'EOF'
feat: curation manifest and applier for the retrieval corpus (D45)

Selection is a rule, not a hand-picked list: the corpus is the eval's
ground truth, and a golden set keyed to ids nobody can reproduce is a
golden set nobody can check.

Within each (experiment, model) stratum the rule takes best, worst and
evenly spaced middles. Selecting for note quality instead would build an
unrepresentatively clean corpus and delete the failures — the half the
agent needs in order to recommend against repeating them.

Sends only the status field: writing text through PATCH /runs is
deliberately not an approval (D20).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Apply the curation, and verify the reap for real

This task changes **data**, not code. Its deliverable is a committed `curation.yaml`, a reconciled index, and a recorded reap verification.

**Files:**
- Create: `backend/eval/curation.yaml` (generated, then committed)

**Interfaces:**
- Consumes: `scripts/apply_curation.py` from Task 4.
- Produces: a corpus of **23 approved sources** (17 run notes + 6 findings), roughly 41 chunks. Task 6's golden set is keyed to these ids.

**Prerequisites:** `make db-up` running, `make dev` running, `VOYAGE_API_KEY` set in `.env`.

- [x] **Step 1: Record the starting state**

```bash
psql "postgresql://wavepoint:wavepoint@localhost:5433/wavepoint" -c "
  select 'runs' as t, notes_status as status, count(*) from app.runs group by 2
  union all select 'findings', status, count(*) from app.findings group by 2
  union all select 'chunks', 'n/a', count(*) from app.experiment_note_chunks;"
```

Expected: 34 runs all `draft`, 6 findings (2 `approved` / 4 `draft`), 8 chunks.

- [x] **Step 2: Generate the manifest**

```bash
poetry run python scripts/apply_curation.py --plan
```

Expected: `backend/eval/curation.yaml` written, reporting **17 of 34** notes approved and all 6 findings.

- [x] **Step 3: Review the manifest by hand**

Open `backend/eval/curation.yaml` and confirm:
- 34 run entries, no duplicate ids
- exactly 17 `approved`
- both `persistence` runs approved
- every entry carries a non-empty `reason`

If any of these is wrong, fix `QUOTAS` or `spread_indices` in Task 4 and regenerate — do not hand-edit the file, which would break the reproducibility the manifest exists for.

- [x] **Step 4: Apply it**

```bash
poetry run python scripts/apply_curation.py
```

Expected: `applied: 23 approved, 17 rejected.`

- [x] **Step 5: Reconcile the index**

```bash
make embed
```

This sends one Voyage request per changed source. At 3 requests/minute with ~21 changed sources, expect **7–8 minutes** and several logged `voyage rate limit … retrying` lines. Those are the expected path, not a failure.

Expected report: roughly 21 indexed, 0 reaped, 2 unchanged.

- [x] **Step 6: Confirm the corpus**

```bash
psql "postgresql://wavepoint:wavepoint@localhost:5433/wavepoint" -c "
  select source_type, count(distinct source_id) as sources, count(*) as chunks
  from app.experiment_note_chunks group by 1 order by 1;"
```

Expected: 23 distinct sources in total (17 `note`, 3 `eda`, 3 `diagnostic`), roughly 41 chunks.

- [x] **Step 7: Verify the reap end-to-end**

The 17 rejections above did **not** exercise the reap: those notes went `draft → rejected` and were never indexed, so there was nothing to delete. Only `approved → rejected` fires it. This is the reap's only end-to-end exercise outside unit tests.

Pick any approved run id from the manifest and set `RID`:

```bash
RID=<an approved run id from curation.yaml>
PSQL='psql postgresql://wavepoint:wavepoint@localhost:5433/wavepoint -At -c'

$PSQL "select count(*) from app.experiment_note_chunks where source_id='$RID' and source_type='note';"
# expect: a positive number

curl -s -X PATCH localhost:8000/runs/$RID -H 'content-type: application/json' \
  -d '{"notes_status":"rejected"}' >/dev/null
make embed
$PSQL "select count(*) from app.experiment_note_chunks where source_id='$RID' and source_type='note';"
# expect: 0   <-- the reap

curl -s -X PATCH localhost:8000/runs/$RID -H 'content-type: application/json' \
  -d '{"notes_status":"approved"}' >/dev/null
make embed
$PSQL "select count(*) from app.experiment_note_chunks where source_id='$RID' and source_type='note';"
# expect: back to the original positive number
```

If the middle count is not 0, stop: the reap is broken, rejected text is still ranking and being served labelled `approved`, and D28 is defeated silently. Fix that before continuing — nothing later in this plan will reveal it.

- [x] **Step 8: Commit the manifest**

```bash
git add backend/eval/curation.yaml
git commit -m "$(cat <<'EOF'
chore: curate the retrieval corpus — 23 approved sources (D45)

17 of 34 run notes, stratified by experiment and model and selected for
outcome diversity, plus all 6 findings. The remaining 17 notes rejected.

Reap verified end to end: approve -> embed -> reject -> embed removes the
chunks, and re-approving restores them. The 17 rejections above do NOT
exercise it — draft -> rejected was never indexed, so only an
approved -> rejected transition fires the reap.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: The golden set and the runner

**Files:**
- Create: `backend/eval/golden_set.yaml`, `backend/eval/runner.py`
- Modify: `Makefile:33-34` (the `eval` target)
- Test: `backend/tests/test_eval_runner.py`

**Interfaces:**
- Consumes: `eval.metrics.score_query`, `eval.metrics.aggregate`, `eval.metrics.Source` (Task 2); `eval.cache.CachingVoyageClient` (Task 3); the corpus ids from `backend/eval/curation.yaml` (Task 5).
- Produces:
  - `KS: tuple[int, ...] = (3, 5, 8)`
  - `GoldenQuery` frozen dataclass: `id: str`, `query: str`, `relevant: frozenset[Source]`, `notes: str`
  - `load_golden_set(path: Path) -> list[GoldenQuery]`
  - `run_eval(session, queries, *, client, k) -> list[QueryScore]`
  - `render_report(scores, agg, label, config) -> str`
  - `validate_golden_set(session, queries) -> list[str]` — returns human-readable problems; empty means clean

### D44 — how the queries must be written

**Read only the leaderboard, the params and the metrics. Never the note prose.** Then label relevance afterwards.

Claude wrote the draft notes. A query written while reading a note largely measures whether retrieval can find the document the query was copied from — a real property, but a much weaker one than semantic retrieval, and the resulting numbers do not distinguish the two. **This rule binds anyone extending the set later**; a set that is blind for its first 20 queries and note-derived for its next 20 reports one number over two incomparable halves.

Draft the 20 queries from this, and nothing else:

```bash
psql "postgresql://wavepoint:wavepoint@localhost:5433/wavepoint" -c "
  select e.name, r.model_type, r.id, r.notes_status
  from app.runs r join app.experiments e on e.id = r.experiment_id
  where r.notes_status = 'approved' order by e.name, r.model_type;"
curl -s localhost:8000/experiments | python3 -m json.tool
curl -s localhost:8000/experiments/<id>/runs | python3 -m json.tool   # ranks, params, metrics
```

Cover four shapes, roughly five queries each:

1. **Which model won** — the acceptance criterion's own words: "which model performed best on the revenue nowcast?"
2. **What ranges have I tried** — parameter-space questions: "what alpha values have I tried for ridge?"
3. **What went wrong** — failure questions, answerable only because Task 5 curated for outcome diversity: "which runs did worse than the baseline?"
4. **Dataset questions** that must reach an `eda` finding, exercising the D30 key expansion: "what does the revenue panel's missingness look like?"

Label relevance by asking, for each approved source: *would a correct answer to this question need to cite this?* Two to four relevant sources per query is the target. A query with none is unanswerable and must be rewritten — `metrics.py` raises on an empty relevant set rather than scoring it 0.0.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_eval_runner.py`:

```python
"""Runner wiring. Offline: search_runs is monkeypatched, so no Voyage and no
Postgres. What is tested here is the plumbing between retrieval and metrics —
the metric arithmetic itself is pinned in test_eval_metrics.py."""

from pathlib import Path

import pytest

from eval import runner
from eval.runner import GoldenQuery, load_golden_set, render_report, run_eval


def _hit(source_type, source_id, score):
    class _H:
        pass

    h = _H()
    h.source_type, h.source_id, h.score = source_type, source_id, score
    h.snippet, h.run_id, h.experiment_id, h.dataset_id = "…", None, None, None
    return h


def test_load_reads_queries_and_freezes_their_relevant_sets(tmp_path):
    path = tmp_path / "g.yaml"
    path.write_text(
        "- id: q1\n"
        "  query: which model won?\n"
        "  relevant:\n"
        "    - [note, abc]\n"
        "    - [eda, def]\n"
        "  notes: from the leaderboard only\n"
    )
    queries = load_golden_set(path)
    assert len(queries) == 1
    assert queries[0].id == "q1"
    assert queries[0].relevant == frozenset({("note", "abc"), ("eda", "def")})


def test_load_rejects_a_query_with_no_relevant_sources(tmp_path):
    """Unanswerable, and scoring it 0.0 would drag the mean down for a
    data-entry bug."""
    path = tmp_path / "g.yaml"
    path.write_text("- id: q1\n  query: hm?\n  relevant: []\n  notes: x\n")
    with pytest.raises(ValueError, match="q1"):
        load_golden_set(path)


def test_load_rejects_duplicate_ids(tmp_path):
    """paired_mrr_delta pairs by position and id; duplicates make the pairing
    ambiguous and the sweep's comparison meaningless."""
    path = tmp_path / "g.yaml"
    path.write_text(
        "- id: q1\n  query: a\n  relevant: [[note, x]]\n  notes: ''\n"
        "- id: q1\n  query: b\n  relevant: [[note, y]]\n  notes: ''\n"
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_golden_set(path)


def test_run_eval_ranks_sources_in_the_order_search_returned_them(monkeypatch):
    """MRR depends entirely on position, so a reordering here would be a
    silent, systematic scoring error."""
    monkeypatch.setattr(
        runner.retrieval,
        "search_runs",
        lambda session, query, **kw: (
            [_hit("eda", "c", 0.9), _hit("note", "a", 0.8), _hit("note", "b", 0.7)],
            [],
        ),
    )
    queries = [GoldenQuery("q1", "which model won?", frozenset({("note", "a")}), "")]
    scores = run_eval(session=None, queries=queries, client=None, k=8)
    assert scores[0].rr == pytest.approx(1 / 2)
    assert scores[0].precision[3] == pytest.approx(1 / 3)


def test_run_eval_passes_the_cache_client_through(monkeypatch):
    """If the client is dropped, every run pays the 3 RPM tax and the sweep is
    unusable — with no symptom except slowness."""
    seen = {}

    def _fake(session, query, **kw):
        seen.update(kw)
        return ([_hit("note", "a", 0.9)], [])

    monkeypatch.setattr(runner.retrieval, "search_runs", _fake)
    sentinel = object()
    run_eval(
        session=None,
        queries=[GoldenQuery("q1", "x", frozenset({("note", "a")}), "")],
        client=sentinel,
        k=8,
    )
    assert seen["client"] is sentinel
    assert seen["k"] == 8


def test_run_eval_scores_a_query_that_retrieved_nothing(monkeypatch):
    """An empty result is a real outcome — 0.0 across the board, not a crash."""
    monkeypatch.setattr(runner.retrieval, "search_runs", lambda *a, **k: ([], []))
    scores = run_eval(
        session=None,
        queries=[GoldenQuery("q1", "x", frozenset({("note", "a")}), "")],
        client=None,
        k=8,
    )
    assert scores[0].rr == 0.0
    assert scores[0].recall[8] == 0.0


def test_the_report_names_the_configuration_it_measured(monkeypatch):
    """A results file that does not say which config produced it cannot be
    compared to another one, which is the entire point of the sweep (D46)."""
    from eval.metrics import aggregate, score_query

    scores = [score_query("q1", [("note", "a")], {("note", "a")}, ks=(3, 5, 8))]
    report = render_report(
        scores, aggregate(scores), label="baseline", config={"chunk_max_chars": 1000, "chunk_overfetch": 4}
    )
    assert "chunk_max_chars" in report and "1000" in report
    assert "chunk_overfetch" in report and "4" in report
    assert "q1" in report
    assert "MRR" in report
```

- [x] **Step 2: Run to verify they fail**

```bash
poetry run pytest backend/tests/test_eval_runner.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'eval.runner'`.

- [x] **Step 3: Write the runner**

Create `backend/eval/runner.py`:

```python
"""`make eval` — retrieval quality against a committed golden set (§4).

Deliberately NOT hermetic and deliberately not part of `make check`: it needs a
real VOYAGE_API_KEY (on a cold cache) and Postgres with pgvector, because the
`<=>` similarity operator has no SQLite equivalent. Grades RETRIEVAL only —
precision@k, recall@k, MRR over sources — and never answer quality: an
LLM-judged answer grade would put Claude on both sides of the scoring, which is
the circularity D44 exists to break.

Reads through `retrieval.search_runs`, exactly as POST /agent/chat does, so
what is measured is the production path and not a reimplementation that can
drift from it.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app import retrieval
from app.config import settings
from app.db import SessionLocal
from eval.cache import CachingVoyageClient
from eval.metrics import Aggregate, QueryScore, Source, aggregate, score_query

HERE = Path(__file__).resolve().parent
GOLDEN_SET = HERE / "golden_set.yaml"
CACHE = HERE / ".vector-cache.json"
RESULTS = HERE / "results"

KS: tuple[int, ...] = (3, 5, 8)
"""Reporting cutoffs. Retrieval runs ONCE at settings.retrieval_top_k and these
are three readings of that one ranked list — not three searches (D46)."""


@dataclass(frozen=True)
class GoldenQuery:
    id: str
    query: str
    relevant: frozenset[Source]
    notes: str


def load_golden_set(path: Path = GOLDEN_SET) -> list[GoldenQuery]:
    raw = yaml.safe_load(path.read_text()) or []
    queries: list[GoldenQuery] = []
    seen: set[str] = set()
    for entry in raw:
        qid = entry["id"]
        if qid in seen:
            # paired_mrr_delta pairs by position and id; duplicates make the
            # sweep's comparison ambiguous.
            raise ValueError(f"duplicate golden-set id: {qid}")
        seen.add(qid)
        relevant = frozenset((str(t), str(i)) for t, i in entry.get("relevant") or [])
        if not relevant:
            raise ValueError(f"golden-set entry {qid} labels no relevant sources")
        queries.append(
            GoldenQuery(id=qid, query=entry["query"], relevant=relevant, notes=entry.get("notes", ""))
        )
    return queries


def run_eval(
    session: Any, queries: list[GoldenQuery], *, client: Any, k: int
) -> list[QueryScore]:
    scores: list[QueryScore] = []
    for q in queries:
        hits, _warnings = retrieval.search_runs(session, q.query, k=k, client=client)
        ranked: list[Source] = [(h.source_type, h.source_id) for h in hits]
        scores.append(score_query(q.id, ranked, q.relevant, ks=KS))
    return scores


def validate_golden_set(session: Any, queries: list[GoldenQuery]) -> list[str]:
    """Every labelled source must exist AND be indexed.

    A typo'd id is unreachable, so the query scores 0.0 and looks like a
    retrieval failure. This turns that into a named problem.
    """
    from app.models import ExperimentNoteChunk

    indexed = {
        (row.source_type, row.source_id)
        for row in session.query(
            ExperimentNoteChunk.source_type, ExperimentNoteChunk.source_id
        ).distinct()
    }
    problems: list[str] = []
    for q in queries:
        for source in sorted(q.relevant):
            if source not in indexed:
                problems.append(f"{q.id}: {source[0]}/{source[1]} is not in the index")
    return problems


def render_report(
    scores: list[QueryScore], agg: Aggregate, *, label: str, config: dict[str, Any]
) -> str:
    """A results file that does not name its configuration cannot be compared
    to another one, which is the whole point of the sweep (D46)."""
    lines = [
        f"# Retrieval eval — {label}",
        "",
        "## Configuration",
        "",
        "| Setting | Value |",
        "| --- | --- |",
    ]
    lines += [f"| `{key}` | {value} |" for key, value in sorted(config.items())]
    lines += [
        "",
        "## Aggregate",
        "",
        f"- queries: **{agg.n}**",
        f"- MRR: **{agg.mrr:.3f}**",
    ]
    lines += [f"- precision@{k}: {agg.precision[k]:.3f}" for k in KS]
    lines += [f"- recall@{k}: {agg.recall[k]:.3f}" for k in KS]
    lines += ["", "## Per query", "", "| query | RR | " + " | ".join(f"P@{k}" for k in KS) + " |"]
    lines.append("| --- | --- |" + " --- |" * len(KS))
    for s in scores:
        cells = " | ".join(f"{s.precision[k]:.2f}" for k in KS)
        lines.append(f"| {s.query_id} | {s.rr:.2f} | {cells} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Retrieval eval over the golden set")
    parser.add_argument("--label", default="baseline", help="names the report and its file")
    parser.add_argument("--no-cache", action="store_true", help="ignore the vector cache")
    parser.add_argument("--validate-only", action="store_true", help="check ids, do not search")
    args = parser.parse_args()

    if "sqlite" in settings.database_url:
        # The `<=>` operator has no SQLite equivalent. Failing here names the
        # problem; failing inside the query would name an operator.
        print(
            "error: the eval needs Postgres with pgvector — DATABASE_URL points at SQLite.\n"
            "       run `make db-up` and set DATABASE_URL in .env.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    queries = load_golden_set()
    inner = None
    if not args.no_cache and not settings.voyage_api_key:
        print("warning: VOYAGE_API_KEY is unset; only fully-cached runs will work", file=sys.stderr)

    with SessionLocal() as session:
        problems = validate_golden_set(session, queries)
        if problems:
            print("golden set does not match the index:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            raise SystemExit(1)
        if args.validate_only:
            print(f"golden set is clean: {len(queries)} queries, every labelled source indexed.")
            return

        cache = None if args.no_cache else CachingVoyageClient(CACHE, inner=inner)
        scores = run_eval(session, queries, client=cache, k=settings.retrieval_top_k)

    if cache is not None:
        cache.save()
        print(f"vector cache: {cache.hits} hit(s), {cache.misses} miss(es)")

    agg = aggregate(scores)
    config = {
        "chunk_max_chars": settings.chunk_max_chars,
        "chunk_overfetch": settings.chunk_overfetch,
        "retrieval_top_k": settings.retrieval_top_k,
        "voyage_model": settings.voyage_model,
    }
    report = render_report(scores, agg, label=args.label, config=config)
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{args.label}.md"
    out.write_text(report)
    print(report)
    print(f"written to {out}")


if __name__ == "__main__":
    main()
```

**Note on `inner`:** it is left `None` so that a cold cache raises the `CachingVoyageClient`'s explicit "no inner client" error rather than failing deep in the SDK. Task 7 wires the real client in once the first live run is needed — see its Step 2.

- [x] **Step 4: Run to verify they pass**

```bash
poetry run pytest backend/tests/test_eval_runner.py -v
```

Expected: PASS, 7 tests.

- [x] **Step 5: Make `make eval` real**

Replace `Makefile:33-34`:

```make
eval:
	poetry run python -m eval.runner $(ARGS)
```

- [x] **Step 6: Author the golden set**

Following the D44 procedure at the top of this task, write `backend/eval/golden_set.yaml` with ~20 queries across the four shapes. Use the real ids from `backend/eval/curation.yaml` and the psql/API output above — **and do not open a single note's text while writing the query strings.**

- [x] **Step 7: Validate it against the index**

```bash
make eval ARGS=--validate-only
```

Expected: `golden set is clean: 20 queries, every labelled source indexed.` Fix any reported id before continuing — an unreachable id scores 0.0 and reads as a retrieval failure.

- [x] **Step 8: Run the gate and commit**

```bash
make check
git add backend/eval/runner.py backend/eval/golden_set.yaml backend/tests/test_eval_runner.py Makefile
git commit -m "$(cat <<'EOF'
feat: make eval — retrieval quality over a committed golden set (4.2)

Reads through retrieval.search_runs exactly as /agent/chat does, so what
is measured is the production path rather than a reimplementation.

Grades retrieval only. An LLM-judged answer grade would put Claude on
both sides of the scoring, which is the circularity D44 exists to break.

Queries are blind-drafted from the leaderboard, params and metrics — never
from note prose — and the rule binds whoever extends the set: a half-blind,
half-derived set reports one number over two incomparable halves.

Replaces the Makefile stub. CLAUDE.md's description of a Project 1
prose-keyword grader is now wrong and is corrected in this commit.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

- [x] **Step 9: Correct CLAUDE.md in this same commit**

Before committing Step 8, rewrite the **`make eval` — the LLM eval suite (D6)** paragraph in `CLAUDE.md`. It currently describes grading tool selection, columns passed and keyword presence over chart questions — a Project 1 suite that was never built, and actively wrong once this task lands. Replace it with: what `make eval` now measures (precision@k / recall@k / MRR over `(source_type, source_id)`), why it is separate from `make test` (real Voyage, real Postgres with pgvector), and D43/D44. Amend the commit if you have already made it.

---

## Task 7: The baseline run

Operational, and the first task whose deliverable is a measurement rather than
code. It produces the number every later configuration is compared against, so
it has to be reproducible before the sweep starts moving parts.

**Files:**
- Modify: `backend/eval/runner.py` (wire the real Voyage client behind the cache)
- Create: `backend/eval/results/baseline.md` (generated, committed)
- Create: `backend/eval/.vector-cache.json` (generated, **git-ignored** — Task 3 added the rule)

**Interfaces:**
- Consumes: `eval.runner.main` (Task 6), `app.embeddings._default_client` (existing), the reconciled index (Task 5).
- Produces: `backend/eval/results/baseline.md` — the reference report for Task 8's comparison.

- [x] **Step 1: Give the cache a real client to miss into**

Task 6 left `inner = None` deliberately, so a cold cache fails with the shim's
own named error rather than deep inside the SDK. Wire the real one now, in
`runner.main`, replacing the `inner = None` line and the warning below it:

```python
    inner = None
    if not args.no_cache and not settings.voyage_api_key:
        print("warning: VOYAGE_API_KEY is unset; only fully-cached runs will work", file=sys.stderr)
    elif settings.voyage_api_key:
        from app import embeddings

        inner = embeddings._default_client()
```

`_default_client()` is reached through the module rather than imported at the
top, matching how `app.embeddings` itself defers the `voyageai` import — a
missing package fails at call time, not at app startup.

- [x] **Step 2: Confirm the tests still pass**

```bash
poetry run pytest backend/tests/test_eval_runner.py -v
```

Expected: PASS, 7 tests. They monkeypatch `search_runs`, so none of them reach
this branch — which is the point of checking rather than assuming.

- [x] **Step 3: Bring up the services**

```bash
make db-up
grep -E '^(DATABASE_URL|VOYAGE_API_KEY|MLFLOW)' .env
```

`DATABASE_URL` must be the Postgres one. If it points at SQLite the runner exits
with the named error from Task 6 rather than a pgvector operator failure.

- [x] **Step 4: Validate, then run**

```bash
make eval ARGS=--validate-only
make eval ARGS="--label baseline"
```

The first run is a cold cache: 20 query embeddings, one request each, at Voyage's
free-tier **3 requests/minute** — roughly **7 minutes**, with the retry backoff in
`embed_texts` absorbing the 429s. It is the only slow run; every later one reuses
these vectors, because a query's text and `input_type` do not change between
configurations.

- [x] **Step 5: Read the numbers before recording them**

Do not skip to committing. Check three things:

1. **MRR is not 1.000.** A perfect score over 20 queries means the queries are
   restatements of their own answers — the exact failure D44's blind-authorship
   rule exists to prevent. If it happens, the set needs rewriting, not the
   retrieval.
2. **No query scored 0.0 across every cutoff.** `--validate-only` already proved
   the labelled sources are indexed, so a total miss is either a genuinely bad
   query or a real retrieval failure. Open that one query, run it through
   `POST /agent/chat`, and find out which — the answer belongs in the report.
3. **`recall@8 ≥ recall@5 ≥ recall@3`.** These are three readings of one ranked
   list; recall that falls as k grows means the truncation is wrong, in
   `metrics.py` and not in the retrieval.

- [x] **Step 6: Append what you learned**

Add a short `## Notes` section to `backend/eval/results/baseline.md` by hand:
the weakest query and why, and any query shape (of the four in Task 6) that
scores systematically worse. A results file with no reading of it is a number
nobody can act on.

- [x] **Step 7: Commit**

```bash
git status --short backend/eval/    # .vector-cache.json must NOT appear
git add backend/eval/runner.py backend/eval/results/baseline.md
git commit -m "$(cat <<'EOF'
chore: baseline retrieval eval over the 20-query golden set (4.2)

The reference measurement every Task 8 configuration is compared against.
Wires the real Voyage client behind the cache shim; the cold run costs 20
query embeddings at the free tier's 3 RPM and every later run reuses them,
since a query's text and input_type do not change between configurations.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

Verify the cache file is untracked before committing — it holds ~20 float
vectors of 512 dimensions and would grow with every sweep configuration.

---

## Task 8: The pre-registered sweep (D46)

**Files:**
- Create: `scripts/sweep_retrieval.py`, `backend/eval/results/sweep.md`
- Test: `backend/tests/test_sweep.py`

**Interfaces:**
- Consumes: `eval.runner.load_golden_set`, `eval.runner.run_eval`, `eval.runner.KS`; `eval.metrics.aggregate`, `eval.metrics.paired_mrr_delta`; `eval.cache.CachingVoyageClient`; `app.embeddings.backfill`.
- Produces:
  - `GRID: tuple[tuple[int, int], ...]` — the nine `(chunk_max_chars, chunk_overfetch)` pairs, **committed before any of them is run**
  - `SweepRow` frozen dataclass: `chunk_max_chars: int`, `chunk_overfetch: int`, `mrr: float`, `delta: float`, `stderr: float`, `adopt: bool`
  - `adoption_verdict(delta: float, stderr: float) -> bool`
  - `render_sweep(rows: list[SweepRow], baseline_mrr: float) -> str`

### Why the grid is written down first

Nine configurations scored on twenty queries, with the winner picked afterwards,
finds a winner from pure noise essentially every time — there is always a highest
number. The grid, the metric, and the adoption rule are therefore fixed in this
task's first commit, **before any configuration is measured**.

The adoption rule mirrors the codebase's own D38 "within noise" convention:

> Adopt a configuration only if its **paired** MRR delta against the baseline
> exceeds **two standard errors**. Otherwise keep the baseline.

Paired, not unpaired: the same twenty queries score both configurations, so the
per-query difference cancels the (large) variation in how hard the queries are.
An unpaired comparison of two means over twenty queries has a standard error
wide enough to swallow every effect this grid can produce.

The grid — the two parameters retrieval quality actually turns on:

| | `chunk_overfetch` 2 | 4 | 8 |
| --- | --- | --- | --- |
| **`chunk_max_chars` 600** | | | |
| **1000** | | baseline | |
| **1500** | | | |

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_sweep.py`:

```python
"""The adoption rule and the report. The sweep's IO — re-indexing and
searching — is not tested here; what must not be allowed to drift is the rule
that decides whether a difference is real."""

import pytest

from sweep_retrieval import GRID, SweepRow, adoption_verdict, render_sweep


def test_the_grid_is_the_nine_pre_registered_configurations():
    """Pinned so the grid cannot quietly grow after the results are in —
    adding a tenth configuration post hoc is exactly the fishing D46 forbids."""
    assert len(GRID) == 9
    assert set(GRID) == {
        (chars, over) for chars in (600, 1000, 1500) for over in (2, 4, 8)
    }
    assert (1000, 4) in GRID  # the baseline must be measured alongside the rest


def test_a_difference_inside_two_standard_errors_is_not_adopted():
    assert adoption_verdict(delta=0.04, stderr=0.03) is False


def test_a_difference_beyond_two_standard_errors_is_adopted():
    assert adoption_verdict(delta=0.10, stderr=0.03) is True


def test_a_difference_exactly_at_two_standard_errors_is_not_adopted():
    """Strictly greater. The boundary goes to the incumbent — a tie is not
    evidence for changing a shipped default."""
    assert adoption_verdict(delta=0.06, stderr=0.03) is False


def test_a_worse_configuration_is_never_adopted():
    assert adoption_verdict(delta=-0.20, stderr=0.01) is False


def test_an_infinite_standard_error_is_never_adopted():
    """paired_mrr_delta returns inf for n < 2 — an unmeasurable difference
    must not read as a significant one."""
    assert adoption_verdict(delta=0.5, stderr=float("inf")) is False


def test_the_report_states_the_adoption_rule_and_the_outcome():
    rows = [
        SweepRow(1000, 4, mrr=0.62, delta=0.0, stderr=0.0, adopt=False),
        SweepRow(600, 8, mrr=0.71, delta=0.09, stderr=0.03, adopt=True),
    ]
    report = render_sweep(rows, baseline_mrr=0.62)
    assert "two standard errors" in report
    assert "0.09" in report and "0.03" in report
    assert "600" in report


def test_the_report_says_so_when_nothing_clears_the_bar():
    """The likeliest outcome, and the one a reader most needs stated plainly —
    silence would read as an unfinished sweep."""
    rows = [SweepRow(600, 2, mrr=0.64, delta=0.02, stderr=0.04, adopt=False)]
    report = render_sweep(rows, baseline_mrr=0.62)
    assert "no configuration" in report.lower()
```

- [x] **Step 2: Run to verify they fail**

```bash
poetry run pytest backend/tests/test_sweep.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'sweep_retrieval'`.
(`pyproject.toml` puts `scripts` on `pythonpath`, so the import is bare.)

- [x] **Step 3: Write the sweep script**

Create `scripts/sweep_retrieval.py`:

```python
"""The pre-registered retrieval sweep (§5, D46).

The grid, the metric and the adoption rule are fixed in this file's first
commit, BEFORE any configuration is measured. Nine configurations scored on
twenty queries with the winner chosen afterwards finds a winner from noise
essentially every time — there is always a highest number.

chunk_overfetch changes nothing about the index, so all three of its values are
measured against one re-index. chunk_max_chars does change it: each of its three
values costs a full `make embed` cycle, one Voyage request per changed source at
the free tier's 3 RPM.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from app.config import settings
from app.db import SessionLocal
from app.embeddings import backfill
from eval.cache import CachingVoyageClient
from eval.metrics import aggregate, paired_mrr_delta
from eval.runner import CACHE, RESULTS, load_golden_set, run_eval

GRID: tuple[tuple[int, int], ...] = tuple(
    (chars, over) for chars in (600, 1000, 1500) for over in (2, 4, 8)
)
"""(chunk_max_chars, chunk_overfetch). Pre-registered — see the module docstring."""

BASELINE: tuple[int, int] = (1000, 4)
ADOPTION_SIGMA = 2.0


@dataclass(frozen=True)
class SweepRow:
    chunk_max_chars: int
    chunk_overfetch: int
    mrr: float
    delta: float
    stderr: float
    adopt: bool


def adoption_verdict(delta: float, stderr: float) -> bool:
    """Strictly greater than two standard errors. The boundary goes to the
    incumbent: a tie is not evidence for changing a shipped default (D38)."""
    if stderr == float("inf"):
        return False
    return delta > ADOPTION_SIGMA * stderr


def render_sweep(rows: list[SweepRow], baseline_mrr: float) -> str:
    lines = [
        "# Retrieval sweep — pre-registered grid (D46)",
        "",
        "The grid, the metric and the adoption rule were committed before any",
        "configuration was measured. A configuration is adopted only if its",
        "**paired** MRR delta against the baseline exceeds **two standard errors**;",
        "otherwise the baseline stands.",
        "",
        f"Baseline: `chunk_max_chars={BASELINE[0]}`, `chunk_overfetch={BASELINE[1]}`, "
        f"MRR **{baseline_mrr:.3f}**.",
        "",
        "| chunk_max_chars | chunk_overfetch | MRR | Δ MRR | std. err. | adopt? |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row.chunk_max_chars} | {row.chunk_overfetch} | {row.mrr:.3f} | "
            f"{row.delta:+.3f} | {row.stderr:.3f} | {'**yes**' if row.adopt else 'no'} |"
        )
    lines.append("")
    winners = [r for r in rows if r.adopt]
    if winners:
        best = max(winners, key=lambda r: r.delta)
        lines.append(
            f"**Adopted:** `chunk_max_chars={best.chunk_max_chars}`, "
            f"`chunk_overfetch={best.chunk_overfetch}` "
            f"({best.delta:+.3f} ± {best.stderr:.3f})."
        )
    else:
        lines.append(
            "**No configuration cleared the bar.** The baseline stands. This is the "
            "likeliest outcome at n=20 and is a result, not a failed sweep: it says the "
            "defaults are not detectably wrong at this corpus size, and it is the honest "
            "alternative to shipping the highest number in the table."
        )
    return "\n".join(lines) + "\n"


def _reindex(chunk_max_chars: int, client: object) -> None:
    """Re-chunk and re-embed at a new size.

    backfill()'s skip check is `current == chunk_text(source.text)`, which
    re-chunks with the CURRENT parameters — so a chunk-size change is correctly
    seen as an edit and every source is re-indexed. Nothing extra is needed here.
    """
    settings.chunk_max_chars = chunk_max_chars
    with SessionLocal() as session:
        report = backfill(session, client=client)
        session.commit()
    print(f"  reindexed at {chunk_max_chars}: {report}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-registered retrieval sweep")
    parser.add_argument("--dry-run", action="store_true", help="print the grid and exit")
    args = parser.parse_args()

    if args.dry_run:
        for chars, over in GRID:
            print(f"chunk_max_chars={chars} chunk_overfetch={over}")
        return
    if "sqlite" in settings.database_url:
        print("error: the sweep needs Postgres with pgvector.", file=sys.stderr)
        raise SystemExit(1)

    from app import embeddings

    cache = CachingVoyageClient(CACHE, inner=embeddings._default_client())
    queries = load_golden_set()
    by_config: dict[tuple[int, int], list] = {}

    # Grouped by chunk size so each re-index is paid once, not once per overfetch.
    for chars in sorted({c for c, _ in GRID}):
        _reindex(chars, cache)
        for over in sorted({o for c, o in GRID if c == chars}):
            settings.chunk_overfetch = over
            with SessionLocal() as session:
                by_config[(chars, over)] = run_eval(
                    session, queries, client=cache, k=settings.retrieval_top_k
                )
            print(f"  scored ({chars}, {over})", file=sys.stderr)
    cache.save()

    base_scores = by_config[BASELINE]
    rows: list[SweepRow] = []
    for config in GRID:
        scores = by_config[config]
        # (baseline, challenger) — reversing these inverts every delta in
        # the table, and the sign is the only thing the adoption rule reads.
        delta, stderr = paired_mrr_delta(base_scores, scores)
        rows.append(
            SweepRow(
                chunk_max_chars=config[0],
                chunk_overfetch=config[1],
                mrr=aggregate(scores).mrr,
                delta=delta,
                stderr=stderr,
                adopt=config != BASELINE and adoption_verdict(delta, stderr),
            )
        )

    report = render_sweep(rows, baseline_mrr=aggregate(base_scores).mrr)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "sweep.md").write_text(report)
    print(report)

    # Leave the index at whatever the adopted configuration is — a store left at
    # 1500 while settings say 1000 is an index that silently disagrees with the code.
    adopted = next((r for r in rows if r.adopt), None)
    final = (adopted.chunk_max_chars, adopted.chunk_overfetch) if adopted else BASELINE
    _reindex(final[0], cache)
    cache.save()
    print(f"index restored to chunk_max_chars={final[0]}", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [x] **Step 4: Run to verify they pass**

```bash
poetry run pytest backend/tests/test_sweep.py -v
poetry run python scripts/sweep_retrieval.py --dry-run
```

Expected: 7 tests PASS; the dry run prints nine lines.

- [x] **Step 5: Commit the grid BEFORE measuring it**

This commit is what makes the registration real. It must land before Step 6 runs.

```bash
make check
git add scripts/sweep_retrieval.py backend/tests/test_sweep.py
git commit -m "$(cat <<'EOF'
feat: pre-register the retrieval sweep grid and adoption rule (4.3)

Nine configurations scored on twenty queries with the winner picked
afterwards finds a winner from noise essentially every time — there is
always a highest number. The grid, the metric and the rule are therefore
committed here, before any configuration is measured.

Adoption requires a paired MRR delta beyond two standard errors, mirroring
D38's "within noise" convention. Paired because the same twenty queries
score both sides, which cancels the large variation in query difficulty.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

- [x] **Step 6: Run the sweep**

```bash
poetry run python scripts/sweep_retrieval.py
```

Budget roughly **35 minutes**, almost all of it Voyage rate limiting: four
re-index cycles (600, 1000, 1500, then back to the adopted size) at ~23 requests
each, 3 requests/minute. The twenty query vectors are served from the cache
throughout — they are identical across configurations — so the searches
themselves are fast.

If it dies partway, re-running is safe: the cache makes completed embeddings
free, and `backfill` is a reconciliation, so a half-finished re-index converges
on the next pass.

- [x] **Step 7: Verify the index matches the settings**

```bash
make db-psql -- -c "select count(*), avg(length(chunk_text))::int from app.experiment_note_chunks;"
grep -n 'chunk_max_chars\|chunk_overfetch' backend/app/config.py .env
```

If a configuration was adopted, update the defaults in `backend/app/config.py`
to match and re-run `make eval ARGS="--label adopted"`. If none was — the
likeliest outcome — change nothing. The index must sit at whatever
`chunk_max_chars` the config file states; a store re-chunked at 1500 while the
code says 1000 disagrees with itself, and the next `make embed` would silently
rewrite the whole index.

- [x] **Step 8: Commit the results**

```bash
git add backend/eval/results/sweep.md backend/app/config.py
git commit -m "$(cat <<'EOF'
chore: retrieval sweep results over the pre-registered grid (4.3)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Extract `app/leaderboard.py`

Pure refactor, no behaviour change. Task 10's agent tool needs the ranked
leaderboard, and the only place that knowledge currently lives is inside a
FastAPI route handler — 53 lines of it, ending in `HTTPException`. Calling a
route handler from `agent._execute` would drag `HTTPException` into the tool
layer, where a 404 raised at the model is not an HTTP concern at all.

**Files:**
- Create: `backend/app/leaderboard.py`
- Modify: `backend/app/routes/experiments.py:511-573` (the `GET /{experiment_id}/runs` handler)
- Test: `backend/tests/test_leaderboard.py`

**Interfaces:**
- Consumes: `app.ranking.rank_runs`, `app.routes.shared.merge_runs`, `app.schemas.LeaderboardOut` / `LeaderboardRowOut`, `app.models.Experiment` / `Run`, `app.tracing.span`.
- Produces:
  - `class ExperimentNotFound(LookupError)` — carries the id in `args[0]`
  - `build_leaderboard(session: Session, experiment_id: str, *, limit: int | None = None) -> LeaderboardOut`

### Why `LookupError` and not `KeyError`

`agent._execute` already has `except KeyError` for an unknown `run_id`. If
`build_leaderboard` raised `KeyError` for an unknown experiment, that handler
would swallow it and report `No run with id …` for something that is not a run —
a wrong message with nothing about it looking wrong. `LookupError` is
`KeyError`'s **parent**, so `except KeyError` cannot catch it, and Task 10 adds
its own handler.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_leaderboard.py`:

```python
"""The extraction's contract. The ranking arithmetic is already pinned in
test_ranking.py and the merge in test_runs_route.py; what is new here is that
the function is callable without FastAPI and signals a missing experiment with
a type agent._execute cannot mistake for a missing run."""

import pytest

from app.leaderboard import ExperimentNotFound, build_leaderboard


def test_an_unknown_experiment_raises_experiment_not_found(session):
    with pytest.raises(ExperimentNotFound) as excinfo:
        build_leaderboard(session, "no-such-experiment")
    assert excinfo.value.args[0] == "no-such-experiment"


def test_experiment_not_found_is_not_a_key_error():
    """agent._execute catches KeyError for an unknown run_id. If this were a
    KeyError, a missing EXPERIMENT would be reported as a missing RUN."""
    assert issubclass(ExperimentNotFound, LookupError)
    assert not issubclass(ExperimentNotFound, KeyError)


def test_it_returns_the_ranked_rows(session, seeded_experiment):
    """LeaderboardOut carries rows/primary_metric/metric_direction/ranked/
    mlflow_available — and deliberately no experiment_id. It is a shipped API
    response, and widening it for a tool's convenience would change the
    frontend contract for no frontend reason."""
    board = build_leaderboard(session, seeded_experiment.id)
    assert board.primary_metric == seeded_experiment.primary_metric
    assert [row.rank for row in board.rows] == list(range(1, len(board.rows) + 1))


def test_limit_truncates_without_renumbering(session, seeded_experiment):
    """Ranks are over the whole investigation (D38). A truncated view whose top
    row claimed rank 1 would be a lie about a different denominator — the same
    property #51 pins for the frontend's model filter."""
    full = build_leaderboard(session, seeded_experiment.id)
    limited = build_leaderboard(session, seeded_experiment.id, limit=2)
    assert len(limited.rows) == 2
    assert [row.rank for row in limited.rows] == [row.rank for row in full.rows[:2]]


def test_the_route_still_answers_identically(client, seeded_experiment):
    """The refactor's whole claim. If this drifts, the extraction changed
    behaviour."""
    response = client.get(f"/experiments/{seeded_experiment.id}/runs")
    assert response.status_code == 200
    assert response.json()["rows"][0]["rank"] == 1


def test_the_route_still_404s_for_an_unknown_experiment(client):
    assert client.get("/experiments/nope/runs").status_code == 404
```

**On the fixtures:** `client` exists in `backend/tests/conftest.py` already. If
`session` and `seeded_experiment` do not, add them to `conftest.py` in this
step — `session` yielding the same isolated SQLite session `client` overrides
`get_session` with, and `seeded_experiment` creating one `Experiment` with three
`Run` rows carrying distinct `metrics` values. Do not invent a second database
fixture; reuse the `tmp_path` wiring `client` already uses, or the two halves of
these tests will be looking at different data.

- [x] **Step 2: Run to verify they fail**

```bash
poetry run pytest backend/tests/test_leaderboard.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.leaderboard'`.

- [x] **Step 3: Move the handler body into the new module**

Create `backend/app/leaderboard.py` holding the ranked-leaderboard logic
currently in `routes/experiments.py:511-573`. Move it **verbatim** apart from
three changes:

1. The signature becomes
   `def build_leaderboard(session: Session, experiment_id: str, *, limit: int | None = None) -> LeaderboardOut:`
2. `raise HTTPException(status_code=404, …)` becomes `raise ExperimentNotFound(experiment_id)`
   (replacing the `_require_experiment` call, which is a route helper and stays put).
3. Wrap the body in a span, so the new tool traces like the retrieval ones do:

```python
class ExperimentNotFound(LookupError):
    """Raised when no experiment answers to an id.

    LookupError, deliberately not KeyError: agent._execute catches KeyError for
    an unknown run_id, and a missing experiment reported as a missing run is a
    wrong message with nothing about it looking wrong.
    """


def build_leaderboard(
    session: Session, experiment_id: str, *, limit: int | None = None
) -> LeaderboardOut:
    """One investigation's runs, ranked by its primary metric (D38).

    Extracted from GET /experiments/{id}/runs so the agent's get_leaderboard
    tool can reach it without importing HTTPException into the tool layer.
    """
    with span("leaderboard.build", experiment_id=experiment_id, limit=limit) as board_span:
        experiment = session.get(Experiment, experiment_id)
        if experiment is None:
            raise ExperimentNotFound(experiment_id)
        # >>> the body of routes/experiments.py:511-573, moved verbatim: the
        # ranking via rank_runs, the merge via merge_runs, and the assembly
        # of `rows`. Nothing in it changes. <<<
        if limit is not None:
            # Truncate AFTER ranking. The ranks are over the whole
            # investigation (D38); renumbering a truncated view would report a
            # different denominator as the same one.
            rows = rows[:limit]
        board_span.set_attribute("rows", len(rows))
        return LeaderboardOut(...)  # the same construction the route already builds
```

`span()` drops `None`-valued attributes, so `limit=None` is handled without a
sentinel (3.1).

- [x] **Step 4: Make the route call it**

Replace the handler body in `routes/experiments.py` with the translation only.
**Keep the handler named `leaderboard`** — renaming it to `get_leaderboard`
would collide with Task 10's tool name and make `grep get_leaderboard` return
two unrelated things.

```python
@router.get("/{experiment_id}/runs", response_model=LeaderboardOut)
def leaderboard(experiment_id: str, session: Session = Depends(get_session)) -> LeaderboardOut:
    try:
        return build_leaderboard(session, experiment_id)
    except ExperimentNotFound:
        raise HTTPException(status_code=404, detail="Experiment not found") from None
```

Remove any imports in `routes/experiments.py` left unused by the move (`rank_runs`
in particular, if nothing else there uses it) — ruff's `F401` will name them.

- [x] **Step 5: Run the full suite, not just the new file**

```bash
poetry run pytest backend/tests/test_leaderboard.py backend/tests/test_experiments_route.py -v
make check
```

Expected: PASS. The existing route tests are the real check here — this task
claims no behaviour changed, and they are what makes the claim falsifiable.

- [x] **Step 6: Commit**

```bash
git add backend/app/leaderboard.py backend/app/routes/experiments.py backend/tests/test_leaderboard.py backend/tests/conftest.py
git commit -m "$(cat <<'EOF'
refactor: extract build_leaderboard out of the route (4.4)

Task 10's agent tool needs the ranked leaderboard, and it lived inside a
FastAPI handler ending in HTTPException. Calling that from agent._execute
would drag HTTP status codes into the tool layer, where a 404 raised at a
model is not an HTTP concern.

ExperimentNotFound subclasses LookupError, not KeyError: _execute already
catches KeyError for an unknown run_id, and a missing experiment reported
as a missing run is a wrong message with nothing about it looking wrong.

No behaviour change — the existing route tests are what makes that claim
falsifiable.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: The `get_leaderboard` tool (D47)

**Files:**
- Modify: `backend/app/agent.py` (`TOOLS`, `validate_tool_call`, `_execute`, a renderer), `backend/app/config.py`
- Test: `backend/tests/test_agent_leaderboard.py`

**Interfaces:**
- Consumes: `app.leaderboard.build_leaderboard`, `app.leaderboard.ExperimentNotFound` (Task 9); `app.schemas.LeaderboardOut`.
- Produces:
  - `Settings.agent_max_leaderboard_rows: int = 20`
  - `_render_leaderboard(board: LeaderboardOut, experiment_id: str) -> str`
  - a third entry in `TOOLS`, named `get_leaderboard`

### Why a third tool rather than a better prompt

"Recommend what to try next" is a ranking question, and the two existing tools
cannot answer it. `search_runs` returns reviewed *prose*, and `get_run_detail`
returns *one* run. Asking the model to recommend from those means asking it to
reconstruct an ordering from snippets — which it will do, fluently, and
sometimes wrongly, because the numbers it needs were never in its context. The
ranking already exists, computed by `rank_runs` against the holdout metric with
`cv_std` beside it (D38). Handing the model the actual ordering is the
difference between a recommendation grounded in the leaderboard and one that
merely sounds like it.

**The name is `get_leaderboard`, matching the concept the UI already uses.** Not
`recommend_next` — a tool that returns rows must not be named for the conclusion
the model is supposed to draw from them, or the model treats its output as the
recommendation rather than as evidence for one.

- [x] **Step 1: Add the bound to settings**

In `backend/app/config.py`, beside `agent_max_k`:

```python
    agent_max_leaderboard_rows: int = 20
    """Ceiling on the rows get_leaderboard will return.

    Rejected, not clamped — same rule as agent_max_k: answering a request for
    500 rows with 20 tells the model the investigation holds 20, and it then
    reports that.
    """
```

Add `AGENT_MAX_LEADERBOARD_ROWS=20` to `.env.example` under the agent settings.

- [x] **Step 2: Write the failing tests**

Create `backend/tests/test_agent_leaderboard.py`:

```python
"""The third tool. Offline — build_leaderboard is monkeypatched, so no
Postgres and no Anthropic."""

import pytest

from app import agent
from app.agent import TOOLS, validate_tool_call
from app.config import settings
from app.leaderboard import ExperimentNotFound


def test_the_tool_is_registered_and_named_for_what_it_returns():
    """Not `recommend_next`: a tool returning rows must not be named for the
    conclusion, or the model treats its output as the recommendation."""
    names = [tool["name"] for tool in TOOLS]
    assert "get_leaderboard" in names
    assert "recommend_next" not in names


def test_experiment_id_is_required():
    assert validate_tool_call("get_leaderboard", {}) is not None
    assert validate_tool_call("get_leaderboard", {"experiment_id": "e1"}) is None


def test_a_row_count_over_the_ceiling_is_rejected_not_clamped():
    """Answering 500 with 20 tells the model the investigation holds 20."""
    error = validate_tool_call("get_leaderboard", {"experiment_id": "e1", "limit": 500})
    assert error is not None
    assert str(settings.agent_max_leaderboard_rows) in error


def test_a_zero_or_negative_limit_is_rejected():
    assert validate_tool_call("get_leaderboard", {"experiment_id": "e1", "limit": 0}) is not None
    assert validate_tool_call("get_leaderboard", {"experiment_id": "e1", "limit": -3}) is not None


def test_an_unknown_experiment_comes_back_as_a_tool_result(monkeypatch):
    """_execute never raises (3.5). The model must be able to correct the id."""

    def _raise(session, experiment_id, **kw):
        raise ExperimentNotFound(experiment_id)

    monkeypatch.setattr(agent, "build_leaderboard", _raise)
    text, hits, warnings, error, summary = agent._execute(
        "get_leaderboard", {"experiment_id": "nope"}, session=None
    )
    assert error is not None
    assert "nope" in text
    assert "run" not in text.lower().split("experiment")[0]  # not reported as a missing RUN
    assert hits == []


def test_the_rendered_rows_carry_the_noise_band(monkeypatch, fake_board):
    """D38: a win smaller than the leader's cv_std is within noise. Without the
    band in the tool result the model cannot tell a real lead from a tied one,
    and it will call every lead real."""
    monkeypatch.setattr(agent, "build_leaderboard", lambda *a, **k: fake_board)
    text, _hits, _warnings, error, summary = agent._execute(
        "get_leaderboard", {"experiment_id": "e1"}, session=None
    )
    assert error is None
    assert "cv_std" in text
    assert "rank" in text.lower()
    # within_noise comes from the backend's own D38 judgment, not a
    # re-derivation — two surfaces must not disagree about the same runs.
    assert "within noise" in text


def test_an_absent_cv_std_renders_as_unquantified_never_zero(monkeypatch, fake_board_no_band):
    """D32. A fabricated zero band makes every difference look significant."""
    monkeypatch.setattr(agent, "build_leaderboard", lambda *a, **k: fake_board_no_band)
    text, *_ = agent._execute("get_leaderboard", {"experiment_id": "e1"}, session=None)
    assert "unquantified" in text
    assert "±0.0" not in text and "± 0.0" not in text


def test_an_unreachable_tracking_store_still_returns_rows(monkeypatch, fake_board_no_mlflow):
    """merge_runs degrades to mlflow_available=False rather than raising, and
    that must survive the extraction: the ranking is ours, in Postgres. The
    tool result has to SAY the metrics are missing, though — rows with blank
    values and no explanation read as runs that scored nothing."""
    monkeypatch.setattr(agent, "build_leaderboard", lambda *a, **k: fake_board_no_mlflow)
    text, _hits, _warnings, error, _summary = agent._execute(
        "get_leaderboard", {"experiment_id": "e1"}, session=None
    )
    assert error is None
    assert "mlflow_available=False" in text


def test_the_step_summary_carries_no_row_text(monkeypatch, fake_board):
    """AgentStep carries counts, ids and durations — never retrieved content."""
    monkeypatch.setattr(agent, "build_leaderboard", lambda *a, **k: fake_board)
    _text, _hits, _warnings, _error, summary = agent._execute(
        "get_leaderboard", {"experiment_id": "e1"}, session=None
    )
    assert "row" in summary
    assert fake_board.rows[0].run.model_type not in summary or len(summary) < 60
```

Add `fake_board`, `fake_board_no_band` and `fake_board_no_mlflow` fixtures to
this file: a
`LeaderboardOut` with three `LeaderboardRowOut`s carrying ranks 1–3, distinct
`value`s, each wrapping a real `RunDetailOut` (whose `model_type` differs per
row); `cv_std` set and `within_noise` true on one row of the first fixture,
`cv_std=None` throughout the second, and `mlflow_available=False` with
`value=None`/`cv_value=None` on the third. Build them from the real schema classes — a stand-in with the
same attribute names would let a field rename pass this file and break the tool.

- [x] **Step 3: Run to verify they fail**

```bash
poetry run pytest backend/tests/test_agent_leaderboard.py -v
```

Expected: FAIL — `get_leaderboard` is not in `TOOLS`.

- [x] **Step 4: Add the tool schema**

Append to `TOOLS` in `backend/app/agent.py`:

```python
    {
        "name": "get_leaderboard",
        "description": (
            "One investigation's runs, ranked by its primary metric on the holdout, "
            "with each run's cross-validation band beside it. Use this to compare "
            "what has been tried and to ground a recommendation about what to try "
            "next — it returns the ordering the app itself computed, not an "
            "impression assembled from snippets. Takes the experiment_id returned "
            "by search_runs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "experiment_id": {
                    "type": "string",
                    "description": "The investigation's id.",
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        "How many top-ranked rows to return. Defaults to all of them, "
                        f"maximum {settings.agent_max_leaderboard_rows}."
                    ),
                },
            },
            "required": ["experiment_id"],
        },
    },
```

The import-time `_TYPES` completeness guard already covers this — both property
types are `string` and `integer`, both mapped.

- [x] **Step 5: Bound `limit` in `validate_tool_call`**

Beside the existing `k` bound, after the type loop:

```python
    limit = args.get("limit")
    if isinstance(limit, int) and not isinstance(limit, bool):
        if limit < 1 or limit > settings.agent_max_leaderboard_rows:
            return (
                f"{name}: limit must be between 1 and "
                f"{settings.agent_max_leaderboard_rows}, got {limit}."
            )
```

Rejected rather than clamped, for the reason in Step 1's docstring.

- [x] **Step 6: Add the renderer and the `_execute` branch**

```python
def _render_leaderboard(board: LeaderboardOut, experiment_id: str) -> str:
    """The tool result the MODEL sees.

    `experiment_id` is a parameter because LeaderboardOut does not carry one —
    the caller already knows the id it asked for, and widening a shipped API
    response for a tool's convenience would change the frontend contract for no
    frontend reason.

    A LeaderboardRowOut nests its run: `row.run.id`, `row.run.model_type`. The
    rank-level fields are `rank`, `value`, `cv_value`, `cv_std`, `is_best` and
    `within_noise`.

    `within_noise` is rendered rather than re-derived from cv_std. The backend
    already made that D38 judgment, over the whole investigation; a tool that
    recomputes it from the raw numbers can disagree with the leaderboard the
    user is looking at, and then two surfaces state different things about the
    same runs. cv_std is included too, and a `None` renders as "unquantified",
    never as 0.0 (D32) — a fabricated zero band makes every difference look
    significant.
    """
    if not board.rows:
        return f"Investigation {experiment_id} has no ranked runs yet."
    header = (
        f"Investigation {experiment_id}, ranked by {board.primary_metric} "
        f"({board.metric_direction}). ranked={board.ranked} "
        f"mlflow_available={board.mlflow_available}"
    )
    lines = [
        f"rank={row.rank} run_id={row.run.id} model={row.run.model_type} "
        f"{board.primary_metric}={row.value} cv={row.cv_value} "
        f"cv_std={'unquantified' if row.cv_std is None else row.cv_std}"
        + (" [best]" if row.is_best else "")
        + (" [within noise of the leader]" if row.within_noise else "")
        for row in board.rows
    ]
    return header + "\n" + "\n".join(lines)
```

In `_execute`, add the branch inside the existing `try`, and an
`except ExperimentNotFound` **before** the `except KeyError`:

```python
        if name == "get_leaderboard":
            board = build_leaderboard(session, args["experiment_id"], limit=args.get("limit"))
            return (
                _render_leaderboard(board, args["experiment_id"]),
                [],
                [],
                None,
                f"{len(board.rows)} row(s)",
            )
```

```python
    except ExperimentNotFound as exc:
        # Before `except KeyError`, and a distinct message: reporting a missing
        # experiment as a missing run gives the model a correction it cannot make.
        message = f"No experiment with id {exc.args[0]!r}."
        return message, [], [], message, "not found"
```

Import `build_leaderboard`, `ExperimentNotFound` and `LeaderboardOut` at the top
of `agent.py`. Import `build_leaderboard` as a module-level name (not
`leaderboard.build_leaderboard`) so the tests' `monkeypatch.setattr(agent, ...)`
binds the symbol `_execute` actually calls.

- [x] **Step 7: Run to verify they pass**

```bash
poetry run pytest backend/tests/test_agent_leaderboard.py backend/tests/test_agent.py -v
make check
```

Expected: PASS. `test_agent.py` matters here — it holds the never-raise and
turn-cap contracts a third tool must not break.

- [x] **Step 8: Commit**

```bash
git add backend/app/agent.py backend/app/config.py backend/tests/test_agent_leaderboard.py .env.example
git commit -m "$(cat <<'EOF'
feat: get_leaderboard, the agent's third tool (4.4, D47)

"Recommend what to try next" is a ranking question, and neither existing
tool can answer it: search_runs returns prose and get_run_detail returns
one run. Asking the model to reconstruct an ordering from snippets gets a
fluent recommendation whose numbers were never in its context.

Named for what it returns, not for the conclusion — a tool called
recommend_next would be treated as producing the recommendation rather
than the evidence for one.

Every row carries its cv band, because D38 makes it load-bearing: a model
given only point estimates reports every lead as real. Absent bands render
as "unquantified", never 0.0 (D32).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Teach the prompt to recommend

**Files:**
- Modify: `prompts/agent.md`
- Test: `backend/tests/test_agent_prompt.py`

**Interfaces:**
- Consumes: the `get_leaderboard` tool (Task 10).
- Produces: no new symbols. The deliverable is prompt text plus a live verification.

- [x] **Step 1: Read the current prompt before editing it**

```bash
cat prompts/agent.md
```

The existing rules — cite sources, say so when retrieval comes back empty, do
not state a margin you cannot source — are the ones a recommendation rule most
easily contradicts. The addition must extend them, not compete with them.

- [x] **Step 2: Write the failing test**

Create `backend/tests/test_agent_prompt.py`:

```python
"""The prompt is a source file with a contract, so its load-bearing rules are
pinned like any other. These assertions are deliberately about the RULES being
present, not about their wording — a reworded prompt that keeps the rules
should not fail."""

from pathlib import Path

PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "agent.md"


def test_the_prompt_names_all_three_tools():
    text = PROMPT.read_text()
    for tool in ("search_runs", "get_run_detail", "get_leaderboard"):
        assert tool in text


def test_a_recommendation_must_be_grounded_in_the_leaderboard():
    """The failure mode D47 exists to prevent: a fluent suggestion assembled
    from snippets, with no ordering behind it."""
    text = PROMPT.read_text().lower()
    assert "recommend" in text
    assert "get_leaderboard" in text


def test_the_prompt_still_forbids_an_unsourceable_margin():
    """Pre-existing rule. A recommendation rule is exactly the kind of addition
    that quietly overrides it — "suggest the next thing to try" invites stating
    a margin nothing measured."""
    text = PROMPT.read_text().lower()
    assert "within noise" in text or "cv_std" in text or "unquantified" in text
```

- [x] **Step 3: Run to verify it fails**

```bash
poetry run pytest backend/tests/test_agent_prompt.py -v
```

Expected: FAIL on the first two — `get_leaderboard` is not yet in the prompt.

- [x] **Step 4: Add the rule**

Append to `prompts/agent.md`, in the numbered-rule style the file already uses:

```markdown
When the question asks what to try next — or asks you to compare, rank, or
recommend — call `get_leaderboard` for the relevant investigation before
answering. Do not assemble an ordering from search snippets: the snippets are
prose about individual runs, and an ordering inferred from them can be wrong
while reading as authoritative.

Ground the recommendation in what the leaderboard shows, and say what it rests
on: which runs, which metric, and what has not been tried. If the gap between
the top runs is smaller than the leader's `cv_std`, say the difference is
within noise rather than naming a winner. Where a run's band is reported as
`unquantified`, say that — do not treat a missing band as a zero one.

If you have no leaderboard for the investigation in question, say what you would
need. A recommendation with nothing behind it is worse than no recommendation,
because it is indistinguishable from one with evidence.
```

- [x] **Step 5: Run to verify it passes**

```bash
poetry run pytest backend/tests/test_agent_prompt.py -v
make check
```

Expected: PASS, 3 tests.

- [x] **Step 6: Verify it live — the actual acceptance criterion**

The tests above prove the prompt says the words. They cannot prove the model
follows them. Start the stack and ask it, through the real endpoint:

```bash
make dev   # in one terminal, with the Postgres DATABASE_URL and both API keys set
curl -s localhost:8000/agent/chat -H 'content-type: application/json' \
  -d '{"question":"which model performed best on the revenue nowcast, and what should I try next?"}' \
  | python3 -m json.tool
```

Check four things in the response, and record what you found in the commit body:

1. `trace.steps` contains a `get_leaderboard` call. If it does not, the tool
   description or the prompt rule is not reaching the model — fix the prompt,
   not the test.
2. The recommendation names specific runs or parameter ranges, not a generic
   "try tuning the hyperparameters".
3. If the top two runs are within `cv_std`, the answer **says so**. This is the
   rule most likely to be ignored, and the one most worth having.
4. `retrieved` still carries citations. A recommendation that cites nothing is
   the regression this task risks introducing.

- [x] **Step 7: Commit**

```bash
git add prompts/agent.md backend/tests/test_agent_prompt.py
git commit -m "$(cat <<'EOF'
feat: ground recommendations in the leaderboard, not in snippets (4.4)

Rules pinned by test are the rules, not their wording — a reworded prompt
that keeps them should not fail.

Verified live against POST /agent/chat: <record what the four checks in
the plan's Step 6 actually showed, including whether the model reported a
within-noise gap as within noise>.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Dockerfile and `render.yaml` (D48, §7.1)

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `render.yaml`
- Modify: `.env.example`
- Test: `backend/tests/test_deploy_config.py`

**Interfaces:**
- Consumes: `app.main.create_app` (existing), `Settings.cors_allow_origins` (existing).
- Produces: no Python symbols. The deliverable is a buildable image and a service manifest.

### Two origins, not one

`/experiments/:experimentId` is **both** a React Router path and a real API route
returning JSON. Serving the SPA from FastAPI needs a catch-all that either
shadows the API or is shadowed by it, and the only clean fix is prefixing every
backend route under `/api` — which changes `/agent/chat`, the path D42 argues
for by name. Two Render services avoid the problem entirely, and
`Settings.cors_allow_origins` already exists for it, carrying the comment "prod
only; dev uses the Vite /api proxy".

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_deploy_config.py`:

```python
"""The deploy manifest is a config file with load-bearing properties, so the
ones that fail silently in production are pinned here rather than discovered
on Render."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_render_declares_both_services_and_a_database():
    manifest = yaml.safe_load((ROOT / "render.yaml").read_text())
    kinds = {service["type"] for service in manifest["services"]}
    assert {"web", "static"} <= kinds
    assert manifest.get("databases")


def test_the_api_service_declares_a_health_check_path():
    """Render restarts an unhealthy instance. Without this it restarts nothing,
    and a wedged process serves 502s indefinitely."""
    manifest = yaml.safe_load((ROOT / "render.yaml").read_text())
    api = next(s for s in manifest["services"] if s["type"] == "web")
    assert api["healthCheckPath"] == "/health"


def test_mlflow_db_upgrade_is_a_release_step_not_a_start_command():
    """Another tool's migrations against a shared database. In the start
    command, every cold start races it (§7.2)."""
    manifest = yaml.safe_load((ROOT / "render.yaml").read_text())
    api = next(s for s in manifest["services"] if s["type"] == "web")
    assert "mlflow db upgrade" not in api.get("startCommand", "")
    assert "mlflow db upgrade" in api.get("preDeployCommand", "")


def test_the_dockerfile_does_not_bake_secrets_or_the_artifact_store():
    text = (ROOT / "Dockerfile").read_text()
    assert "ANTHROPIC_API_KEY" not in text
    assert "VOYAGE_API_KEY" not in text
    assert "mlruns" not in text  # 126 MB of artifacts do not belong in an image


def test_env_example_documents_every_deploy_variable():
    """A variable that exists only in the Render dashboard is one the next
    person cannot know to set."""
    text = (ROOT / ".env.example").read_text()
    for key in (
        "CORS_ALLOW_ORIGINS",
        "MLFLOW_TRACKING_URI",
        "MLFLOW_ARTIFACT_ROOT",
        "MLFLOW_S3_ENDPOINT_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
    ):
        assert key in text, key
```

- [x] **Step 2: Run to verify they fail**

```bash
poetry run pytest backend/tests/test_deploy_config.py -v
```

Expected: FAIL — `render.yaml` does not exist.

- [x] **Step 3: Write the Dockerfile**

```dockerfile
# The API service only. The SPA is a separate Render static site (§7.1).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_VIRTUALENVS_CREATE=false

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir "poetry==${POETRY_VERSION}"

WORKDIR /app

# Dependencies first, so a source-only change does not reinstall them.
COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root --no-interaction

COPY backend/ ./backend/
COPY prompts/ ./prompts/
COPY alembic.ini ./

# No secrets and no mlruns/. Keys arrive as Render environment variables, and
# artifacts live in R2 (Task 13) — 126 MB of models in an image would be baked
# in at build time and stale by the first run logged after it.
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--app-dir", "backend", \
     "--host", "0.0.0.0", "--port", "8000"]
```

Create `.dockerignore`:

```
mlruns/
data-sources/
frontend/
.git/
.env
.venv/
**/__pycache__/
.mypy_cache/
.pytest_cache/
.ruff_cache/
backend/eval/.vector-cache.json
```

- [x] **Step 4: Write `render.yaml`**

```yaml
# Two services (§7.1): the SPA is static, the API is a container. A single
# origin would need every backend route prefixed under /api, which changes
# /agent/chat — the path D42 argues for by name.
services:
  - type: web
    name: wavepoint-api
    runtime: docker
    dockerfilePath: ./Dockerfile
    plan: free
    healthCheckPath: /health
    # MLflow's migrations are another tool's, against a shared database. In
    # startCommand every cold start would race them (§7.2). init_db() still
    # runs OUR alembic upgrade at startup, which is ours to race with nobody.
    preDeployCommand: "poetry run mlflow db upgrade $DATABASE_URL"
    envVars:
      - key: DATABASE_URL
        fromDatabase:
          name: wavepoint-db
          property: connectionString
      - key: MLFLOW_TRACKING_URI
        fromDatabase:
          name: wavepoint-db
          property: connectionString
      - key: CORS_ALLOW_ORIGINS
        sync: false
      - key: MLFLOW_ARTIFACT_ROOT
        sync: false
      - key: MLFLOW_S3_ENDPOINT_URL
        sync: false
      - key: AWS_ACCESS_KEY_ID
        sync: false
      - key: AWS_SECRET_ACCESS_KEY
        sync: false
      - key: ANTHROPIC_API_KEY
        sync: false
      - key: VOYAGE_API_KEY
        sync: false
      # No collector is deployed, and Jaeger stays a local tool (§7.4).
      - key: OTEL_ENABLED
        value: "false"

  - type: static
    name: wavepoint-web
    buildCommand: "cd frontend && npm ci && npm run build"
    staticPublishPath: ./frontend/dist
    envVars:
      - key: VITE_API_BASE
        sync: false
    routes:
      # Client-side routing: /experiments/:id must serve index.html, not 404.
      - type: rewrite
        source: /*
        destination: /index.html

databases:
  - name: wavepoint-db
    plan: free
    postgresMajorVersion: "16"
```

**`MLFLOW_TRACKING_URI` shares the app database on purpose** — that is the
existing local arrangement (D4), with MLflow owning the `mlflow` schema and
Alembic's `app_schema_only` filter keeping autogenerate off it. If Render's
connection string arrives in `postgres://` form and MLflow rejects it, normalize
to `postgresql://` in `config.py` rather than hand-editing the dashboard value,
so the fix is in the repo.

`CORS_ALLOW_ORIGINS` is `sync: false` because the static site's URL is not known
until it first deploys. Set it to that URL afterwards — the frontend will fetch
successfully with it unset in dev (the Vite proxy) and fail only in production,
which is exactly the failure that is easy to ship.

- [x] **Step 5: Run to verify they pass**

```bash
poetry run pytest backend/tests/test_deploy_config.py -v
```

Expected: PASS, 5 tests. Add the `CORS_ALLOW_ORIGINS`, `MLFLOW_*`, and `AWS_*`
entries to `.env.example` in this step if the last test still fails.

- [x] **Step 6: Build the image locally**

```bash
docker build -t wavepoint-api .
docker run --rm -p 8001:8000 -e DATABASE_URL="sqlite:///./smoke.db" wavepoint-api &
sleep 8 && curl -fsS localhost:8001/health && echo OK
docker rm -f $(docker ps -q --filter ancestor=wavepoint-api) 2>/dev/null || true
```

A green `make check` says nothing about whether the image builds. This is the
step that does.

- [x] **Step 7: Commit**

```bash
make check
git add Dockerfile .dockerignore render.yaml .env.example backend/tests/test_deploy_config.py
git commit -m "$(cat <<'EOF'
feat: two-service Render deploy manifest and API image (4.5, D48)

Two origins, not one: /experiments/:experimentId is both a React Router
path and a real API route, so a single origin needs every backend route
prefixed under /api — which changes /agent/chat, the path D42 argues for
by name. cors_allow_origins already existed for exactly this.

mlflow db upgrade is a preDeployCommand: it is another tool's migrations
against a shared database, and in the start command every cold start
races it. Our own alembic upgrade stays in init_db().

Image built and /health checked locally — make check says nothing about
whether the image builds.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Artifacts to R2, and the URI rewrite (D48, §7.3)

The task the deploy actually turns on. Without it,
`POST /runs/{id}/diagnostics` 409s forever on the deployed instance — D24 refuses
to refit from logged params, so a missing artifact is unrecoverable by design.

**Files:**
- Create: `scripts/migrate_artifact_uris.py`
- Modify: `pyproject.toml` (add `boto3`), `backend/app/config.py`, `.env.example`, `README.md`
- Test: `backend/tests/test_artifact_uri_migration.py`

**Interfaces:**
- Consumes: `Settings.mlflow_artifact_root` (existing, currently `"./mlruns"`).
- Produces:
  - `rewrite_uri(old: str, *, old_root: str, new_root: str) -> str`
  - `plan_rewrites(rows: list[tuple[str, str]], *, old_root: str, new_root: str) -> list[tuple[str, str]]`
  - `main()` — applies the rewrite to `mlflow.experiments.artifact_location` and `mlflow.runs.artifact_uri`

### Why not just re-train on the deployed instance

Training is LLM-free (D17) and cheap, so re-running it there is the tempting
shortcut. It mints **new run ids** — and both `backend/eval/curation.yaml` and
`backend/eval/golden_set.yaml` are keyed by the existing ones. The corpus and its
ground truth would silently stop referring to anything that exists, and every
eval number after that point would be measuring a different corpus under the same
name. Dump, restore, sync, rewrite. Ids are preserved.

### Why a rewrite is needed at all

MLflow stores **absolute** artifact URIs, in two columns. Syncing `mlruns/` to R2
does not touch them: they still name `/app/mlruns/...`, a path that does not
exist on Render. `mlflow.sklearn.load_model` then fails with a file-not-found for
a file that was uploaded successfully.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_artifact_uri_migration.py`:

```python
"""Pure string rewriting, tested offline. The SQL that applies it is four
lines; the arithmetic of which prefix becomes which is where this goes wrong,
and a wrong URI fails as a file-not-found for a file that uploaded fine."""

import pytest

from migrate_artifact_uris import plan_rewrites, rewrite_uri

OLD = "file:///Users/x/dev/wavepoint/mlruns"
NEW = "s3://wavepoint-artifacts/mlruns"


def test_it_replaces_only_the_root_prefix():
    got = rewrite_uri(f"{OLD}/12/abc123/artifacts", old_root=OLD, new_root=NEW)
    assert got == f"{NEW}/12/abc123/artifacts"


def test_a_bare_relative_root_is_matched_too():
    """mlflow_artifact_root defaults to './mlruns', so rows written before any
    deploy carry a relative path, not a file:// URI."""
    got = rewrite_uri("./mlruns/12/abc/artifacts", old_root="./mlruns", new_root=NEW)
    assert got == f"{NEW}/12/abc/artifacts"


def test_a_uri_already_under_the_new_root_is_left_alone():
    """The script must be safe to re-run — a half-finished migration is the
    likeliest state to find it in."""
    already = f"{NEW}/12/abc/artifacts"
    assert rewrite_uri(already, old_root=OLD, new_root=NEW) == already


def test_a_uri_under_neither_root_is_refused_not_guessed():
    """Silently leaving it makes the run unloadable with no error; silently
    rewriting it invents a path. Naming it is the only honest option."""
    with pytest.raises(ValueError, match="unexpected"):
        rewrite_uri("s3://someone-elses-bucket/12/abc", old_root=OLD, new_root=NEW)


def test_the_plan_skips_rows_that_need_no_change():
    rows = [("run-1", f"{OLD}/1/a"), ("run-2", f"{NEW}/1/b")]
    plan = plan_rewrites(rows, old_root=OLD, new_root=NEW)
    assert plan == [("run-1", f"{NEW}/1/a")]


def test_the_plan_preserves_the_trailing_path_exactly():
    """The suffix carries the experiment id, the run id and 'artifacts'. Losing
    a segment points every run at the same directory."""
    rows = [("r", f"{OLD}/7/deadbeef/artifacts")]
    assert plan_rewrites(rows, old_root=OLD, new_root=NEW)[0][1].endswith("/7/deadbeef/artifacts")
```

- [x] **Step 2: Run to verify they fail**

```bash
poetry run pytest backend/tests/test_artifact_uri_migration.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'migrate_artifact_uris'`.

- [x] **Step 3: Write the script**

Create `scripts/migrate_artifact_uris.py`:

```python
"""Re-point MLflow's absolute artifact URIs at object storage (§7.3, D48).

MLflow stores ABSOLUTE artifact URIs in two columns —
mlflow.experiments.artifact_location and mlflow.runs.artifact_uri — so syncing
mlruns/ to R2 is not sufficient. Those columns still name a local path that does
not exist on Render, and mlflow.sklearn.load_model then fails with a
file-not-found for a file that uploaded successfully.

Raw SQL against MLflow's own schema, deliberately: D4 says never model MLflow
tables in app/models.py. This is a one-shot script, not an ORM change.

Re-running it is safe — rows already under the new root are skipped.
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import create_engine, text


def rewrite_uri(old: str, *, old_root: str, new_root: str) -> str:
    old_root, new_root = old_root.rstrip("/"), new_root.rstrip("/")
    if old.startswith(new_root):
        return old  # already migrated; the script must be re-runnable
    if old.startswith(old_root):
        return new_root + old[len(old_root) :]
    # Neither leaving it nor rewriting it is honest: leaving it makes the run
    # unloadable with no error, rewriting it invents a path.
    raise ValueError(f"unexpected artifact root in {old!r}; expected {old_root!r}")


def plan_rewrites(
    rows: list[tuple[str, str]], *, old_root: str, new_root: str
) -> list[tuple[str, str]]:
    plan: list[tuple[str, str]] = []
    for key, uri in rows:
        new = rewrite_uri(uri, old_root=old_root, new_root=new_root)
        if new != uri:
            plan.append((key, new))
    return plan


_TABLES = (
    ("mlflow.experiments", "experiment_id", "artifact_location"),
    ("mlflow.runs", "run_uuid", "artifact_uri"),
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-point MLflow artifact URIs")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--old-root", required=True, help="e.g. file:///app/mlruns or ./mlruns")
    parser.add_argument("--new-root", required=True, help="e.g. s3://wavepoint-artifacts/mlruns")
    parser.add_argument("--apply", action="store_true", help="write; otherwise print the plan")
    args = parser.parse_args()

    engine = create_engine(args.database_url)
    with engine.begin() as conn:
        for table, key_col, uri_col in _TABLES:
            rows = [
                (str(k), str(u))
                for k, u in conn.execute(text(f"SELECT {key_col}, {uri_col} FROM {table}"))
                if u is not None
            ]
            plan = plan_rewrites(rows, old_root=args.old_root, new_root=args.new_root)
            print(f"{table}: {len(plan)} of {len(rows)} row(s) to rewrite")
            for key, new in plan:
                print(f"  {key} -> {new}")
                if args.apply:
                    conn.execute(
                        text(f"UPDATE {table} SET {uri_col} = :uri WHERE {key_col} = :key"),
                        {"uri": new, "key": key},
                    )
    print("applied." if args.apply else "dry run; re-run with --apply to write.")


if __name__ == "__main__":
    main()
```

- [x] **Step 4: Run to verify they pass**

```bash
poetry run pytest backend/tests/test_artifact_uri_migration.py -v
```

Expected: PASS, 6 tests.

- [x] **Step 5: Add `boto3` and document the new configuration**

```bash
poetry add boto3
```

MLflow's `s3://` artifact repository requires it, and `MLFLOW_S3_ENDPOINT_URL`
is what points that S3 client at R2 rather than at AWS. Add to `.env.example`:

```
# Artifact store (D48). Local dev keeps ./mlruns; the deploy uses R2.
MLFLOW_ARTIFACT_ROOT=./mlruns
MLFLOW_S3_ENDPOINT_URL=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
```

Leave `Settings.mlflow_artifact_root`'s default as `"./mlruns"` — local
development should not need R2 credentials to train a model.

- [x] **Step 6: Create the bucket and sync**

```bash
# Cloudflare R2 → create bucket `wavepoint-artifacts`, then an API token with
# Object Read & Write. R2's free tier is 10 GB against a current 126 MB:
du -sh mlruns/

aws s3 sync mlruns/ s3://wavepoint-artifacts/mlruns/ \
  --endpoint-url "$MLFLOW_S3_ENDPOINT_URL"
aws s3 ls s3://wavepoint-artifacts/mlruns/ --endpoint-url "$MLFLOW_S3_ENDPOINT_URL" | head
```

- [x] **Step 7: Dry-run the rewrite against the LOCAL database first**

```bash
poetry run python scripts/migrate_artifact_uris.py \
  --database-url "postgresql+psycopg2://wavepoint:wavepoint@localhost:5433/wavepoint" \
  --old-root "$(pwd)/mlruns" \
  --new-root "s3://wavepoint-artifacts/mlruns"
```

Read the printed plan. If any row raises `unexpected artifact root`, find out
what root it carries before touching `--apply` — MLflow may have written
`file://`-prefixed URIs, in which case pass that form as `--old-root`. Do **not**
apply against the local database: local dev keeps its local artifacts. This run
is a rehearsal, and Task 14 applies it against Render.

- [x] **Step 8: Commit**

```bash
make check
git add scripts/migrate_artifact_uris.py backend/tests/test_artifact_uri_migration.py pyproject.toml poetry.lock .env.example
git commit -m "$(cat <<'EOF'
feat: re-point MLflow artifact URIs at object storage (4.5, D48)

Without this the deployed instance 409s on every diagnostics request
forever: D24 refuses to refit from logged params, so a missing artifact is
unrecoverable by design. This closes the phases-2-4 design's open risk #2,
which had accepted artifact loss on deploy.

Syncing mlruns/ to R2 is not sufficient — MLflow stores absolute URIs in
two columns, and they still name a path that does not exist on Render.

Not re-training on the deployed instance: it is cheap (D17) but it mints
new run ids, and curation.yaml and golden_set.yaml are keyed by the
existing ones. The corpus would silently stop referring to anything real.

Raw SQL against MLflow's schema, per D4 — never model those tables.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Deploy and smoke-test (§7.5, §8.4)

Operational. No automated test — a deployed instance is not something
`make check` can assert on, and the checklist below is the deliverable.

**Files:**
- Modify: `README.md` (the live URL, the free-tier caveats, the deploy runbook)
- Create: `doc/deploy-runbook.md`

**Interfaces:**
- Consumes: `Dockerfile` and `render.yaml` (Task 12); `scripts/migrate_artifact_uris.py` (Task 13); the R2 bucket populated in Task 13, Step 6.
- Produces: no code. A live URL, `doc/deploy-runbook.md`, and a completed smoke checklist.

- [x] **Step 1: Provision**

Connect the repo to Render as a Blueprint so `render.yaml` is read. Create the
free Postgres, then set every `sync: false` variable in the dashboard:
`ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `MLFLOW_ARTIFACT_ROOT`
(`s3://wavepoint-artifacts/mlruns`), `MLFLOW_S3_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`. Leave `CORS_ALLOW_ORIGINS` until Step 4.

- [x] **Step 2: Move the data**

```bash
pg_dump "postgresql://wavepoint:wavepoint@localhost:5433/wavepoint" \
  --schema=app --schema=mlflow --no-owner --no-privileges -f /tmp/wavepoint.sql
psql "$RENDER_DATABASE_URL" -f /tmp/wavepoint.sql
psql "$RENDER_DATABASE_URL" -c "select count(*) from app.runs;
  select count(*) from app.experiment_note_chunks;"
```

Both schemas, in one dump. `app` alone loses every MLflow run the `app.runs`
rows join to, and the leaderboard's metrics live on the MLflow side.

- [x] **Step 3: Apply the URI rewrite**

```bash
poetry run python scripts/migrate_artifact_uris.py \
  --database-url "$RENDER_DATABASE_URL" \
  --old-root "$(pwd)/mlruns" --new-root "s3://wavepoint-artifacts/mlruns"
# read the plan, then:
poetry run python scripts/migrate_artifact_uris.py \
  --database-url "$RENDER_DATABASE_URL" \
  --old-root "$(pwd)/mlruns" --new-root "s3://wavepoint-artifacts/mlruns" --apply
```

- [x] **Step 4: Close the CORS loop**

Set `CORS_ALLOW_ORIGINS` on the API service to the static site's URL, and
`VITE_API_BASE` on the static site to the API's URL. Redeploy both. Until this
is done the frontend loads and every request fails — and it works perfectly in
dev, because the Vite proxy makes it same-origin there.

- [x] **Step 5: Run the smoke checklist**

Every item, in order. Item 6 is the one that actually proves D48 landed; a
broken artifact store passes items 1 through 5 without a symptom.

```
[ ] 1. GET /health returns 200 (allow ~50s on the first hit — free tier sleeps)
[ ] 2. The SPA loads and the nav rail lists datasets AND experiments
       (two independent fetches; one failing must not blank the other)
[ ] 3. An experiment's leaderboard renders with ranks and cv bands
[ ] 4. GET /findings returns the approved corpus (23 sources)
[ ] 5. POST /agent/chat answers with citations, and each citation deep-links
       to a page that actually renders that text (3.6b)
[ ] 6. POST /runs/{id}/diagnostics on a run whose artifact lives in R2
       returns 200 and writes a draft finding      <-- the real proof
[ ] 7. POST /experiments/{id}/train completes and appears on the leaderboard
[ ] 8. A second identical CSV upload returns the existing dataset (issue #7)
```

If item 6 409s, the artifact URI rewrite did not take. Re-run Step 3's dry run
against the Render database and read the plan — a zero-row plan means the
`--old-root` did not match what MLflow actually wrote.

- [x] **Step 6: Write the runbook and the caveats**

Create `doc/deploy-runbook.md` recording Steps 1–5 as performed, including the
actual `--old-root` value that matched, and add to `README.md`:

```markdown
## Live demo

<URL>

Two free-tier caveats worth knowing before you click:

- The API sleeps after inactivity, so the **first request after a quiet period
  takes roughly 50 seconds**. Subsequent requests are fast. If the first page
  load looks broken, it is waking up.
- The free managed Postgres **expires 30 days** after creation. After that the
  demo needs a new database and a fresh restore — the runbook in
  `doc/deploy-runbook.md` is what to re-run.

Tracing stays off in the deploy: there is no collector, and Jaeger remains a
local tool.
```

A visitor should read these rather than discover them.

- [x] **Step 7: Commit**

```bash
git add README.md doc/deploy-runbook.md
git commit -m "$(cat <<'EOF'
docs: live deploy, runbook and free-tier caveats (4.5)

Smoke checklist run in full. Item 6 — diagnostics on a run whose artifact
now lives in R2 — is the one that actually proves D48 landed; health
checks and page loads pass with a broken artifact store.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Close the documents out (§9)

Most of the sync happens in the task that causes each change — Task 6 rewrites
`CLAUDE.md`'s `make eval` paragraph, Task 14 adds the README's deploy section.
What is left is the cross-cutting record: the decisions, the closed risks, and
the traceability table that currently points at nothing.

**Files:**
- Modify: `CLAUDE.md`, `README.md`, `doc/architecture.md`, `doc/plans/2026-08-10-project-2-phases-2-4-design.md`, `docs/superpowers/plans/2026-08-28-project-2-phase-4.md`

**Interfaces:**
- Consumes: every prior task's deliverable, by name.
- Produces: no code. This task exists because a decision recorded nowhere is a decision the next person re-litigates.

- [x] **Step 1: Add the D43–D48 sections to `CLAUDE.md`**

Under **Non-obvious design decisions**, in the existing voice — each one leads
with what breaks if you do the tempting thing:

- **Ground truth is a source, not a chunk (D43).** Relevance is labelled on
  `(source_type, source_id)`, matching what `search_runs` returns after grouping
  (3.4b). Labelling chunks would measure the chunker rather than the retrieval,
  and the labels would silently expire the next time `chunk_max_chars` changed.
- **Golden-set queries are written blind (D44).** Drafted from the leaderboard,
  params and metrics only — never from note prose. Claude wrote the notes; a
  query written while reading one largely measures whether retrieval can find
  the document it was copied from. The rule binds anyone extending the set: a
  half-blind, half-derived set reports one number over two incomparable halves.
- **The corpus is a curated subset (D45).** 17 of 32 runs approved, chosen for
  model and outcome diversity, with reasons recorded in `backend/eval/curation.yaml`.
  Approving all 32 makes almost every source relevant to almost every query and
  precision stops discriminating; approving whichever ones read well biases the
  corpus toward the queries.
- **The sweep is pre-registered (D46).** Grid, metric and adoption rule
  committed before any configuration is measured. Nine configurations on twenty
  queries with a post-hoc winner finds one from noise essentially every time.
  Adoption needs a paired MRR delta beyond two standard errors — the same
  "within noise" convention D38 uses.
- **`get_leaderboard` is named for what it returns (D47).** Not `recommend_next`:
  a tool returning rows must not be named for the conclusion, or the model
  treats its output as the recommendation rather than the evidence for one.
- **Artifacts live in object storage (D48).** `mlflow_artifact_root` is an
  `s3://` URI on the deploy. MLflow stores **absolute** artifact URIs in two
  columns, so syncing the directory is not enough — `scripts/migrate_artifact_uris.py`
  rewrites them. Re-training on the deployed instance instead would mint new run
  ids and orphan both `curation.yaml` and `golden_set.yaml`.

- [x] **Step 2: Update `CLAUDE.md`'s code-layout tree**

Add `backend/eval/` (`metrics.py`, `cache.py`, `runner.py`, `golden_set.yaml`,
`curation.yaml`, `results/`), `backend/app/leaderboard.py`,
`scripts/apply_curation.py`, `scripts/sweep_retrieval.py`,
`scripts/migrate_artifact_uris.py`, `Dockerfile`, `render.yaml`. The tree is the
first thing a reader uses to find code; a file missing from it is a file nobody
finds.

- [x] **Step 3: Close the two open risks**

In `doc/plans/2026-08-10-project-2-phases-2-4-design.md`:

- **Risk #2** ("model artefacts do not survive a deploy … Acceptable") — mark
  **resolved**, pointing at D48 and `scripts/migrate_artifact_uris.py`. Record
  that "acceptable" was wrong for a specific reason: D24 refuses to refit from
  logged params, so artifact loss makes diagnostics permanently unavailable
  rather than merely slower.
- **Risk #4** (branch protection) — mark **won't-fix**, recording the 403 that
  made it unavailable on this account. A risk left open with no note reads as
  unexamined.

- [x] **Step 4: Annotate the outline's three stale Phase 4 statements**

The spec's §2 records six supersessions. Two of them are the risks above and one
is `CLAUDE.md`'s `make eval` paragraph (Task 6, Step 9). The remaining three live
in `doc/plans/2026-08-10-project-2-phases-2-4-design.md`'s Phase 4 section and are
still stated as future work. Annotate each in place — do not delete them, since a
document that quietly loses a claim gives a later reader no way to tell it was
reconsidered:

- **"Build `ExperimentChatPage`" is already done**, as `AskPage`, shipped in 3.6b.
  The outline's first Phase 4 task was complete before Phase 4 began.
- **"known-relevant experiment ids" is the wrong unit.** Written before D33 split
  *experiment* (an investigation) from *run* (one attempt). `search_runs` returns
  `(source_type, source_id)` spanning `note`, `diagnostic` and `eda` — and the
  last is keyed to a *dataset* and has no experiment id at all. See D43.
- **`k` counts sources, not chunks** (3.4b), so precision@k is a precision over
  answers rather than over passages. The outline's `k` predates that change.

- [x] **Step 5: Repoint the traceability table**

Two rows in that document's §8 currently point at nothing:

- "agent recommends next experiments" → `app/agent.py` (`get_leaderboard`),
  `app/leaderboard.py`, `prompts/agent.md`
- "retrieval quality is measured" → `backend/eval/`, `make eval`,
  `backend/eval/results/`

- [x] **Step 6: Update the architecture diagram**

In `doc/architecture.md`, add the eval harness beside the retrieval half —
golden set → runner → `retrieval.search_runs` → metrics — and show
`get_leaderboard` as the agent's third tool. Make it visible that the harness
reads through the **same** `search_runs` the agent does; a diagram showing a
separate path would suggest the eval measures a reimplementation, which is the
one thing about it that must not be true.

- [x] **Step 7: Tick this plan's boxes**

Walk `docs/superpowers/plans/2026-08-28-project-2-phase-4.md` and check off every
completed step. An unticked plan is indistinguishable from an abandoned one.

- [x] **Step 8: Final gate and commit**

```bash
make check
cd frontend && npm run type-check && npm test && npm run build && cd ..
```

```bash
git add CLAUDE.md README.md doc/architecture.md doc/plans/2026-08-10-project-2-phases-2-4-design.md docs/superpowers/plans/2026-08-28-project-2-phase-4.md
git commit -m "$(cat <<'EOF'
docs: record D43-D48, close two open risks, repoint traceability (4.6)

Risk #2 is closed as resolved rather than accepted: "artifacts do not
survive a deploy" was judged acceptable, but D24 refuses to refit from
logged params, so it made diagnostics permanently unavailable rather than
merely slower. Risk #4 is closed won't-fix with the 403 recorded — a risk
left open with no note reads as unexamined.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Done means

- `make check` green; the frontend job green; `pytest -m postgres` green against a pgvector service.
- `make eval` runs end to end and writes a report naming the configuration it measured.
- `backend/eval/results/` holds `baseline.md` and `sweep.md`, and the sweep's grid was committed before its results.
- The agent calls `get_leaderboard` when asked what to try next, and reports a within-noise gap as within noise.
- A live URL serves the SPA, and `POST /runs/{id}/diagnostics` returns 200 there.
- D43–D48 are in `CLAUDE.md`; risks #2 and #4 are closed with reasons.
