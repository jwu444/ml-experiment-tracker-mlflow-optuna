# Project 2 Phase 3 — Retrieval, Agent, and Tracing: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the embedding pipeline, two-stage retrieval over approved experiment history, a hand-rolled agent that queries it, and the OpenTelemetry tracing that makes both inspectable.

**Architecture:** Four new backend modules with one external boundary each — `embeddings.py` (Voyage), `retrieval.py` (pgvector + MLflow), `agent.py` (Anthropic), `tracing.py` (OpenTelemetry) — behind one new route, `POST /agent/chat`, and one new page, `AskPage`. Indexing runs offline from `make embed`, never from a request. Retrieval is a structured pre-filter (SQL over `app.runs ⋈ app.experiments`, plus MLflow for run status) that narrows a candidate set, then a vector similarity query over approved chunks restricted to that set.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, pgvector, Voyage AI (`voyageai`), Anthropic, OpenTelemetry (SDK + OTLP/HTTP exporter), MLflow 3.15, pytest, React 19 + Vite + TypeScript, Vitest.

**Spec:** [`doc/plans/2026-08-25-project-2-phase-3-retrieval-agent-tracing-design.md`](2026-08-25-project-2-phase-3-retrieval-agent-tracing-design.md) (decisions D28–D42).

## Global Constraints

Every task's requirements implicitly include this section.

- **Line length is 100.** ruff and black are both configured to it. mypy is **strict** on `backend/app`.
- **Backend app code goes in `backend/app/` only; backend tests in `backend/tests/` only.** Imports are absolute from `app` (`from app.retrieval import search_runs`).
- **`make check` is the gate**: `lint` + `format-check` + `type-check` + `test`. All four target `backend` only — `scripts/` is unlinted, unformatted and untyped, so never put logic there that deserves checking.
- **Tests run on SQLite** via the `client` / `db_engine` / `db_session` fixtures in `backend/tests/conftest.py`. Production uses Postgres. Postgres-only behaviour is tested under `@pytest.mark.postgres` and is skipped when `POSTGRES_TEST_URL` is unset.
- **No API keys in CI.** Voyage and Anthropic are mocked in every test. Every new `Settings` field must have a default that lets the suite run with no `.env` at all.
- **Only `approved` text is ever embedded (D28).** Never index drafts; never add a draft tier to retrieval; never add bulk-approval tooling to make the corpus gate easier.
- **No route calls Voyage for indexing (D17).** `POST /agent/chat` embeds *queries* at request time — that is the one and only request-path Voyage call. Approval routes (`PATCH /runs/{id}`, `PATCH /findings/{id}`) stay untouched.
- **`EMBEDDING_DIM = 512`** (`backend/app/models.py`). No migration is written in this phase; `experiment_note_chunks` already exists with the right shape.
- **The assembled system prompt is never exposed** — not returned by any route, not stored, no UI toggle.
- **Span attributes carry ids, counts and durations — never payloads.** No embedding vectors, no note text, no question text on a span.
- **An "experiment" is an investigation; a "run" is one training run (D33).** `runs.notes` is the note corpus. Diagnostic findings key on `runs.id`; EDA findings key on `datasets.id`. `dataset_id`, `task_type` and `target_column` live on `app.experiments`, not on `app.runs`.
- **Let ruff place the imports.** The import blocks shown in this plan are grouped for readability, not sorted to ruff's `I` rule. After adding imports, run `poetry run ruff check --fix backend` and `make format`; do not hand-tune the order.
- **Commit after every task**, using the repo's conventional-commit style (`feat:`, `test:`, `docs:`, `chore:`). Reference the task's GitHub issue in the body.

## Preconditions (not code — do these before Task 4)

- **≥20 approved run notes.** Currently **0 of 33** (all drafts, all with real generated text). Approve them one at a time through `ExperimentDetailPage`'s review dialog. Tasks 1–3 do not depend on this; Task 5's `make embed` produces an empty index without it, and Tasks 6–12 will run but demonstrate nothing.
- **`VOYAGE_API_KEY` in `.env`.** Needed by `make embed` *and* at request time by `POST /agent/chat`. Never in CI.
- **`make db-up` + `make mlflow-init`** for anything touching Postgres or the tracking store.

## File Structure

| Path | Responsibility | Task |
|---|---|---|
| `backend/app/tracing.py` | **Create.** `configure_tracing()`, `span()`. Only module importing `opentelemetry`. | 2 |
| `backend/app/embeddings.py` | **Create.** `chunk_text()`, `embed_texts()`, `approved_sources()`, `index_source()`, `backfill()`. Only module importing `voyageai`. | 4, 5 |
| `backend/app/retrieval.py` | **Create.** `Filters`, `Candidates`, `Hit`, `RunDetail`, `candidate_runs()`, `search_runs()`, `get_run_detail()`. pgvector SQL + `experiment_log`. No Anthropic. | 6, 7 |
| `backend/app/agent.py` | **Create.** `TOOLS`, `validate_tool_call()`, `run_agent()`, `AgentResult`, `AgentStep`. Only new module importing `anthropic`. | 9, 10 |
| `backend/app/routes/agent.py` | **Create.** `POST /agent/chat`. | 11 |
| `prompts/agent.md` | **Create.** The agent's system prompt. | 9 |
| `scripts/backfill_embeddings.py` | **Create.** `make embed` entry point. | 5 |
| `backend/app/config.py` | **Modify.** New settings, added by the task that consumes each. | 2, 4, 7, 10 |
| `backend/app/main.py` | **Modify.** `configure_tracing()` in `create_app()`; include the agent router. | 2, 11 |
| `backend/app/loop.py` | **Modify.** Spans around analyst/judge/render. | 3 |
| `backend/app/routes/experiments.py` | **Modify.** `train_run` attaches `cv_<metric>` + `cv_std`. | 1 |
| `backend/app/schemas.py` | **Modify.** `AgentChatRequest`, `AgentChatOut`, `RetrievedOut`, `AgentTraceOut`, `AgentStepOut`. | 11 |
| `backend/app/models.py` | **Modify.** Fix `ExperimentNoteChunk`'s pre-D33 docstring. | 13 |
| `backend/tests/conftest.py` | **Modify.** `spans` fixture (Task 2), `fake_voyage` fixture (Task 4). | 2, 4 |
| `frontend/src/pages/AskPage.tsx` + `.module.css` + `.test.tsx` | **Create.** | 12 |
| `frontend/src/api.ts`, `types.ts`, `App.tsx`, `components/NavRail.tsx` | **Modify.** `askAgent`, `/ask` route, `Agent` nav category. | 12 |
| `.github/workflows/ci.yml` | **Modify.** Third job, `backend-postgres`. | 8 |
| `pyproject.toml` | **Modify.** Dependencies; the `postgres` pytest marker. | 2, 4, 8 |
| `Makefile` | **Modify.** `embed` target. | 5 |
| `.env.example` | **Modify.** New keys, added by the task that introduces each. | 2, 4 |

---

## GitHub issues

One issue per task, labelled `phase-3`. Reference the issue in the task's commit body and
close it from the PR.

| Task | Issue | Depends on |
|---|---|---|
| 1 — cv band on `/train` (3.0) | [#62](../../issues/62) | — |
| 2 — `app/tracing.py` (3.1) | [#63](../../issues/63) | — |
| 3 — spans in `app/loop.py` (3.2) | [#64](../../issues/64) | 2 |
| 4 — `app/embeddings.py` (3.3a) | [#65](../../issues/65) | — |
| 5 — the backfill (3.3b) | [#66](../../issues/66) | 4 |
| 6 — structured stage (3.4a) | [#67](../../issues/67) | — |
| 7 — vector stage (3.4b) | [#68](../../issues/68) | 4, 6 |
| 8 — Postgres CI job (3.7) | [#69](../../issues/69) | 7 |
| 9 — tools and prompt (3.5a) | [#70](../../issues/70) | 6, 7 |
| 10 — `run_agent()` (3.5b) | [#71](../../issues/71) | 2, 7, 9 |
| 11 — `POST /agent/chat` (3.6a) | [#72](../../issues/72) | 10 |
| 12 — `AskPage` (3.6b) | [#73](../../issues/73) | 11 |
| 13 — doc sync | [#74](../../issues/74) | all |

Tasks 1, 2, 4 and 6 have no dependencies and can be started in any order.

---

### Task 1: `POST /experiments/{id}/train` logs the cross-validation band (3.0)

**Files:**
- Modify: `backend/app/routes/experiments.py` (add `_attach_cv_metrics`; call it in `train_run` between `fit_and_score` and `log_run`)
- Test: `backend/tests/test_train_route.py`

**Why:** `training.fit_and_score` returns holdout metrics only. `cv_<metric>` and `cv_std` are written by `tune_run` alone. The persistence baseline is trained and never tuned (its `search_space` is empty and `/tune` 422s on it, D25), so the one run on every leaderboard with no noise band is the reference every other run is compared against. `app/ranking.py` already reads `cv_std` and receives `None` for every trained run.

**Interfaces:**
- Consumes: `training.cv_objective(model_type, hyperparams, df, target, features, time_column) -> tuple[float, float]` (mean, std) — already exists and is pure; `training.ModelSpec.objective_metric`.
- Produces: `RunOut.metrics` for a `FINISHED` train run now contains `cv_<objective_metric>` and `cv_std` alongside the holdout metrics. Task 7's `get_run_detail` reads `cv_std` out of MLflow.

- [x] **Step 1: Write the failing test**

Append to `backend/tests/test_train_route.py`:

```python
def test_train_logs_the_cross_validation_band(client, panel_id):
    """3.0/D32: a trained run reports cv_<metric> and cv_std, as a tuned one does.

    Without this the persistence baseline — trained and never tuned (D25) — is
    the only run on the leaderboard with no noise band, and it is the reference
    every other run is compared against.
    """
    experiment = client.post(
        "/experiments",
        json={
            "name": "cv-band",
            "dataset_id": panel_id,
            "target_column": "price",
            "task_type": "regression",
            "primary_metric": "rmse",
        },
    ).json()
    resp = client.post(
        f"/experiments/{experiment['id']}/train",
        json={"model_type": "ridge", "hyperparams": {"alpha": 1.0}, "time_column": "as_of"},
    )
    assert resp.status_code == 200
    metrics = resp.json()["metrics"]
    assert "rmse" in metrics
    assert "cv_rmse" in metrics
    assert "cv_std" in metrics
    assert metrics["cv_std"] >= 0.0


def test_train_logs_the_band_for_the_persistence_baseline(client, panel_id):
    """The baseline is the run that most needs a band, and the one that had none."""
    experiment = client.post(
        "/experiments",
        json={
            "name": "cv-band-baseline",
            "dataset_id": panel_id,
            "target_column": "price",
            "task_type": "regression",
            "primary_metric": "rmse",
        },
    ).json()
    resp = client.post(
        f"/experiments/{experiment['id']}/train",
        json={
            "model_type": "persistence",
            "hyperparams": {"prior_column": "memory"},
            "time_column": "as_of",
        },
    )
    assert resp.status_code == 200
    metrics = resp.json()["metrics"]
    assert "cv_rmse" in metrics
    assert "cv_std" in metrics


def test_a_failed_fit_gets_no_band_and_is_still_recorded(client, panel_id):
    """A cross-validation failure must not turn a recorded FAILED run into a 500,
    and must not invent a band for a run that never fit (§8: failures are data)."""
    experiment = client.post(
        "/experiments",
        json={
            "name": "cv-band-failed",
            "dataset_id": panel_id,
            "target_column": "price",
            "task_type": "regression",
            "primary_metric": "rmse",
        },
    ).json()
    resp = client.post(
        f"/experiments/{experiment['id']}/train",
        json={"model_type": "ridge", "hyperparams": {"alpha": "not-a-number"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "FAILED"
    assert "cv_std" not in body["metrics"]
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `poetry run pytest backend/tests/test_train_route.py -k cross_validation_band -v`
Expected: FAIL with `KeyError` / `assert 'cv_rmse' in {...}`.

Note: `test_train_route.py` carries a module-level `pytestmark = pytest.mark.usefixtures("mlflow_store")`. Confirm that line is present at the top of the file before running; if it is not, add `@pytest.mark.usefixtures("mlflow_store")` to each new test.

- [x] **Step 3: Add the helper**

In `backend/app/routes/experiments.py`, add above `train_run`:

```python
def _attach_cv_metrics(
    result: training.TrainResult,
    spec: training.ModelSpec,
    model_type: str,
    df: pd.DataFrame,
    target: str,
    features: list[str],
    time_column: str | None,
) -> None:
    """Add `cv_<objective_metric>` and `cv_std` to a finished run's metrics (3.0).

    /tune has always logged the spread; /train logging only the holdout is why
    the persistence baseline — trained and never tuned (D25) — is the one run on
    every leaderboard with no noise band, and it is the reference every other run
    is compared against. The holdout is ~30 rows at this data size, so a point
    estimate cannot separate two models (D12).

    A cross-validation failure is not a training failure: the fit already
    succeeded and is worth logging, so the bands are simply absent rather than
    the run being lost. `cv_std` stays optional everywhere downstream for the
    same reason runs logged before this task have none.
    """
    if result.status != "FINISHED":
        return
    try:
        mean, std = training.cv_objective(
            model_type, result.params, df, target, features, time_column
        )
    except Exception:  # noqa: BLE001 — a missing band must never lose a good fit
        return
    result.metrics[f"cv_{spec.objective_metric}"] = mean
    result.metrics["cv_std"] = std
```

`pd` is already imported in this module (it is used by `_require_dataset_column`). If it is not, add `import pandas as pd` to the top-level imports.

- [x] **Step 4: Call it from `train_run`**

In `train_run`, insert the call between the `fit_and_score` assignment and the `experiment_log.log_run(...)` call — the ordering matters, because `log_run` writes `result.metrics` to the tracking store:

```python
    result = training.fit_and_score(
        request.model_type,
        request.hyperparams,
        df,
        experiment.target_column,
        features,
        request.time_column,
    )
    # Before log_run: the tracking store is written from result.metrics.
    _attach_cv_metrics(
        result,
        spec,
        request.model_type,
        df,
        experiment.target_column,
        features,
        request.time_column,
    )
    run_id = experiment_log.log_run(
```

- [x] **Step 5: Run the tests to verify they pass**

Run: `poetry run pytest backend/tests/test_train_route.py -v`
Expected: PASS, including the pre-existing tests in that file.

- [x] **Step 6: Run the gate**

Run: `make check`
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add backend/app/routes/experiments.py backend/tests/test_train_route.py
git commit -m "feat: /train logs cv_<metric> and cv_std as /tune does (3.0)"
```

- [x] **Step 8: Re-launch the persistence baselines (manual, needs the dev stack)**

This is the second half of deliverable 3.0 and is **not** a code change: it is a
new run through the fixed route, not a rewrite of the three existing MLflow
runs, which stay as they are. Requires `make db-up`, `make mlflow-init`, and
`make dev` running against Postgres.

For each experiment that has a persistence run, POST a fresh one:

```bash
curl -s localhost:8000/experiments | python3 -m json.tool   # find the ids
curl -s -X POST localhost:8000/experiments/<experiment-id>/train \
  -H 'content-type: application/json' \
  -d '{"model_type":"persistence","hyperparams":{"prior_column":"<prior col>"},"time_column":"<time col>"}' \
  | python3 -m json.tool
```

Verify the response `metrics` contains `cv_rmse` and `cv_std`, then confirm the
leaderboard shows a band on the baseline row: `GET /experiments/<id>/runs`.

---

### Task 2: `app/tracing.py` — OTel helpers, off by default (3.1)

**Files:**
- Create: `backend/app/tracing.py`
- Modify: `backend/app/main.py` (call `configure_tracing()` in `create_app()`), `backend/app/config.py`, `.env.example`, `pyproject.toml`, `backend/tests/conftest.py`
- Test: `backend/tests/test_tracing.py`

**Why:** `docker-compose.yml` already runs Jaeger with OTLP on :4318 and its UI on :16686, instrumented by nothing. Tracing must be **off by default** so `make test` needs no collector and CI is unaffected.

**Interfaces:**
- Produces:
  - `tracing.configure_tracing() -> None` — installs the OTLP exporter; a no-op when `settings.otel_enabled` is False, and idempotent.
  - `tracing.span(name: str, **attributes: Any) -> Iterator[Any]` — a context manager, always safe to call. Attributes whose value is `None` are skipped.
  - `tracing._tracer() -> Any` — the indirection tests monkeypatch. Task 3 and Task 10 use the `spans` fixture that patches it.
  - `Settings.otel_enabled: bool = False`, `Settings.otel_exporter_otlp_endpoint: str = "http://localhost:4318"`.

- [x] **Step 1: Add the dependencies**

```bash
poetry add opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
```

Expected: `pyproject.toml` gains both under `[tool.poetry.dependencies]`, and `poetry.lock` is regenerated.

- [x] **Step 2: Write the failing tests**

Create `backend/tests/test_tracing.py`:

```python
"""Tracing is off unless asked for, and emits real spans when it is on (3.1)."""

import pytest
from app import tracing


def test_configure_is_a_noop_when_disabled(monkeypatch):
    """The default. `make test` must need no collector, and CI no service."""
    monkeypatch.setattr(tracing.settings, "otel_enabled", False)
    monkeypatch.setattr(tracing, "_configured", False)
    tracing.configure_tracing()
    assert tracing._configured is False


def test_configure_is_idempotent(monkeypatch):
    """create_app() is called per test by the client fixture; installing a second
    exporter per call would leak processors for the life of the process."""
    calls = []
    monkeypatch.setattr(tracing.settings, "otel_enabled", True)
    monkeypatch.setattr(tracing, "_configured", False)
    monkeypatch.setattr(tracing, "_install_exporter", lambda: calls.append(1))
    tracing.configure_tracing()
    tracing.configure_tracing()
    assert calls == [1]


def test_span_is_safe_to_call_with_no_provider_installed():
    """span() is called from library code that must not care whether tracing is on."""
    with tracing.span("unit.test", count=3) as current:
        assert current is not None


def test_span_records_name_and_attributes(spans):
    with tracing.span("unit.test", count=3, label="x", skipped=None):
        pass
    finished = spans.get_finished_spans()
    assert [s.name for s in finished] == ["unit.test"]
    assert finished[0].attributes["count"] == 3
    assert finished[0].attributes["label"] == "x"
    # None-valued attributes are dropped: OTel rejects None and would raise.
    assert "skipped" not in finished[0].attributes


def test_nested_spans_are_parented(spans):
    with tracing.span("outer"):
        with tracing.span("inner"):
            pass
    finished = {s.name: s for s in spans.get_finished_spans()}
    assert finished["inner"].parent.span_id == finished["outer"].context.span_id


def test_span_records_an_exception_and_re_raises(spans):
    with pytest.raises(ValueError):
        with tracing.span("boom"):
            raise ValueError("nope")
    finished = spans.get_finished_spans()
    assert finished[0].status.status_code.name == "ERROR"
```

- [x] **Step 3: Add the `spans` fixture**

Append to `backend/tests/conftest.py`:

```python
@pytest.fixture
def spans(monkeypatch):
    """An in-memory span exporter wired into app.tracing.

    Patches `tracing._tracer` rather than calling `trace.set_tracer_provider`,
    because the global provider can only be set once per process — a fixture
    that set it would work in the first test that used it and silently export
    nothing in every later one.
    """
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from app import tracing

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    monkeypatch.setattr(tracing, "_tracer", lambda: tracer)
    return exporter
```

- [x] **Step 4: Run the tests to verify they fail**

Run: `poetry run pytest backend/tests/test_tracing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.tracing'`.

- [x] **Step 5: Add the settings**

In `backend/app/config.py`, append inside `Settings` (after the `judge_model` block):

```python
    # OpenTelemetry (3.1). Off by default: `make test` must need no collector and
    # CI no service container. docker-compose already runs Jaeger with OTLP on
    # 4318 and its UI on 16686 — this is what finally sends it anything.
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"
```

In `.env.example`, append:

```bash
# OpenTelemetry (3.1). Off by default; `make db-up` already runs Jaeger.
# Traces at http://localhost:16686 once OTEL_ENABLED=true.
OTEL_ENABLED=false
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
```

- [x] **Step 6: Write `backend/app/tracing.py`**

```python
"""OpenTelemetry helpers (3.1).

The one module that imports `opentelemetry`. Two entry points: `configure_tracing`
installs the OTLP exporter at app startup, and `span` is the context manager the
rest of the backend wraps work in.

Two rules this module exists to hold:

- **Off by default.** `settings.otel_enabled` is False, so the test suite needs no
  collector and CI needs no service container. `span()` still works when nothing
  is installed — OpenTelemetry's default tracer returns a non-recording span — so
  callers never branch on whether tracing is on.
- **Attributes carry ids, counts and durations, never payloads.** No embedding
  vectors (512 floats), no note text, no user questions. A trace is for finding
  where the time and the calls went, and an exporter is a place data leaves from.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.config import settings

_configured = False

# Values OpenTelemetry accepts for an attribute. Anything else is stringified by
# the caller before it gets here; None is dropped (OTel raises on it).
_Scalar = str | bool | int | float


def _tracer() -> Any:
    """Indirection so tests can substitute a tracer bound to an in-memory
    exporter. The global tracer provider can only be set once per process, so a
    test that installed one would silently export nothing in every later test."""
    from opentelemetry import trace

    return trace.get_tracer("wavepoint")


def _install_exporter() -> None:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": "wavepoint-backend"}))
    endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/") + "/v1/traces"
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)


def configure_tracing() -> None:
    """Install the OTLP exporter. A no-op when disabled, and idempotent.

    Idempotence is not decoration: `create_app()` runs once per test in the
    `client` fixture, and a second install would add a second span processor that
    lives for the rest of the process.
    """
    global _configured
    if not settings.otel_enabled or _configured:
        return
    _install_exporter()
    _configured = True


@contextmanager
def span(name: str, **attributes: _Scalar | None) -> Iterator[Any]:
    """Run a block inside a span. Safe whether or not tracing is configured.

    `None`-valued attributes are dropped rather than passed through, so callers
    can hand optional values straight in without a conditional at each site.
    """
    with _tracer().start_as_current_span(name) as current:
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(key, value)
        yield current
```

- [x] **Step 7: Wire it into `create_app()`**

In `backend/app/main.py`, inside `create_app`, immediately before `app = FastAPI(...)`:

```python
    from app.tracing import configure_tracing

    configure_tracing()
```

- [x] **Step 8: Run the tests to verify they pass**

Run: `poetry run pytest backend/tests/test_tracing.py -v`
Expected: PASS (6 tests).

- [x] **Step 9: Run the gate**

Run: `make check`
Expected: PASS.

- [x] **Step 10: Commit**

```bash
git add backend/app/tracing.py backend/app/main.py backend/app/config.py \
        backend/tests/test_tracing.py backend/tests/conftest.py \
        .env.example pyproject.toml poetry.lock
git commit -m "feat: app/tracing.py — OTel span helpers, off by default (3.1)"
```

---

### Task 3: Retrofit spans into `app/loop.py` (3.2)

**Files:**
- Modify: `backend/app/loop.py`
- Test: `backend/tests/test_loop_tracing.py`

**Why:** This lands before the agent (Task 10) on purpose. Retrofitting spans into shipped, well-understood code proves the exporter against something whose behaviour is already known — debugging the exporter and a brand-new agent loop at the same time is how a tracing layer ends up permanently disabled.

**Interfaces:**
- Consumes: `tracing.span(name, **attributes)` from Task 2; the `spans` fixture from Task 2.
- Produces: span names `llm.loop` (root, per turn), `llm.analyst_pass`, `llm.judge_pass`, `charts.render` — the names Task 10 mirrors for the agent.

- [x] **Step 1: Write the failing test**

Create `backend/tests/test_loop_tracing.py`:

```python
"""run_loop emits spans (3.2). Proving the helpers against shipped code before
the agent depends on them."""

from app import loop


class _FakeClient:
    """Minimal stand-in: one analyst text response, one judge verdict above the
    threshold, so the loop stops after a single pass."""

    class messages:  # noqa: N801 — mirrors the anthropic client's attribute name
        @staticmethod
        def create(**kwargs):
            raise NotImplementedError


def test_run_loop_emits_a_root_span_and_one_span_per_call(spans, monkeypatch):
    from app.llm import AnalystResult, JudgeResult

    monkeypatch.setattr(
        loop,
        "analyst_call",
        lambda client, system, messages: AnalystResult(
            interpretation="looks fine",
            tool_calls=[],
            model="claude-sonnet-5",
            tokens_in=10,
            tokens_out=5,
            latency_ms=1,
        ),
    )
    monkeypatch.setattr(
        loop,
        "judge_call",
        lambda *args, **kwargs: JudgeResult(
            score=95,
            feedback="good",
            gaps=[],
            model="claude-sonnet-5",
            tokens_in=4,
            tokens_out=2,
            latency_ms=1,
        ),
    )

    result = loop.run_loop([], {}, [], "what is the mean?", client=_FakeClient())
    assert result.pass_count == 1

    names = [s.name for s in spans.get_finished_spans()]
    assert "llm.analyst_pass" in names
    assert "llm.judge_pass" in names
    assert "llm.loop" in names
    # The root closes last: every call must be inside it, or a trace shows
    # orphaned spans with no turn to attribute them to.
    assert names[-1] == "llm.loop"


def test_loop_span_carries_counts_not_payloads(spans, monkeypatch):
    """Ids, counts and durations only — never the question or the chart PNGs."""
    from app.llm import AnalystResult, JudgeResult

    monkeypatch.setattr(
        loop,
        "analyst_call",
        lambda client, system, messages: AnalystResult(
            interpretation="ok", tool_calls=[], model="m", tokens_in=1, tokens_out=1, latency_ms=1
        ),
    )
    monkeypatch.setattr(
        loop,
        "judge_call",
        lambda *args, **kwargs: JudgeResult(
            score=99, feedback="", gaps=[], model="m", tokens_in=1, tokens_out=1, latency_ms=1
        ),
    )

    loop.run_loop([], {}, [], "a question that must not appear in the trace", client=_FakeClient())
    root = next(s for s in spans.get_finished_spans() if s.name == "llm.loop")
    assert root.attributes["pass_count"] == 1
    assert root.attributes["best_score"] == 99
    serialized = repr(dict(root.attributes))
    assert "a question that must not appear" not in serialized
```

Before writing this, open `backend/app/llm.py` and confirm the exact field names and order of `AnalystResult` and `JudgeResult`; construct them with keyword arguments matching what you find, adjusting the two constructors above if the dataclasses carry fields not listed here.

- [x] **Step 2: Run the test to verify it fails**

Run: `poetry run pytest backend/tests/test_loop_tracing.py -v`
Expected: FAIL — `assert 'llm.analyst_pass' in []`.

- [x] **Step 3: Add the spans**

In `backend/app/loop.py`, add the import:

```python
from app.tracing import span
```

Wrap the pass loop's body. The `for _ in range(max(1, settings.llm_max_passes)):` block becomes:

```python
    with span("llm.loop", max_passes=settings.llm_max_passes) as loop_span:
        for _ in range(max(1, settings.llm_max_passes)):
            with span("llm.analyst_pass", pass_index=passes) as analyst_span:
                analyst = analyst_call(client, system, messages)
                passes += 1
                analyst_span.set_attribute("model", analyst.model)
                analyst_span.set_attribute("tokens_in", analyst.tokens_in)
                analyst_span.set_attribute("tokens_out", analyst.tokens_out)
                analyst_span.set_attribute("tool_calls", len(analyst.tool_calls))
            ...  # the rest of the existing pass body, indented one level
        loop_span.set_attribute("pass_count", passes)
        loop_span.set_attribute("best_score", best.judge.score if best else -1)
```

Inside that body, wrap the two remaining units of work in the same style:

- the chart-rendering call becomes `with span("charts.render", tool_calls=len(new_calls)):` around the existing render, setting `charts` and `errors` counts on the span afterwards;
- the judge call becomes `with span("llm.judge_pass", pass_index=passes) as judge_span:` around the existing `judge_call(...)`, setting `model`, `tokens_in`, `tokens_out` and `score` on the span.

Do not restructure the loop's logic — only indent it and add the four `with` blocks. Use the local variable names the file already has (`new_calls`, `verdict`, etc.); read the function before editing rather than assuming the names above.

- [x] **Step 4: Run the tests to verify they pass**

Run: `poetry run pytest backend/tests/test_loop_tracing.py backend/tests/test_loop.py -v`
Expected: PASS. The existing loop tests must be unaffected — spans change no return value.

- [x] **Step 5: Verify against Jaeger (manual, optional but recommended)**

```bash
make db-up
OTEL_ENABLED=true make dev
```
Ask a question in the chat UI, then open http://localhost:16686, pick service
`wavepoint-backend`, and confirm one `llm.loop` trace with `llm.analyst_pass`,
`charts.render` and `llm.judge_pass` children. This is the check that proves the
exporter works before Task 10 depends on it.

- [x] **Step 6: Run the gate**

Run: `make check`
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add backend/app/loop.py backend/tests/test_loop_tracing.py
git commit -m "feat: trace the analyst/judge loop (3.2)"
```

---

### Task 4: `app/embeddings.py` — chunking and the Voyage boundary (3.3a)

**Files:**
- Create: `backend/app/embeddings.py`
- Modify: `backend/app/config.py`, `.env.example`, `pyproject.toml`, `backend/tests/conftest.py`
- Test: `backend/tests/test_embeddings.py`

**Why:** `chunk_text` is a pure function of a string and is where D29 lives. `embed_texts` is the only place `voyageai` is imported, and the only place the document/query asymmetry can be got wrong — omitting it costs recall in a way that surfaces later as mediocre eval numbers, where it is hard to attribute.

**Sizing (measured):** mean run-note length is 693 characters, mean finding length 2,704–4,022. At `max_chars=1000` a note stays one chunk and a finding splits into three or four at sentence boundaries.

**Interfaces:**
- Produces:
  - `embeddings.chunk_text(text: str, max_chars: int = 1000) -> list[str]`
  - `embeddings.embed_texts(texts: list[str], *, input_type: str, client: Any | None = None) -> list[list[float]]`
  - `Settings.voyage_api_key: str = ""`, `Settings.voyage_model: str = "voyage-3.5"`
  - `fake_voyage` pytest fixture (conftest) — a client whose `.embed()` returns deterministic unit-ish vectors and records its calls.
- Consumes: `app.models.EMBEDDING_DIM`.

- [x] **Step 1: Add the dependency**

```bash
poetry add voyageai
```

- [x] **Step 2: Confirm the model name (2 minutes, do not skip)**

Check Voyage's current model list for `voyage-3.5` and its supported output
dimensions. D14 fixes the **provider** and the **512-dimension** requirement, not
the exact model string. If `voyage-3.5` has been superseded, use its successor
that still supports `output_dimension=512` and change the default in Step 4.
Anything that does not support 512 keeps D14 but costs a migration — stop and
raise it rather than changing `EMBEDDING_DIM`.

- [x] **Step 3: Write the failing tests**

Create `backend/tests/test_embeddings.py`:

```python
"""Chunking (D29) and the Voyage boundary (3.3)."""

import pytest
from app import embeddings
from app.models import EMBEDDING_DIM


def test_chunk_text_returns_nothing_for_empty_input():
    assert embeddings.chunk_text("") == []
    assert embeddings.chunk_text("   \n\n  ") == []


def test_a_short_note_stays_one_chunk():
    """Mean run-note length is 693 chars — the common case must not be split."""
    note = "Ridge at alpha=1.0 beat the baseline by 4%. " * 10  # ~430 chars
    assert len(embeddings.chunk_text(note)) == 1


def test_a_long_finding_splits_on_sentence_boundaries():
    """Mean finding length is 2,704-4,022 chars — three or four chunks."""
    sentence = "The residuals are heteroscedastic across the upper quartile of revenue. "
    chunks = embeddings.chunk_text(sentence * 60)  # ~4,300 chars
    assert len(chunks) >= 4
    # No chunk exceeds the budget, and none starts mid-sentence.
    assert all(len(c) <= 1000 for c in chunks)
    assert all(c.startswith("The residuals") for c in chunks)


def test_chunks_do_not_overlap():
    """D29: sentence boundaries already guarantee no sentence is unretrievable,
    so overlap would only duplicate text and inflate Phase 4's recall."""
    text = " ".join(f"Sentence number {i} says something." for i in range(200))
    chunks = embeddings.chunk_text(text)
    rejoined = " ".join(chunks)
    assert rejoined.count("Sentence number 7 says") == 1


def test_a_single_sentence_longer_than_the_budget_is_emitted_whole():
    """Never split mid-sentence: a half-sentence chunk retrieves as nonsense."""
    monster = "x" * 2500 + "."
    assert embeddings.chunk_text(monster) == [monster]


def test_blank_lines_are_chunk_boundaries():
    """Findings are markdown with headed sections; a heading must not be glued to
    the tail of the previous section."""
    text = "## Distribution\n\n" + ("A. " * 200) + "\n\n## Missingness\n\n" + ("B. " * 200)
    chunks = embeddings.chunk_text(text)
    assert any(c.startswith("## Missingness") for c in chunks)


def test_embed_texts_passes_the_document_input_type(fake_voyage):
    vectors = embeddings.embed_texts(["hello"], input_type="document", client=fake_voyage)
    assert len(vectors) == 1
    assert len(vectors[0]) == EMBEDDING_DIM
    assert fake_voyage.calls[0]["input_type"] == "document"
    assert fake_voyage.calls[0]["output_dimension"] == EMBEDDING_DIM


def test_embed_texts_passes_the_query_input_type(fake_voyage):
    """The asymmetry is the whole point: indexing and querying use different
    input types, and omitting it costs recall with no visible symptom."""
    embeddings.embed_texts(["hello"], input_type="query", client=fake_voyage)
    assert fake_voyage.calls[0]["input_type"] == "query"


def test_embed_texts_rejects_an_unknown_input_type(fake_voyage):
    with pytest.raises(ValueError, match="input_type"):
        embeddings.embed_texts(["hello"], input_type="passage", client=fake_voyage)


def test_embed_texts_short_circuits_on_an_empty_list(fake_voyage):
    assert embeddings.embed_texts([], input_type="document", client=fake_voyage) == []
    assert fake_voyage.calls == []


def test_embed_texts_rejects_a_wrong_width_vector(fake_voyage):
    """A provider returning 1024 floats into a VECTOR(512) column fails at INSERT
    with a message about the column, far from the cause."""
    fake_voyage.width = 8
    with pytest.raises(ValueError, match="512"):
        embeddings.embed_texts(["hello"], input_type="document", client=fake_voyage)
```

- [x] **Step 4: Add the `fake_voyage` fixture**

Append to `backend/tests/conftest.py`:

```python
class FakeVoyage:
    """Stands in for `voyageai.Client`. Records every call and returns
    deterministic vectors derived from the text, so two identical texts embed
    identically and two different ones do not — enough for the reconciliation
    tests, which care about which rows exist rather than about geometry.
    Ranking assertions use hand-built vectors instead (test_retrieval_postgres)."""

    def __init__(self, width: int | None = None) -> None:
        from app.models import EMBEDDING_DIM

        self.width = width if width is not None else EMBEDDING_DIM
        self.calls: list[dict] = []

    def embed(self, texts, model=None, input_type=None, output_dimension=None):
        self.calls.append(
            {
                "texts": list(texts),
                "model": model,
                "input_type": input_type,
                "output_dimension": output_dimension,
            }
        )

        class _Resp:
            pass

        resp = _Resp()
        resp.embeddings = [
            [float((hash(t) >> (i % 16)) % 7) / 7.0 for i in range(self.width)] for t in texts
        ]
        return resp


@pytest.fixture
def fake_voyage():
    return FakeVoyage()
```

- [x] **Step 5: Run the tests to verify they fail**

Run: `poetry run pytest backend/tests/test_embeddings.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.embeddings'`.

- [x] **Step 6: Add the settings**

In `backend/app/config.py`, append inside `Settings`:

```python
    # Voyage embeddings (D14, 3.3). 512 dimensions via Matryoshka truncation, to
    # match EMBEDDING_DIM — the column already exists at that width, so a
    # different output dimension would cost a migration rather than a config
    # change. The key is needed by `make embed` AND at request time, because
    # every agent search embeds its query.
    voyage_api_key: str = ""
    voyage_model: str = "voyage-3.5"
```

In `.env.example`, append:

```bash
# Voyage embeddings (D14). Needed by `make embed` and by POST /agent/chat, which
# embeds every search query. Never set in CI — tests mock the provider.
VOYAGE_API_KEY=
VOYAGE_MODEL=voyage-3.5
```

- [x] **Step 7: Write `backend/app/embeddings.py`**

```python
"""Chunking and embedding for the retrieval index (3.3).

The only module that imports `voyageai`. Two boundaries it holds:

- **Chunking is a pure function of a string** (D29): split on sentence
  boundaries, accumulate to ~1000 characters, no overlap. Sentence boundaries
  already guarantee no sentence is unretrievable, so overlap would duplicate
  text in the index and inflate Phase 4's recall by counting one passage twice.
- **Indexing and querying use different input types.** Voyage's models are
  trained with that asymmetry; passing "document" for a query costs recall, and
  the only symptom is mediocre eval numbers with nothing to attribute them to.
"""

import re
from typing import Any

from app.config import settings
from app.models import EMBEDDING_DIM

# Sentence enders followed by whitespace, or a blank line. Findings are markdown
# with headed sections, so a blank line has to break too — otherwise a heading is
# glued to the tail of the section above it and retrieves as that section.
_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n{2,}")

_INPUT_TYPES = ("document", "query")

DEFAULT_MAX_CHARS = 1000


def chunk_text(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[str]:
    """Split `text` into chunks of at most `max_chars`, breaking only between
    sentences (D29).

    A single sentence longer than the budget is emitted whole rather than cut:
    half a sentence retrieves as nonsense, and the embedding model truncates
    over-long input on its own terms.
    """
    stripped = text.strip()
    if not stripped:
        return []

    pieces = [p.strip() for p in _BOUNDARY.split(stripped) if p and p.strip()]
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current} {piece}" if current else piece
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = piece
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _default_client() -> Any:
    import voyageai

    if not settings.voyage_api_key:
        raise RuntimeError("VOYAGE_API_KEY is not set; embedding is unavailable")
    return voyageai.Client(api_key=settings.voyage_api_key)


def embed_texts(
    texts: list[str], *, input_type: str, client: Any | None = None
) -> list[list[float]]:
    """Embed `texts` at EMBEDDING_DIM.

    `input_type` is "document" when indexing and "query" when searching, and is
    checked rather than defaulted — a silent default is exactly the mistake that
    shows up only as a recall number nobody can explain.
    """
    if input_type not in _INPUT_TYPES:
        raise ValueError(f"input_type must be one of {_INPUT_TYPES}, got {input_type!r}")
    if not texts:
        return []

    resp = (client or _default_client()).embed(
        texts,
        model=settings.voyage_model,
        input_type=input_type,
        output_dimension=EMBEDDING_DIM,
    )
    vectors = [[float(v) for v in e] for e in resp.embeddings]
    bad = next((len(v) for v in vectors if len(v) != EMBEDDING_DIM), None)
    if bad is not None:
        # Caught here rather than at INSERT, where the error names the column and
        # says nothing about the provider that produced the wrong width.
        raise ValueError(
            f"{settings.voyage_model} returned {bad}-dimension vectors; "
            f"experiment_note_chunks.embedding is VECTOR({EMBEDDING_DIM})"
        )
    return vectors
```

- [x] **Step 8: Run the tests to verify they pass**

Run: `poetry run pytest backend/tests/test_embeddings.py -v`
Expected: PASS (11 tests).

- [x] **Step 9: Run the gate**

Run: `make check`
Expected: PASS.

- [x] **Step 10: Commit**

```bash
git add backend/app/embeddings.py backend/app/config.py backend/tests/test_embeddings.py \
        backend/tests/conftest.py .env.example pyproject.toml poetry.lock
git commit -m "feat: app/embeddings.py — sentence-boundary chunking and the Voyage boundary (3.3)"
```

---

### Task 5: The backfill is a reconciliation, not an append (3.3b)

**Files:**
- Modify: `backend/app/embeddings.py` (add `SourceText`, `BackfillReport`, `approved_sources`, `index_source`, `backfill`)
- Create: `scripts/backfill_embeddings.py`
- Modify: `Makefile` (add the `embed` target)
- Test: `backend/tests/test_backfill.py`

**Why:** Approval is not a one-way door. `PATCH /runs/{id}` (`backend/app/routes/runs.py:109–112`) and `PATCH /findings/{id}` both move a status in either direction. An append-only backfill leaves rejected text in the index **carrying `status = 'approved'`**, so it keeps ranking — D28's whole claim, that the index contains only reviewed text, quietly stops being true while every other test stays green.

**The multi-source key.** `POST /datasets/{id}/eda` can be run twice on one dataset, producing two findings that both key to `("eda", dataset_id)`; the chunk table's unique constraint on `(source_type, source_id, chunk_index)` does not allow that. The backfill concatenates every approved finding for a key, oldest first, separated by a blank line, and chunks the result as one document (spec §5.3).

**Interfaces:**
- Consumes: `chunk_text`, `embed_texts` (Task 4); `app.models.Run`, `Finding`, `ExperimentNoteChunk`.
- Produces:
  - `embeddings.SourceText(source_type: str, source_id: str, text: str)` — frozen dataclass
  - `embeddings.approved_sources(session: Session) -> list[SourceText]`
  - `embeddings.index_source(session, source: SourceText, *, client: Any | None = None) -> int`
  - `embeddings.backfill(session, *, client: Any | None = None) -> BackfillReport`
  - `embeddings.BackfillReport(indexed: int, reindexed: int, reaped: int, unchanged: int)`
  - `make embed`

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_backfill.py`:

```python
"""The backfill reconciles the index against what is currently approved (5.3).

The reaping case is the one an append-only implementation passes every other
test without, and it is the case D28 rests on.
"""

from app import embeddings
from app.models import Dataset, Experiment, ExperimentNoteChunk, Finding, Run
from sqlalchemy import select


def _chunks(session, source_type, source_id):
    return list(
        session.execute(
            select(ExperimentNoteChunk)
            .where(ExperimentNoteChunk.source_type == source_type)
            .where(ExperimentNoteChunk.source_id == source_id)
            .order_by(ExperimentNoteChunk.chunk_index)
        ).scalars()
    )


def _seed_run(session, *, notes, notes_status):
    dataset = Dataset(name="d.csv", data_csv="a,b\n1,2\n", content_hash="h", n_rows=1, n_cols=2)
    session.add(dataset)
    session.flush()
    experiment = Experiment(
        name=f"exp-{notes_status}-{id(notes)}",
        dataset_id=dataset.id,
        target_column="b",
        task_type="regression",
        primary_metric="rmse",
    )
    session.add(experiment)
    session.flush()
    run = Run(
        mlflow_run_id=f"mlf-{id(notes)}",
        experiment_id=experiment.id,
        model_type="ridge",
        notes=notes,
        notes_status=notes_status,
    )
    session.add(run)
    session.commit()
    return dataset, experiment, run


def test_an_approved_note_is_indexed(db_session, fake_voyage):
    _, _, run = _seed_run(db_session, notes="Ridge beat the baseline.", notes_status="approved")
    report = embeddings.backfill(db_session, client=fake_voyage)
    assert report.indexed == 1
    rows = _chunks(db_session, "note", run.id)
    assert len(rows) == 1
    assert rows[0].chunk_text == "Ridge beat the baseline."
    assert rows[0].status == "approved"
    assert rows[0].chunk_index == 0


def test_a_draft_note_is_not_indexed(db_session, fake_voyage):
    """D28: drafts in the index make Phase 4's precision a measurement of
    unreviewed output against itself, and the numbers look entirely normal."""
    _, _, run = _seed_run(db_session, notes="Not reviewed yet.", notes_status="draft")
    report = embeddings.backfill(db_session, client=fake_voyage)
    assert report.indexed == 0
    assert _chunks(db_session, "note", run.id) == []


def test_an_approved_but_empty_note_is_not_indexed(db_session, fake_voyage):
    _, _, run = _seed_run(db_session, notes="   ", notes_status="approved")
    embeddings.backfill(db_session, client=fake_voyage)
    assert _chunks(db_session, "note", run.id) == []


def test_a_second_run_is_a_no_op(db_session, fake_voyage):
    _, _, run = _seed_run(db_session, notes="Ridge beat the baseline.", notes_status="approved")
    embeddings.backfill(db_session, client=fake_voyage)
    report = embeddings.backfill(db_session, client=fake_voyage)
    assert report.unchanged == 1
    assert report.indexed == 0
    assert report.reindexed == 0
    assert len(_chunks(db_session, "note", run.id)) == 1


def test_edited_text_is_reindexed_and_leaves_no_orphan_chunks(db_session, fake_voyage):
    """Delete-then-insert, never upsert: text edited from four chunks down to one
    would otherwise leave chunk_index 1..3 behind, still ranking."""
    long_text = "The residual spread widens in the upper quartile. " * 90
    _, _, run = _seed_run(db_session, notes=long_text, notes_status="approved")
    embeddings.backfill(db_session, client=fake_voyage)
    assert len(_chunks(db_session, "note", run.id)) > 1

    run.notes = "Short after edit."
    db_session.commit()
    report = embeddings.backfill(db_session, client=fake_voyage)

    assert report.reindexed == 1
    rows = _chunks(db_session, "note", run.id)
    assert len(rows) == 1
    assert rows[0].chunk_text == "Short after edit."


def test_un_approving_a_note_reaps_its_chunks(db_session, fake_voyage):
    """THE test. An append-only backfill passes every other test in this file and
    leaves rejected text in the index carrying status='approved'."""
    _, _, run = _seed_run(db_session, notes="Ridge beat the baseline.", notes_status="approved")
    embeddings.backfill(db_session, client=fake_voyage)
    assert _chunks(db_session, "note", run.id) != []

    run.notes_status = "rejected"
    db_session.commit()
    report = embeddings.backfill(db_session, client=fake_voyage)

    assert report.reaped == 1
    assert _chunks(db_session, "note", run.id) == []


def test_an_approved_eda_finding_is_keyed_to_its_dataset(db_session, fake_voyage):
    """D30: eda chunks key on datasets.id, not on any run."""
    dataset, _, _ = _seed_run(db_session, notes="", notes_status="draft")
    db_session.add(
        Finding(
            source_type="eda",
            source_id=dataset.id,
            text="Revenue is right-skewed.",
            original_text="Revenue is right-skewed.",
            status="approved",
        )
    )
    db_session.commit()

    embeddings.backfill(db_session, client=fake_voyage)
    rows = _chunks(db_session, "eda", dataset.id)
    assert len(rows) == 1
    assert rows[0].chunk_text == "Revenue is right-skewed."


def test_an_approved_diagnostic_finding_is_keyed_to_its_run(db_session, fake_voyage):
    """D37: a diagnostic is scored against one trained run, not the investigation."""
    _, _, run = _seed_run(db_session, notes="", notes_status="draft")
    db_session.add(
        Finding(
            source_type="diagnostic",
            source_id=run.id,
            text="Residuals fan out above the median.",
            original_text="Residuals fan out above the median.",
            status="approved",
        )
    )
    db_session.commit()

    embeddings.backfill(db_session, client=fake_voyage)
    assert len(_chunks(db_session, "diagnostic", run.id)) == 1


def test_two_approved_findings_on_one_key_are_concatenated(db_session, fake_voyage):
    """POST /datasets/{id}/eda can be run twice. Both write ("eda", dataset_id),
    and the chunk table's unique constraint does not allow two documents there —
    so all reviewed EDA text about a dataset is chunked as one document (§5.3)."""
    dataset, _, _ = _seed_run(db_session, notes="", notes_status="draft")
    for text in ("First pass observation.", "Second pass observation."):
        db_session.add(
            Finding(
                source_type="eda",
                source_id=dataset.id,
                text=text,
                original_text=text,
                status="approved",
            )
        )
    db_session.commit()

    embeddings.backfill(db_session, client=fake_voyage)
    joined = " ".join(c.chunk_text for c in _chunks(db_session, "eda", dataset.id))
    assert "First pass observation." in joined
    assert "Second pass observation." in joined


def test_a_note_and_a_diagnostic_on_the_same_run_do_not_collide(db_session, fake_voyage):
    """Both key on runs.id; only source_type separates them."""
    _, _, run = _seed_run(db_session, notes="The note.", notes_status="approved")
    db_session.add(
        Finding(
            source_type="diagnostic",
            source_id=run.id,
            text="The diagnostic.",
            original_text="The diagnostic.",
            status="approved",
        )
    )
    db_session.commit()

    embeddings.backfill(db_session, client=fake_voyage)
    assert _chunks(db_session, "note", run.id)[0].chunk_text == "The note."
    assert _chunks(db_session, "diagnostic", run.id)[0].chunk_text == "The diagnostic."


def test_indexing_uses_the_document_input_type(db_session, fake_voyage):
    _seed_run(db_session, notes="Ridge beat the baseline.", notes_status="approved")
    embeddings.backfill(db_session, client=fake_voyage)
    assert fake_voyage.calls
    assert all(call["input_type"] == "document" for call in fake_voyage.calls)
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `poetry run pytest backend/tests/test_backfill.py -v`
Expected: FAIL with `AttributeError: module 'app.embeddings' has no attribute 'backfill'`.

Check the `Dataset`, `Experiment`, `Run` and `Finding` constructors in
`backend/app/models.py` first and adjust `_seed_run` if any required column is
missing from the calls above.

- [x] **Step 3: Implement the reconciliation**

Append to `backend/app/embeddings.py`:

```python
@dataclass(frozen=True)
class SourceText:
    """One indexable document: all currently-approved text under one chunk key."""

    source_type: str  # "note" | "eda" | "diagnostic"
    source_id: str  # runs.id for note/diagnostic, datasets.id for eda (D30)
    text: str


@dataclass(frozen=True)
class BackfillReport:
    indexed: int = 0  # keys that had no chunks and now do
    reindexed: int = 0  # keys whose text changed since it was indexed
    reaped: int = 0  # keys no longer approved, whose chunks were deleted
    unchanged: int = 0  # keys already indexed at their current text


def approved_sources(session: Session) -> list[SourceText]:
    """Every currently-approved document, keyed as D30 specifies.

    Eligibility is evaluated against the SOURCE tables, never against the chunk
    table's own denormalised `status` — that copy is what goes stale, and
    trusting it is how rejected text stays retrievable.
    """
    grouped: dict[tuple[str, str], list[str]] = {}

    runs = session.execute(select(Run).where(Run.notes_status == "approved")).scalars()
    for run in runs:
        if run.notes and run.notes.strip():
            grouped.setdefault(("note", run.id), []).append(run.notes.strip())

    # Oldest first, so a re-run produces byte-identical text and the unchanged
    # case stays unchanged rather than churning the index every time.
    findings = session.execute(
        select(Finding).where(Finding.status == "approved").order_by(Finding.created_at)
    ).scalars()
    for finding in findings:
        if finding.text and finding.text.strip():
            key = (finding.source_type, finding.source_id)
            grouped.setdefault(key, []).append(finding.text.strip())

    return [
        SourceText(source_type, source_id, "\n\n".join(parts))
        for (source_type, source_id), parts in grouped.items()
    ]


def _existing_chunks(session: Session) -> dict[tuple[str, str], list[ExperimentNoteChunk]]:
    grouped: dict[tuple[str, str], list[ExperimentNoteChunk]] = {}
    rows = session.execute(
        select(ExperimentNoteChunk).order_by(ExperimentNoteChunk.chunk_index)
    ).scalars()
    for row in rows:
        grouped.setdefault((row.source_type, row.source_id), []).append(row)
    return grouped


def _delete_key(session: Session, source_type: str, source_id: str) -> None:
    """Deletion is by source, never by row. Partial repair of one source's chunks
    is how an index ends up holding half of one revision and half of another."""
    session.execute(
        delete(ExperimentNoteChunk)
        .where(ExperimentNoteChunk.source_type == source_type)
        .where(ExperimentNoteChunk.source_id == source_id)
    )


def index_source(session: Session, source: SourceText, *, client: Any | None = None) -> int:
    """Replace one key's chunks with the chunking of `source.text`. Returns the
    chunk count. Does not commit — the caller owns the transaction."""
    chunks = chunk_text(source.text)
    _delete_key(session, source.source_type, source.source_id)
    if not chunks:
        return 0
    vectors = embed_texts(chunks, input_type="document", client=client)
    for index, (text, vector) in enumerate(zip(chunks, vectors, strict=True)):
        session.add(
            ExperimentNoteChunk(
                source_type=source.source_type,
                source_id=source.source_id,
                chunk_text=text,
                chunk_index=index,
                status="approved",
                embedding=vector,
            )
        )
    return len(chunks)


def backfill(session: Session, *, client: Any | None = None) -> BackfillReport:
    """Reconcile the index against what is currently approved.

    Three cases, and the third is the one an append-only implementation misses:

    | Case                | Action                                  |
    |---------------------|-----------------------------------------|
    | Newly approved      | chunk, embed, insert                    |
    | Edited after approval | delete the key's chunks, re-insert    |
    | No longer approved  | REAP — delete the key's chunks          |

    Without the reap, `approved -> rejected` leaves chunks in the table carrying
    `status = 'approved'`, still ranking. Serving rejected text labelled approved
    is worse than serving nothing, and it defeats D28 silently.
    """
    desired = {(s.source_type, s.source_id): s for s in approved_sources(session)}
    existing = _existing_chunks(session)
    report = BackfillReport()

    for key in existing.keys() - desired.keys():
        _delete_key(session, *key)
        report = replace(report, reaped=report.reaped + 1)

    for key, source in desired.items():
        current = [c.chunk_text for c in existing.get(key, [])]
        if current and current == chunk_text(source.text):
            report = replace(report, unchanged=report.unchanged + 1)
            continue
        index_source(session, source, client=client)
        if current:
            report = replace(report, reindexed=report.reindexed + 1)
        else:
            report = replace(report, indexed=report.indexed + 1)

    session.commit()
    return report
```

Add to the module's imports at the top of the file:

```python
from dataclasses import dataclass, replace

from app.models import EMBEDDING_DIM, ExperimentNoteChunk, Finding, Run
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `poetry run pytest backend/tests/test_backfill.py -v`
Expected: PASS (11 tests).

- [x] **Step 5: Write the script**

Create `scripts/backfill_embeddings.py`:

```python
"""Reconcile the retrieval index against what is currently approved (`make embed`).

Deliberately a script and not a route (D17): an embedding call inside
PATCH /runs/{id} would mean an approval fails when Voyage is down, turning a
local bookkeeping action into something that needs a vendor to be up.

Accepted cost: the index lags approval, and nothing detects the gap between an
approval decision and the next run of this script.
"""

import sys

from app.db import SessionLocal
from app.embeddings import backfill


def main() -> int:
    with SessionLocal() as session:
        report = backfill(session)
    print(
        f"indexed={report.indexed} reindexed={report.reindexed} "
        f"reaped={report.reaped} unchanged={report.unchanged}"
    )
    total = report.indexed + report.reindexed + report.unchanged
    if total == 0:
        print(
            "Nothing is approved yet. Approve run notes in the experiment's review "
            "dialog and findings in the findings panel, then run `make embed` again."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Confirm `SessionLocal` is exported from `backend/app/db.py`; if it is named
differently there, use the name the module actually defines.

- [x] **Step 6: Add the Makefile target**

Add `embed` to the `.PHONY` line, and append:

```make
# Reconcile the retrieval index against approved notes and findings (3.3).
# Needs VOYAGE_API_KEY and a DATABASE_URL pointing at the Postgres from db-up.
# Not a route by design (D17): an approval must not fail because Voyage is down.
embed:
	poetry run python scripts/backfill_embeddings.py
```

- [x] **Step 7: Run the gate**

Run: `make check`
Expected: PASS.

- [x] **Step 8: Run it for real (manual, needs the preconditions)**
      <!-- Partially done 2026-08-26: `make db-up` + `make embed` reach the source
      query against real Postgres and abort at the documented VOYAGE_API_KEY
      precondition without writing a row. The rows-landed check needs a key. -->

```bash
make db-up
make embed
```
With no approved text the script prints zeros and the guidance line. After
approving notes it prints non-zero `indexed`. Confirm rows landed:

```bash
docker compose exec -T postgres psql -U wavepoint -d wavepoint -tAc \
  "SELECT source_type, count(*) FROM app.experiment_note_chunks GROUP BY 1;"
```

- [x] **Step 9: Commit**

```bash
git add backend/app/embeddings.py backend/tests/test_backfill.py \
        scripts/backfill_embeddings.py Makefile
git commit -m "feat: backfill reconciles the index, including reaping un-approved text (3.3)"
```

---

### Task 6: `app/retrieval.py` — the structured stage (3.4a)

**Files:**
- Create: `backend/app/retrieval.py`
- Test: `backend/tests/test_retrieval_filters.py`

**Why:** D15 and D31: filters run against the **relational** store before the
vector store is touched, so "ridge runs on the revenue panel" is answered by a
`WHERE`, not by hoping the embedding encodes the model name. This half is pure
SQL and MLflow, and is fully testable on SQLite — the `<=>` half (Task 7) is not.

**Where each filter lives (D37 moved three of them):**

| Filter | Column | Table |
|---|---|---|
| `model_type` | `runs.model_type` | `app.runs` |
| `experiment_id` | `runs.experiment_id` | `app.runs` |
| `dataset_id` | `experiments.dataset_id` | `app.experiments` (parent) |
| `task_type` | `experiments.task_type` | `app.experiments` (parent) |
| `status` | none — MLflow's `runs.info.status` | tracking store |

`status` is the odd one out: `app.runs` has no status column, because params,
metrics and status live in MLflow (D4). It is resolved by intersecting with
`experiment_log.search_runs(None, None, [status])`.

**Interfaces:**
- Consumes: `app.experiment_log.search_runs`; `app.models.Run`, `Experiment`.
- Produces:
  - `retrieval.Filters(model_type: str | None = None, dataset_id: str | None = None, task_type: str | None = None, experiment_id: str | None = None, status: str | None = None)` — frozen dataclass
  - `retrieval.Candidates(keys: tuple[tuple[str, str], ...] | None, run_ids: tuple[str, ...], warnings: tuple[str, ...])` — frozen dataclass. **`keys is None` means unrestricted** (no filters were given), which is not the same as `keys == ()` (filters were given and matched nothing).
  - `retrieval.candidate_runs(session: Session, filters: Filters) -> Candidates`

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_retrieval_filters.py`:

```python
"""The structured stage: relational filters resolved before any vector work (D15).

Runs entirely on SQLite — nothing here touches pgvector.
"""

from app import retrieval
from app.models import Dataset, Experiment, Run


def _seed(db_session, *, dataset_name, model_type, task_type="regression", notes="n"):
    dataset = Dataset(
        name=dataset_name, data_csv="a,b\n1,2\n", content_hash=dataset_name, n_rows=1, n_cols=2
    )
    db_session.add(dataset)
    db_session.flush()
    experiment = Experiment(
        name=f"{dataset_name}-{model_type}-{task_type}",
        dataset_id=dataset.id,
        target_column="b",
        task_type=task_type,
        primary_metric="rmse",
    )
    db_session.add(experiment)
    db_session.flush()
    run = Run(
        mlflow_run_id=f"mlf-{dataset_name}-{model_type}",
        experiment_id=experiment.id,
        model_type=model_type,
        notes=notes,
        notes_status="approved",
    )
    db_session.add(run)
    db_session.commit()
    return dataset, experiment, run


def test_no_filters_means_unrestricted(db_session):
    """keys=None is 'search everything'. Returning every key instead would put an
    IN list of the whole corpus into the vector query for the common case."""
    _seed(db_session, dataset_name="panel", model_type="ridge")
    candidates = retrieval.candidate_runs(db_session, retrieval.Filters())
    assert candidates.keys is None
    assert candidates.warnings == ()


def test_model_type_filters_on_the_run(db_session):
    _, _, ridge = _seed(db_session, dataset_name="panel", model_type="ridge")
    _seed(db_session, dataset_name="panel2", model_type="random_forest")

    candidates = retrieval.candidate_runs(db_session, retrieval.Filters(model_type="ridge"))
    assert ("note", ridge.id) in candidates.keys
    assert not any(key[0] == "note" and key[1] != ridge.id for key in candidates.keys)


def test_dataset_id_filters_on_the_parent_experiment(db_session):
    """D37: dataset_id lives on app.experiments, not on app.runs. A filter that
    looked for runs.dataset_id would not compile, but one written against a
    stale mental model of the schema silently matches nothing."""
    dataset, _, run = _seed(db_session, dataset_name="panel", model_type="ridge")
    _seed(db_session, dataset_name="other", model_type="ridge")

    candidates = retrieval.candidate_runs(db_session, retrieval.Filters(dataset_id=dataset.id))
    assert ("note", run.id) in candidates.keys
    assert ("eda", dataset.id) in candidates.keys


def test_task_type_filters_on_the_parent_experiment(db_session):
    _, _, clf = _seed(
        db_session, dataset_name="c", model_type="logistic_regression", task_type="classification"
    )
    _seed(db_session, dataset_name="r", model_type="ridge", task_type="regression")

    candidates = retrieval.candidate_runs(
        db_session, retrieval.Filters(task_type="classification")
    )
    assert {key for key in candidates.keys if key[0] == "note"} == {("note", clf.id)}


def test_experiment_id_filters_on_the_run(db_session):
    _, experiment, run = _seed(db_session, dataset_name="panel", model_type="ridge")
    _seed(db_session, dataset_name="other", model_type="ridge")

    candidates = retrieval.candidate_runs(
        db_session, retrieval.Filters(experiment_id=experiment.id)
    )
    assert {key for key in candidates.keys if key[0] == "note"} == {("note", run.id)}


def test_a_matching_run_expands_to_three_chunk_keys(db_session):
    """One run makes its own note and diagnostic reachable, plus the EDA on the
    dataset its experiment was run against (D30). Without the expansion, 'what
    do we know about this data' finds run notes and never the EDA."""
    dataset, _, run = _seed(db_session, dataset_name="panel", model_type="ridge")
    candidates = retrieval.candidate_runs(db_session, retrieval.Filters(model_type="ridge"))
    assert set(candidates.keys) == {
        ("note", run.id),
        ("diagnostic", run.id),
        ("eda", dataset.id),
    }


def test_an_experiment_with_no_dataset_contributes_no_eda_key(db_session):
    """experiments.dataset_id is nullable. ("eda", None) is not a key."""
    experiment = Experiment(
        name="orphan", dataset_id=None, target_column="b", task_type="regression",
        primary_metric="rmse",
    )
    db_session.add(experiment)
    db_session.flush()
    run = Run(
        mlflow_run_id="mlf-orphan", experiment_id=experiment.id, model_type="ridge",
        notes="n", notes_status="approved",
    )
    db_session.add(run)
    db_session.commit()

    candidates = retrieval.candidate_runs(db_session, retrieval.Filters(model_type="ridge"))
    assert all(key[1] is not None for key in candidates.keys)
    assert ("eda", None) not in candidates.keys


def test_a_filter_matching_nothing_returns_empty_not_unrestricted(db_session):
    """() and None are different answers. Collapsing them turns 'no ridge runs
    exist' into 'here is everything', which reads as a confident wrong answer."""
    _seed(db_session, dataset_name="panel", model_type="ridge")
    candidates = retrieval.candidate_runs(
        db_session, retrieval.Filters(model_type="does_not_exist")
    )
    assert candidates.keys == ()
    assert candidates.run_ids == ()


def test_status_intersects_with_the_tracking_store(db_session, monkeypatch):
    _, _, finished = _seed(db_session, dataset_name="a", model_type="ridge")
    _, _, failed = _seed(db_session, dataset_name="b", model_type="ridge")
    monkeypatch.setattr(
        retrieval.experiment_log, "search_runs", lambda *a, **k: [finished.mlflow_run_id]
    )

    candidates = retrieval.candidate_runs(db_session, retrieval.Filters(status="FINISHED"))
    assert ("note", finished.id) in candidates.keys
    assert ("note", failed.id) not in candidates.keys


def test_an_unreachable_tracking_store_warns_rather_than_failing(db_session, monkeypatch):
    """The store being down must not take retrieval with it: notes and findings
    live in Postgres and are still answerable. A 503 here would make the whole
    agent unavailable because of an optional filter."""
    _, _, run = _seed(db_session, dataset_name="a", model_type="ridge")

    def boom(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(retrieval.experiment_log, "search_runs", boom)

    candidates = retrieval.candidate_runs(db_session, retrieval.Filters(status="FINISHED"))
    assert ("note", run.id) in candidates.keys  # the other filters still applied
    assert len(candidates.warnings) == 1
    assert "status" in candidates.warnings[0]
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `poetry run pytest backend/tests/test_retrieval_filters.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.retrieval'`.

Check `Dataset`'s required columns in `backend/app/models.py` and adjust `_seed`
if `n_rows`/`n_cols`/`content_hash` are named differently.

- [x] **Step 3: Write the structured stage**

Create `backend/app/retrieval.py`:

```python
"""Two-stage retrieval over reviewed experiment history (3.4).

Stage 1 (this half) resolves the structured filters relationally. Stage 2
(Task 7) runs a similarity search restricted to what stage 1 admitted.

The order matters and is D15/D31: "ridge runs on the revenue panel" is a WHERE
clause, not something to hope the embedding encoded. A pure-vector version
returns plausible text about the wrong model and reads exactly like a right
answer.
"""

from dataclasses import dataclass

from app import experiment_log
from app.models import Experiment, Run
from sqlalchemy import select
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Filters:
    """The agent's structured filters. Every field is optional; all supplied
    fields are ANDed."""

    model_type: str | None = None
    dataset_id: str | None = None
    task_type: str | None = None
    experiment_id: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class Candidates:
    """What stage 1 admits.

    `keys is None` means UNRESTRICTED — no filters were given, so stage 2
    searches the whole index. `keys == ()` means filters were given and matched
    nothing. Collapsing the two turns "no ridge runs exist" into "here is
    everything", which the agent then summarises with total confidence.
    """

    keys: tuple[tuple[str, str], ...] | None
    run_ids: tuple[str, ...]
    warnings: tuple[str, ...] = ()


def candidate_runs(session: Session, filters: Filters) -> Candidates:
    """Resolve `filters` against the relational store.

    Each matching run expands to three chunk keys (D30):
      ("note", run.id), ("diagnostic", run.id), ("eda", experiment.dataset_id)
    The EDA key is why "what do we know about this data" finds the dataset
    write-up and not only run notes.
    """
    supplied = (
        filters.model_type,
        filters.dataset_id,
        filters.task_type,
        filters.experiment_id,
        filters.status,
    )
    if not any(supplied):
        return Candidates(keys=None, run_ids=(), warnings=())

    # dataset_id and task_type live on the PARENT (D37), model_type and
    # experiment_id on the run itself.
    stmt = select(Run, Experiment).join(Experiment, Run.experiment_id == Experiment.id)
    if filters.model_type:
        stmt = stmt.where(Run.model_type == filters.model_type)
    if filters.experiment_id:
        stmt = stmt.where(Run.experiment_id == filters.experiment_id)
    if filters.dataset_id:
        stmt = stmt.where(Experiment.dataset_id == filters.dataset_id)
    if filters.task_type:
        stmt = stmt.where(Experiment.task_type == filters.task_type)

    rows = list(session.execute(stmt).all())
    warnings: list[str] = []

    if filters.status:
        # app.runs has no status column — params, metrics and status live in
        # MLflow (D4), so this is an intersection with the tracking store.
        try:
            allowed = set(experiment_log.search_runs(None, None, [filters.status]))
        except Exception as exc:  # noqa: BLE001
            # Degrade, never 503. Notes and findings are in Postgres and remain
            # answerable; failing the whole request because an OPTIONAL filter's
            # backing store is down trades a partial answer for no answer. The
            # warning reaches the response so the caller knows the filter did
            # not apply, rather than silently trusting a broader result.
            warnings.append(
                f"status filter {filters.status!r} was not applied: "
                f"the MLflow tracking store is unavailable ({exc})"
            )
        else:
            rows = [row for row in rows if row[0].mlflow_run_id in allowed]

    keys: list[tuple[str, str]] = []
    run_ids: list[str] = []
    for run, experiment in rows:
        run_ids.append(run.id)
        keys.append(("note", run.id))
        keys.append(("diagnostic", run.id))
        if experiment.dataset_id:
            keys.append(("eda", experiment.dataset_id))

    # Sorted and de-duplicated: several runs in one experiment share an EDA key,
    # and a stable order keeps the generated IN list cacheable and diffable.
    return Candidates(
        keys=tuple(sorted(set(keys))),
        run_ids=tuple(dict.fromkeys(run_ids)),
        warnings=tuple(warnings),
    )
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `poetry run pytest backend/tests/test_retrieval_filters.py -v`
Expected: PASS (10 tests).

- [x] **Step 5: Run the gate**

Run: `make check`
Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add backend/app/retrieval.py backend/tests/test_retrieval_filters.py
git commit -m "feat: retrieval stage 1 — structured filters resolved relationally (3.4)"
```

---

### Task 7: The vector stage, source grouping, and `get_run_detail` (3.4b)

**Files:**
- Modify: `backend/app/retrieval.py`, `backend/app/config.py`
- Test: `backend/tests/test_retrieval_grouping.py`

**Why:** Chunks are the retrieval unit but **sources** are the answer unit. `k`
counts sources, not chunks: a `k` of chunks lets one four-chunk finding fill the
entire context and hide three other runs, and the agent then answers from one
source while sounding comprehensive.

**The SQLite constraint.** `<=>` is a pgvector operator with no SQLite
equivalent, and the whole suite runs on SQLite. `_rank_chunks` isolates the one
call that needs it, so this task's tests monkeypatch that seam and assert on
grouping and scoring; Task 8 exercises the real SQL against Postgres.

**Interfaces:**
- Consumes: `Filters`, `Candidates`, `candidate_runs` (Task 6); `embeddings.embed_texts` (Task 4); `experiment_log.fetch_runs`.
- Produces:
  - `retrieval.Hit(source_type: str, source_id: str, run_id: str | None, experiment_id: str | None, dataset_id: str | None, snippet: str, score: float)`
  - `retrieval.search_runs(session: Session, query: str, *, filters: Filters | None = None, k: int | None = None, client: Any | None = None) -> tuple[list[Hit], list[str]]` — hits, warnings
  - `retrieval.RunDetail(run_id: str, mlflow_run_id: str, experiment_id: str, experiment_name: str, experiment_objective: str, model_type: str, status: str, params: dict[str, str], metrics: dict[str, float], cv_std: float | None, notes: str, notes_status: str)` — frozen dataclass
  - `retrieval.get_run_detail(session: Session, run_id: str) -> RunDetail`
  - `retrieval.TrackingStoreUnavailable(RuntimeError)`
  - `Settings.retrieval_top_k: int = 8`, `Settings.chunk_overfetch: int = 4`

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_retrieval_grouping.py`:

```python
"""Stage 2: grouping chunks into sources, and the run-detail lookup (3.4).

`_rank_chunks` is monkeypatched throughout — it is the one function that emits
pgvector's `<=>`, which SQLite cannot execute. Its real SQL is covered by
test_retrieval_postgres.py.
"""

import pytest
from app import retrieval
from app.models import Dataset, Experiment, ExperimentNoteChunk, Run


def _seed_run(db_session, *, model_type="ridge", notes="Ridge beat the baseline."):
    dataset = Dataset(name="d.csv", data_csv="a,b\n1,2\n", content_hash="h", n_rows=1, n_cols=2)
    db_session.add(dataset)
    db_session.flush()
    experiment = Experiment(
        name="nowcast", objective="Beat the baseline.", dataset_id=dataset.id,
        target_column="b", task_type="regression", primary_metric="rmse",
    )
    db_session.add(experiment)
    db_session.flush()
    run = Run(
        mlflow_run_id="mlf-1", experiment_id=experiment.id, model_type=model_type,
        notes=notes, notes_status="approved",
    )
    db_session.add(run)
    db_session.commit()
    return dataset, experiment, run


def _chunk(db_session, source_type, source_id, index, text):
    row = ExperimentNoteChunk(
        source_type=source_type, source_id=source_id, chunk_text=text,
        chunk_index=index, status="approved", embedding=[0.0] * 512,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _ranked(pairs):
    """Build a _rank_chunks stub returning (chunk_row, distance) pairs."""

    def stub(session, vector, keys, limit):
        return list(pairs)[:limit]

    return stub


def test_k_counts_sources_not_chunks(db_session, monkeypatch, fake_voyage):
    """A four-chunk finding must not consume the whole budget: the agent would
    answer from one source while sounding like it surveyed the history."""
    _, _, run = _seed_run(db_session)
    fat = [_chunk(db_session, "diagnostic", run.id, i, f"chunk {i}") for i in range(4)]
    lean = _chunk(db_session, "note", run.id, 0, "the note")
    monkeypatch.setattr(
        retrieval,
        "_rank_chunks",
        _ranked([(c, 0.1 + 0.01 * i) for i, c in enumerate(fat)] + [(lean, 0.5)]),
    )

    hits, _ = retrieval.search_runs(db_session, "q", k=2, client=fake_voyage)
    assert {h.source_type for h in hits} == {"diagnostic", "note"}
    assert len(hits) == 2


def test_a_source_is_scored_by_its_single_best_chunk(db_session, monkeypatch, fake_voyage):
    """Averaging punishes a long, thorough write-up for its own breadth — the
    exact document most worth surfacing."""
    _, _, run = _seed_run(db_session)
    best = _chunk(db_session, "diagnostic", run.id, 0, "bullseye")
    worst = _chunk(db_session, "diagnostic", run.id, 1, "tangent")
    monkeypatch.setattr(retrieval, "_rank_chunks", _ranked([(best, 0.05), (worst, 0.95)]))

    hits, _ = retrieval.search_runs(db_session, "q", k=5, client=fake_voyage)
    assert len(hits) == 1
    assert hits[0].score == pytest.approx(0.95)
    assert hits[0].snippet == "bullseye"


def test_hits_are_ordered_by_score_descending(db_session, monkeypatch, fake_voyage):
    _, _, run = _seed_run(db_session)
    near = _chunk(db_session, "note", run.id, 0, "near")
    far = _chunk(db_session, "diagnostic", run.id, 0, "far")
    monkeypatch.setattr(retrieval, "_rank_chunks", _ranked([(far, 0.8), (near, 0.2)]))

    hits, _ = retrieval.search_runs(db_session, "q", k=5, client=fake_voyage)
    assert [h.snippet for h in hits] == ["near", "far"]
    assert hits[0].score > hits[1].score


def test_a_hit_carries_the_ids_the_ui_deep_links_with(db_session, monkeypatch, fake_voyage):
    """3.6: an eda hit links to /datasets/{dataset_id}, a note or diagnostic hit
    to /experiments/{experiment_id}. Resolved here, where the join is already
    open, rather than by an N+1 in the route."""
    dataset, experiment, run = _seed_run(db_session)
    note = _chunk(db_session, "note", run.id, 0, "the note")
    eda = _chunk(db_session, "eda", dataset.id, 0, "the eda")
    monkeypatch.setattr(retrieval, "_rank_chunks", _ranked([(note, 0.1), (eda, 0.2)]))

    hits, _ = retrieval.search_runs(db_session, "q", k=5, client=fake_voyage)
    by_type = {h.source_type: h for h in hits}
    assert by_type["note"].run_id == run.id
    assert by_type["note"].experiment_id == experiment.id
    assert by_type["eda"].dataset_id == dataset.id
    assert by_type["eda"].run_id is None


def test_an_empty_index_returns_no_hits_and_no_error(db_session, monkeypatch, fake_voyage):
    """Before `make embed` has ever run this is the normal state. It must be an
    empty list the agent can report, not an exception."""
    monkeypatch.setattr(retrieval, "_rank_chunks", _ranked([]))
    hits, warnings = retrieval.search_runs(db_session, "q", k=5, client=fake_voyage)
    assert hits == []
    assert warnings == []


def test_filters_matching_nothing_skip_the_vector_query(db_session, monkeypatch, fake_voyage):
    """keys == () means stage 1 excluded everything. Running the similarity
    search anyway would return the whole corpus, ignoring the filter."""
    _seed_run(db_session)
    called = []
    monkeypatch.setattr(
        retrieval, "_rank_chunks", lambda *a, **k: called.append(1) or []
    )

    hits, _ = retrieval.search_runs(
        db_session, "q", filters=retrieval.Filters(model_type="nope"), client=fake_voyage
    )
    assert hits == []
    assert called == []


def test_the_query_is_embedded_with_the_query_input_type(db_session, monkeypatch, fake_voyage):
    monkeypatch.setattr(retrieval, "_rank_chunks", _ranked([]))
    retrieval.search_runs(db_session, "q", client=fake_voyage)
    assert fake_voyage.calls[0]["input_type"] == "query"


def test_stage_one_warnings_are_passed_through(db_session, monkeypatch, fake_voyage):
    _seed_run(db_session)

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(retrieval.experiment_log, "search_runs", boom)
    monkeypatch.setattr(retrieval, "_rank_chunks", _ranked([]))

    _, warnings = retrieval.search_runs(
        db_session, "q", filters=retrieval.Filters(status="FINISHED"), client=fake_voyage
    )
    assert warnings and "status" in warnings[0]


def test_get_run_detail_merges_postgres_and_mlflow(db_session, monkeypatch):
    _, experiment, run = _seed_run(db_session)
    monkeypatch.setattr(
        retrieval.experiment_log,
        "fetch_runs",
        lambda ids: {
            "mlf-1": retrieval.experiment_log.RunData(
                run_id="mlf-1",
                status="FINISHED",
                params={"alpha": "1.0"},
                metrics={"rmse": 12.5, "cv_rmse": 13.0, "cv_std": 0.4},
            )
        },
    )

    detail = retrieval.get_run_detail(db_session, run.id)
    assert detail.model_type == "ridge"
    assert detail.experiment_name == "nowcast"
    assert detail.experiment_objective == "Beat the baseline."
    assert detail.params["alpha"] == "1.0"
    assert detail.metrics["rmse"] == 12.5
    assert detail.cv_std == 0.4
    assert detail.notes_status == "approved"


def test_get_run_detail_reports_a_missing_cv_std_as_none(db_session, monkeypatch):
    """3.0 backfills the band, but runs logged before it have none. None is what
    lets the agent say "unquantified" instead of inventing a number."""
    _, _, run = _seed_run(db_session)
    monkeypatch.setattr(
        retrieval.experiment_log,
        "fetch_runs",
        lambda ids: {
            "mlf-1": retrieval.experiment_log.RunData(
                run_id="mlf-1", status="FINISHED", params={}, metrics={"rmse": 12.5}
            )
        },
    )
    assert retrieval.get_run_detail(db_session, run.id).cv_std is None


def test_get_run_detail_on_an_unknown_run_is_a_key_error(db_session):
    with pytest.raises(KeyError):
        retrieval.get_run_detail(db_session, "no-such-run")


def test_get_run_detail_raises_when_the_store_is_unreachable(db_session, monkeypatch):
    """Unlike the status FILTER, this one has no partial answer to give: the
    whole point of the call is the params and metrics MLflow holds."""
    _, _, run = _seed_run(db_session)

    def boom(ids):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(retrieval.experiment_log, "fetch_runs", boom)
    with pytest.raises(retrieval.TrackingStoreUnavailable):
        retrieval.get_run_detail(db_session, run.id)
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `poetry run pytest backend/tests/test_retrieval_grouping.py -v`
Expected: FAIL — `retrieval` has no attribute `_rank_chunks`.

- [x] **Step 3: Add the settings**

In `backend/app/config.py`, append inside `Settings`:

```python
    # Retrieval (3.4). `retrieval_top_k` counts SOURCES, not chunks: a k of
    # chunks lets one four-chunk finding fill the whole budget and hide three
    # other runs, and the agent then answers from one source while sounding
    # comprehensive. `chunk_overfetch` is the multiplier applied before grouping,
    # so k sources survive the collapse.
    retrieval_top_k: int = 8
    chunk_overfetch: int = 4
```

- [x] **Step 4: Implement stage 2**

Append to `backend/app/retrieval.py`:

```python
class TrackingStoreUnavailable(RuntimeError):
    """MLflow could not be reached for a call that has no partial answer.

    Distinct from the status-filter degradation in `candidate_runs`: there, the
    store backs one optional filter and the rest of the answer survives without
    it. Here the params and metrics ARE the answer.
    """


@dataclass(frozen=True)
class Hit:
    """One retrieved SOURCE (not one chunk), with the ids the UI deep-links on."""

    source_type: str  # "note" | "eda" | "diagnostic"
    source_id: str
    run_id: str | None  # None for an eda hit — it is about a dataset
    experiment_id: str | None
    dataset_id: str | None
    snippet: str  # the single best-matching chunk's text
    score: float  # 1.0 - cosine distance; higher is nearer


@dataclass(frozen=True)
class RunDetail:
    run_id: str
    mlflow_run_id: str
    experiment_id: str
    experiment_name: str
    experiment_objective: str
    model_type: str
    status: str
    params: dict[str, str]
    metrics: dict[str, float]
    cv_std: float | None
    notes: str
    notes_status: str


def _rank_chunks(
    session: Session, vector: list[float], keys: tuple[tuple[str, str], ...] | None, limit: int
) -> list[tuple[ExperimentNoteChunk, float]]:
    """Nearest chunks by cosine distance. THE ONLY function that emits `<=>`.

    Isolated deliberately: `<=>` is a pgvector operator with no SQLite
    equivalent, and the whole test suite runs on SQLite. Tests of grouping and
    scoring monkeypatch this seam; its real SQL is covered against Postgres in
    test_retrieval_postgres.py.
    """
    distance = ExperimentNoteChunk.embedding.cosine_distance(vector)
    stmt = select(ExperimentNoteChunk, distance.label("distance"))
    # status is denormalised onto the chunk row, but the backfill is what keeps
    # it honest (5.3) — this predicate is a second line, not the first.
    stmt = stmt.where(ExperimentNoteChunk.status == "approved")
    if keys is not None:
        stmt = stmt.where(
            tuple_(ExperimentNoteChunk.source_type, ExperimentNoteChunk.source_id).in_(keys)
        )
    stmt = stmt.order_by(distance).limit(limit)
    return [(row[0], float(row[1])) for row in session.execute(stmt).all()]


def _resolve_ids(
    session: Session, keys: set[tuple[str, str]]
) -> dict[tuple[str, str], tuple[str | None, str | None, str | None]]:
    """(run_id, experiment_id, dataset_id) per chunk key, in two queries.

    Resolved here, where the join is already open, rather than per hit in the
    route — the route version is an N+1 that only shows up under a full k.
    """
    run_ids = [source_id for source_type, source_id in keys if source_type != "eda"]
    dataset_ids = [source_id for source_type, source_id in keys if source_type == "eda"]

    by_run: dict[str, tuple[str, str | None]] = {}
    if run_ids:
        rows = session.execute(
            select(Run.id, Experiment.id, Experiment.dataset_id)
            .join(Experiment, Run.experiment_id == Experiment.id)
            .where(Run.id.in_(run_ids))
        ).all()
        by_run = {row[0]: (row[1], row[2]) for row in rows}

    resolved: dict[tuple[str, str], tuple[str | None, str | None, str | None]] = {}
    for key in keys:
        source_type, source_id = key
        if source_type == "eda":
            resolved[key] = (None, None, source_id if source_id in dataset_ids else None)
        else:
            experiment_id, dataset_id = by_run.get(source_id, (None, None))
            resolved[key] = (source_id, experiment_id, dataset_id)
    return resolved


def search_runs(
    session: Session,
    query: str,
    *,
    filters: Filters | None = None,
    k: int | None = None,
    client: Any | None = None,
) -> tuple[list[Hit], list[str]]:
    """Two-stage retrieval. Returns (hits, warnings); `k` counts SOURCES."""
    filters = filters or Filters()
    k = k or settings.retrieval_top_k

    candidates = candidate_runs(session, filters)
    warnings = list(candidates.warnings)
    if candidates.keys is not None and not candidates.keys:
        # Stage 1 excluded everything. Running the similarity search anyway
        # would search the whole corpus and silently ignore the filter.
        return [], warnings

    vector = embed_texts([query], input_type="query", client=client)[0]
    ranked = _rank_chunks(session, vector, candidates.keys, k * settings.chunk_overfetch)

    # Group chunks into sources, scoring each by its SINGLE BEST chunk. Averaging
    # would punish a long, thorough write-up for its own breadth — which is the
    # document most worth surfacing.
    best: dict[tuple[str, str], tuple[ExperimentNoteChunk, float]] = {}
    for chunk, distance in ranked:
        key = (chunk.source_type, chunk.source_id)
        if key not in best or distance < best[key][1]:
            best[key] = (chunk, distance)

    ordered = sorted(best.items(), key=lambda item: item[1][1])[:k]
    ids = _resolve_ids(session, {key for key, _ in ordered})

    hits = []
    for key, (chunk, distance) in ordered:
        run_id, experiment_id, dataset_id = ids[key]
        hits.append(
            Hit(
                source_type=key[0],
                source_id=key[1],
                run_id=run_id,
                experiment_id=experiment_id,
                dataset_id=dataset_id,
                snippet=chunk.chunk_text,
                score=1.0 - distance,
            )
        )
    return hits, warnings


def get_run_detail(session: Session, run_id: str) -> RunDetail:
    """One run's full record: our row, its parent investigation, and MLflow's
    params and metrics."""
    row = session.execute(
        select(Run, Experiment)
        .join(Experiment, Run.experiment_id == Experiment.id)
        .where(Run.id == run_id)
    ).first()
    if row is None:
        raise KeyError(run_id)
    run, experiment = row

    try:
        data = experiment_log.fetch_runs([run.mlflow_run_id]).get(run.mlflow_run_id)
    except Exception as exc:  # noqa: BLE001
        raise TrackingStoreUnavailable(str(exc)) from exc

    metrics = dict(data.metrics) if data else {}
    return RunDetail(
        run_id=run.id,
        mlflow_run_id=run.mlflow_run_id,
        experiment_id=experiment.id,
        experiment_name=experiment.name,
        experiment_objective=experiment.objective,
        model_type=run.model_type,
        status=data.status if data else "UNKNOWN",
        params=dict(data.params) if data else {},
        metrics=metrics,
        # None, never 0.0. "unquantified" is a thing the agent can say; a
        # fabricated zero band makes every difference look significant.
        cv_std=metrics.get("cv_std"),
        notes=run.notes,
        notes_status=run.notes_status,
    )
```

Extend the module's imports:

```python
from typing import Any

from app.config import settings
from app.embeddings import embed_texts
from app.models import Experiment, ExperimentNoteChunk, Run
from sqlalchemy import select, tuple_
```

- [x] **Step 5: Run the tests to verify they pass**

Run: `poetry run pytest backend/tests/test_retrieval_grouping.py -v`
Expected: PASS (12 tests).

If `ExperimentNoteChunk.embedding.cosine_distance(...)` raises on SQLite at
*import* time rather than at execution, move the `distance` expression inside
`_rank_chunks` (it already is) and confirm nothing at module scope touches it —
the monkeypatched tests must never execute that line.

- [x] **Step 6: Run the gate**

Run: `make check`
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add backend/app/retrieval.py backend/app/config.py \
        backend/tests/test_retrieval_grouping.py
git commit -m "feat: retrieval stage 2 — source grouping, best-chunk scoring, run detail (3.4)"
```

---

### Task 8: A Postgres CI job for the pgvector half (3.7)

**Files:**
- Create: `backend/tests/test_retrieval_postgres.py`
- Modify: `pyproject.toml`, `.github/workflows/ci.yml`

**Why:** `_rank_chunks` is the only function in the codebase whose correctness
**cannot** be shown on SQLite, and it is the one every retrieval result passes
through. Task 7's tests monkeypatch it, so a wrong ORDER BY, a `<->` where `<=>`
belongs, or a broken `tuple_(...).in_(...)` ships completely green. This task
gives that function a real database.

**Why hand-built vectors.** Random vectors in 512 dimensions are near-orthogonal
with overwhelming probability, so a random-vector test passes under an incorrect
distance operator about as often as under a correct one — and fails
intermittently for reasons nobody can reproduce. Every vector here is
constructed at a known angle, so the expected ordering is arithmetic.

- [x] **Step 1: Register the marker**

In `pyproject.toml`, under `[tool.pytest.ini_options]`, add:

```toml
markers = [
    "postgres: needs a real Postgres with pgvector (set POSTGRES_TEST_URL); skipped otherwise",
]
```

Without this, `make check` fails under `-W error::pytest.PytestUnknownMarkWarning`
on some configurations, and warns on all of them.

- [x] **Step 2: Write the tests**

Create `backend/tests/test_retrieval_postgres.py`:

```python
"""The pgvector half of retrieval, against a real Postgres (3.7).

Skipped unless POSTGRES_TEST_URL is set. Locally:

    make db-up
    POSTGRES_TEST_URL=postgresql+psycopg2://wavepoint:wavepoint@localhost:5433/wavepoint \\
      poetry run pytest -m postgres -v

Every vector below is HAND-BUILT at a known angle. Random vectors in 512
dimensions are near-orthogonal with overwhelming probability, so a random-vector
test passes under a wrong distance operator about as often as under the right
one — and then fails intermittently for reasons nobody can reproduce.
"""

import math
import os

import pytest
from app import retrieval
from app.models import Base, Dataset, Experiment, ExperimentNoteChunk, Run
from app.models import EMBEDDING_DIM
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.postgres

POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL", "")


def _unit(angle_degrees: float) -> list[float]:
    """A unit vector in the plane spanned by the first two axes, at a known
    angle from axis 0. Cosine distance to `_unit(0)` is exactly
    1 - cos(angle), so every assertion below is arithmetic rather than luck."""
    radians = math.radians(angle_degrees)
    vector = [0.0] * EMBEDDING_DIM
    vector[0] = math.cos(radians)
    vector[1] = math.sin(radians)
    return vector


@pytest.fixture(scope="module")
def pg_engine():
    if not POSTGRES_TEST_URL:
        pytest.skip("POSTGRES_TEST_URL is not set")
    engine = create_engine(POSTGRES_TEST_URL, future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS app"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def pg_session(pg_engine):
    """A session on a transaction that is always rolled back, so the tests leave
    the developer's dev database exactly as they found it."""
    connection = pg_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _seed(session, *, model_type="ridge"):
    dataset = Dataset(
        name="d.csv", data_csv="a,b\n1,2\n", content_hash=f"h-{model_type}", n_rows=1, n_cols=2
    )
    session.add(dataset)
    session.flush()
    experiment = Experiment(
        name=f"exp-{model_type}", dataset_id=dataset.id, target_column="b",
        task_type="regression", primary_metric="rmse",
    )
    session.add(experiment)
    session.flush()
    run = Run(
        mlflow_run_id=f"mlf-{model_type}", experiment_id=experiment.id,
        model_type=model_type, notes="n", notes_status="approved",
    )
    session.add(run)
    session.flush()
    return dataset, experiment, run


def _chunk(session, source_type, source_id, index, textval, vector, status="approved"):
    row = ExperimentNoteChunk(
        source_type=source_type, source_id=source_id, chunk_text=textval,
        chunk_index=index, status=status, embedding=vector,
    )
    session.add(row)
    session.flush()
    return row


def test_the_vector_column_round_trips_at_512_dimensions(pg_session):
    _, _, run = _seed(pg_session)
    row = _chunk(pg_session, "note", run.id, 0, "t", _unit(0))
    pg_session.expire(row)
    assert len(row.embedding) == EMBEDDING_DIM


def test_chunks_come_back_nearest_first(pg_session):
    """The operator and the ORDER BY direction, together. `<->` instead of `<=>`
    or a DESC here returns the LEAST relevant text, confidently."""
    _, _, run = _seed(pg_session)
    near = _chunk(pg_session, "note", run.id, 0, "near", _unit(10))
    mid = _chunk(pg_session, "note", run.id, 1, "mid", _unit(60))
    far = _chunk(pg_session, "note", run.id, 2, "far", _unit(150))

    ranked = retrieval._rank_chunks(pg_session, _unit(0), None, 10)
    assert [chunk.chunk_text for chunk, _ in ranked] == ["near", "mid", "far"]
    assert [near.id, mid.id, far.id]  # rows were really written


def test_the_distance_is_cosine_and_matches_the_known_angle(pg_session):
    """1 - cos(60 degrees) = 0.5. A euclidean operator on unit vectors gives
    1.0 here, so this catches `<->` even when the ordering happens to agree."""
    _, _, run = _seed(pg_session)
    _chunk(pg_session, "note", run.id, 0, "sixty", _unit(60))

    ranked = retrieval._rank_chunks(pg_session, _unit(0), None, 10)
    assert ranked[0][1] == pytest.approx(0.5, abs=1e-6)


def test_scores_are_one_minus_distance(pg_session, monkeypatch, fake_voyage):
    """End to end through search_runs, with the real operator underneath."""
    _, _, run = _seed(pg_session)
    _chunk(pg_session, "note", run.id, 0, "sixty", _unit(60))
    monkeypatch.setattr(
        retrieval, "embed_texts", lambda texts, *, input_type, client=None: [_unit(0)]
    )

    hits, _ = retrieval.search_runs(pg_session, "q", k=5, client=fake_voyage)
    assert hits[0].score == pytest.approx(0.5, abs=1e-6)


def test_the_key_restriction_really_restricts(pg_session):
    """tuple_(source_type, source_id).in_(keys) — a composite IN. If it silently
    matched everything, every filtered search would quietly return the whole
    corpus, and Task 7's monkeypatched tests could never see it."""
    _, _, ridge = _seed(pg_session, model_type="ridge")
    _, _, forest = _seed(pg_session, model_type="random_forest")
    _chunk(pg_session, "note", ridge.id, 0, "ridge note", _unit(5))
    _chunk(pg_session, "note", forest.id, 0, "forest note", _unit(1))

    ranked = retrieval._rank_chunks(pg_session, _unit(0), (("note", ridge.id),), 10)
    assert [chunk.chunk_text for chunk, _ in ranked] == ["ridge note"]


def test_a_key_restriction_does_not_leak_across_source_types(pg_session):
    """Both a note and a diagnostic key on runs.id; only source_type separates
    them. A restriction on source_id alone would return both."""
    _, _, run = _seed(pg_session)
    _chunk(pg_session, "note", run.id, 0, "the note", _unit(5))
    _chunk(pg_session, "diagnostic", run.id, 0, "the diagnostic", _unit(1))

    ranked = retrieval._rank_chunks(pg_session, _unit(0), (("note", run.id),), 10)
    assert [chunk.chunk_text for chunk, _ in ranked] == ["the note"]


def test_unapproved_chunks_are_never_ranked(pg_session):
    """Second line of defence behind the backfill's reaping (5.3). D28 is the
    claim that only reviewed text is retrievable, and it must hold even if a
    stale row survives."""
    _, _, run = _seed(pg_session)
    _chunk(pg_session, "note", run.id, 0, "draft text", _unit(1), status="draft")
    _chunk(pg_session, "note", run.id, 1, "approved text", _unit(80))

    ranked = retrieval._rank_chunks(pg_session, _unit(0), None, 10)
    assert [chunk.chunk_text for chunk, _ in ranked] == ["approved text"]


def test_the_limit_is_applied_in_the_database(pg_session):
    """Over-fetch is k * chunk_overfetch, not the whole table."""
    _, _, run = _seed(pg_session)
    for i in range(10):
        _chunk(pg_session, "note", run.id, i, f"chunk {i}", _unit(i))

    assert len(retrieval._rank_chunks(pg_session, _unit(0), None, 3)) == 3
```

- [x] **Step 3: Run them locally**

```bash
make db-up
POSTGRES_TEST_URL=postgresql+psycopg2://wavepoint:wavepoint@localhost:5433/wavepoint \
  poetry run pytest -m postgres -v
```
Expected: PASS (8 tests). Without the variable: 8 skipped.

- [x] **Step 4: Confirm `make check` still ignores them**

Run: `make check`
Expected: PASS, with the postgres tests **skipped** — `POSTGRES_TEST_URL` is not
set, and no developer should need Docker running to run the default suite.

- [x] **Step 5: Add the CI job**

In `.github/workflows/ci.yml`, add a third job alongside `backend` and `frontend`:

```yaml
  backend-postgres:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_USER: wavepoint
          POSTGRES_PASSWORD: wavepoint
          POSTGRES_DB: wavepoint
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U wavepoint"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pipx install poetry
      - run: poetry install --no-interaction
      # The pgvector half of retrieval cannot run on SQLite: `<=>` is a
      # Postgres operator, so the default suite monkeypatches _rank_chunks and
      # a wrong operator or ORDER BY would ship green.
      - name: Run the pgvector tests
        env:
          POSTGRES_TEST_URL: postgresql+psycopg2://wavepoint:wavepoint@localhost:5432/wavepoint
        run: poetry run pytest -m postgres -v
```

Match the existing jobs' checkout/setup/cache steps rather than the sketch above
where they differ — copy the `backend` job's Python setup and `.venv` cache
verbatim so all three stay consistent.

No `VOYAGE_API_KEY` and no `ANTHROPIC_API_KEY`: nothing in this job embeds
anything. Vectors are hand-built and `embed_texts` is monkeypatched.

- [x] **Step 6: Commit and confirm CI is green**

```bash
git add backend/tests/test_retrieval_postgres.py pyproject.toml .github/workflows/ci.yml
git commit -m "test: exercise the pgvector half of retrieval against real Postgres in CI (3.7)"
git push
gh pr checks --watch
```
Expected: three jobs, all green. If `backend-postgres` reports 8 skipped rather
than 8 passed, the env var is not reaching pytest — fix that before moving on, or
the job is decoration.

---

### Task 9: `prompts/agent.md` and the two tool schemas (3.5a)

**Files:**
- Create: `backend/app/agent.py`, `prompts/agent.md`
- Test: `backend/tests/test_agent_tools.py`

**Why:** Tool schemas and validation are pure functions of their arguments and
are worth a gate of their own, separately from the loop that calls them. The
prompt is where three failure modes are headed off: an answer with no citations,
a difference reported as significant when `cv_std` is null, and a confident
answer when retrieval returned nothing.

**Tool naming (D41):** the tools are `search_runs` and `get_run_detail`. Not
`search_experiments` — since D33 an "experiment" is an investigation, and a tool
by that name would make the model search for investigations when it wants runs.

**Interfaces:**
- Consumes: `retrieval.Filters`, `retrieval.search_runs`, `retrieval.get_run_detail` (Tasks 6–7).
- Produces:
  - `agent.TOOLS: list[dict[str, Any]]` — Anthropic tool schemas
  - `agent.validate_tool_call(name: str, args: dict[str, Any]) -> str | None` — returns an error **string** on rejection, `None` when valid
  - `agent.load_system_prompt() -> str`

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_agent_tools.py`:

```python
"""Tool schemas, argument validation, and the agent's system prompt (3.5)."""

from app import agent


def test_the_two_tools_are_named_for_runs_not_experiments():
    """D41: since D33 an 'experiment' is an INVESTIGATION. A tool called
    search_experiments makes the model search for investigations when what it
    wants is runs, and the mistake is invisible in the transcript."""
    assert {tool["name"] for tool in agent.TOOLS} == {"search_runs", "get_run_detail"}


def test_search_runs_requires_only_a_query():
    schema = next(t for t in agent.TOOLS if t["name"] == "search_runs")
    assert schema["input_schema"]["required"] == ["query"]
    properties = schema["input_schema"]["properties"]
    for name in ("model_type", "dataset_id", "task_type", "experiment_id", "status", "k"):
        assert name in properties


def test_get_run_detail_requires_a_run_id():
    schema = next(t for t in agent.TOOLS if t["name"] == "get_run_detail")
    assert schema["input_schema"]["required"] == ["run_id"]


def test_every_tool_has_a_description():
    """The description is the model's only documentation of when to use a tool."""
    assert all(tool["description"].strip() for tool in agent.TOOLS)


def test_a_valid_search_call_passes():
    assert agent.validate_tool_call("search_runs", {"query": "ridge on the panel"}) is None


def test_a_missing_query_is_rejected():
    error = agent.validate_tool_call("search_runs", {})
    assert error is not None
    assert "query" in error


def test_an_unknown_tool_is_rejected():
    error = agent.validate_tool_call("drop_tables", {"query": "x"})
    assert error is not None
    assert "drop_tables" in error


def test_an_unknown_argument_is_rejected_by_name():
    """The error string goes back to the model as the tool result, so it has to
    say which argument was wrong — 'invalid arguments' gives it nothing to
    correct and it retries the same call."""
    error = agent.validate_tool_call("search_runs", {"query": "x", "modle_type": "ridge"})
    assert error is not None
    assert "modle_type" in error


def test_a_non_integer_k_is_rejected():
    error = agent.validate_tool_call("search_runs", {"query": "x", "k": "many"})
    assert error is not None
    assert "k" in error


def test_validation_returns_a_string_and_never_raises():
    """A raised exception ends the turn with a 500. A returned string goes back
    as the tool result and the model corrects itself on the next turn."""
    for args in ({}, {"query": 5}, {"query": "x", "k": -1}, None):
        result = agent.validate_tool_call("search_runs", args if args is not None else {})
        assert result is None or isinstance(result, str)


def test_the_system_prompt_demands_citations():
    prompt = agent.load_system_prompt().lower()
    assert "cite" in prompt or "citation" in prompt


def test_the_system_prompt_covers_the_missing_cv_std_case():
    """The band is absent on runs logged before 3.0. Without this instruction the
    model reports a difference as significant because nothing said it could not."""
    prompt = agent.load_system_prompt().lower()
    assert "unquantified" in prompt


def test_the_system_prompt_covers_the_empty_retrieval_case():
    """Before `make embed` has run, retrieval returns nothing. The model must say
    so rather than answer from its own priors about ridge regression."""
    prompt = agent.load_system_prompt().lower()
    assert "no reviewed history" in prompt
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `poetry run pytest backend/tests/test_agent_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.agent'`.

- [x] **Step 3: Write the system prompt**

Create `prompts/agent.md`:

```markdown
You answer questions about this project's machine-learning experiment history.

You have two tools:

- `search_runs` — semantic search over **reviewed** write-ups: run notes, EDA
  findings, and diagnostic interpretations that a human has approved. Pass
  structured filters (`model_type`, `dataset_id`, `task_type`, `experiment_id`,
  `status`) whenever the question names one; they are applied as database
  filters before the search, and are far more reliable than hoping the phrasing
  matches.
- `get_run_detail` — one run's parameters, metrics and notes, by its run id.
  Use it after a search when you need exact numbers. Search returns snippets,
  not the full record.

Vocabulary, and it matters: an **experiment** is an *investigation* — one
question, many attempts. A **run** is one training attempt inside it. When
someone asks "which model won", they are asking about runs.

How to answer:

1. **Search before answering.** Every claim about this project's history comes
   from a tool result. You know a great deal about machine learning in general;
   none of it tells you what happened in *this* repository.
2. **Cite the runs you used.** Name the model and the experiment, and give the
   metric with its value. A reader must be able to check you.
3. **Respect the error bars.** Metrics are reported with `cv_std`, the
   cross-validation standard deviation. A gap smaller than that is noise — say
   so. When `cv_std` is absent, say the difference is **unquantified**; do not
   describe it as significant, and do not invent a band.
4. **When retrieval comes back empty, say so.** Answer: there is **no reviewed
   history** matching that question — perhaps nothing has been approved yet.
   Then stop. Do not fall back on general knowledge dressed as project history.
5. **Report what the notes say, including disagreement.** If two approved
   write-ups conflict, present both rather than picking one.

Be concise. A short answer with two real citations beats a long one with none.
```

- [x] **Step 4: Write the schemas and the validator**

Create `backend/app/agent.py`:

```python
"""The retrieval agent: tool schemas, validation, and (Task 10) the loop.

Tool naming is D41. The tools are `search_runs` and `get_run_detail`, not
`search_experiments` — since D33 an "experiment" is an investigation containing
many runs, so a tool by the old name would make the model search for
investigations when what it wants is runs, and nothing in the transcript would
look wrong.
"""

from pathlib import Path
from typing import Any

_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "agent.md"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_runs",
        "description": (
            "Semantic search over reviewed write-ups about this project's training "
            "runs: approved run notes, EDA findings, and diagnostic interpretations. "
            "Supply the structured filters whenever the question names one — they are "
            "applied as database filters before the search runs. Returns snippets, not "
            "full records; follow up with get_run_detail for exact numbers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to look for, in natural language.",
                },
                "model_type": {
                    "type": "string",
                    "description": "Restrict to one model, e.g. 'ridge' or 'persistence'.",
                },
                "dataset_id": {
                    "type": "string",
                    "description": "Restrict to runs whose experiment used this dataset.",
                },
                "task_type": {
                    "type": "string",
                    "description": "'regression' or 'classification'.",
                },
                "experiment_id": {
                    "type": "string",
                    "description": "Restrict to one investigation.",
                },
                "status": {
                    "type": "string",
                    "description": "MLflow run status, e.g. 'FINISHED' or 'FAILED'.",
                },
                "k": {
                    "type": "integer",
                    "description": "How many sources to return. Defaults to 8.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_run_detail",
        "description": (
            "One run's full record: its parameters, its metrics with cross-validation "
            "bands, its parent investigation, and its reviewed notes. Takes the run_id "
            "returned by search_runs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "The run's id."},
            },
            "required": ["run_id"],
        },
    },
]

_SCHEMAS = {tool["name"]: tool["input_schema"] for tool in TOOLS}

_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
}


def load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def validate_tool_call(name: str, args: dict[str, Any]) -> str | None:
    """Check `args` against the tool's schema.

    Returns an error STRING, never raises. The string is sent back as the tool
    result, so the model sees its own mistake and corrects it on the next turn;
    an exception here ends the request with a 500 and loses the conversation.
    The message names the offending argument for the same reason — "invalid
    arguments" gives the model nothing to act on, so it retries the same call.
    """
    schema = _SCHEMAS.get(name)
    if schema is None:
        return f"Unknown tool {name!r}. Available tools: {', '.join(sorted(_SCHEMAS))}."

    properties: dict[str, Any] = schema["properties"]
    unknown = sorted(set(args) - set(properties))
    if unknown:
        return (
            f"Unknown argument(s) for {name}: {', '.join(unknown)}. "
            f"Valid arguments: {', '.join(sorted(properties))}."
        )

    missing = [key for key in schema["required"] if not str(args.get(key, "")).strip()]
    if missing:
        return f"{name} requires {', '.join(missing)}."

    for key, value in args.items():
        expected = _TYPES[properties[key]["type"]]
        # bool is a subclass of int; True is not a valid k.
        if isinstance(value, bool) or not isinstance(value, expected):
            return f"{name}: {key} must be a {properties[key]['type']}, got {type(value).__name__}."

    k = args.get("k")
    if isinstance(k, int) and k < 1:
        return f"{name}: k must be at least 1, got {k}."

    return None
```

- [x] **Step 5: Run the tests to verify they pass**

Run: `poetry run pytest backend/tests/test_agent_tools.py -v`
Expected: PASS (13 tests).

- [x] **Step 6: Run the gate**

Run: `make check`
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add backend/app/agent.py prompts/agent.md backend/tests/test_agent_tools.py
git commit -m "feat: agent tool schemas, argument validation, and system prompt (3.5)"
```

---

### Task 10: `run_agent()` — the hand-rolled loop (3.5b)

**Files:**
- Modify: `backend/app/agent.py`, `backend/app/config.py`
- Test: `backend/tests/test_agent_loop.py`

**Why:** This is the deliverable the phase is named for: a loop we wrote, whose
every turn is inspectable. It is deliberately **not** `app/loop.py` — that loop
is judge-gated and renders charts, and merging them would make each one carry the
other's concerns.

**The cap and the forced answer.** `agent_max_turns` bounds the tool loop. On
hitting it, the loop makes **one more call with the tools removed**, and that
call does not count against the cap — otherwise a model that used its whole
budget searching returns an empty answer, which looks like a backend failure and
is the single most confusing outcome for a user.

**Interfaces:**
- Consumes: `TOOLS`, `validate_tool_call`, `load_system_prompt` (Task 9); `retrieval.search_runs`, `retrieval.get_run_detail`, `retrieval.Filters` (Tasks 6–7); `tracing.span` (Task 2).
- Produces:
  - `agent.AgentStep(type: str, model: str, tokens_in: int, tokens_out: int, latency_ms: int, tool_name: str | None, tool_args: dict[str, Any] | None, result_summary: str | None, error: str | None)`
  - `agent.AgentResult(answer: str, retrieved: list[retrieval.Hit], warnings: list[str], steps: list[AgentStep], tokens_in: int, tokens_out: int, cost_usd: float, latency_ms: int)`
  - `agent.run_agent(question: str, session: Session, *, client: Any | None = None) -> AgentResult`
  - `Settings.agent_max_turns: int = 6`

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_agent_loop.py`:

```python
"""The hand-rolled agent loop (3.5).

The Anthropic client is a stub throughout — no test in this file needs a key.
"""

from types import SimpleNamespace

from app import agent, retrieval


class _Block(SimpleNamespace):
    pass


def _text(value):
    return _Block(type="text", text=value)


def _tool_use(name, args, tool_id="t1"):
    return _Block(type="tool_use", name=name, input=args, id=tool_id)


class FakeAnthropic:
    """Returns a scripted response per call and records what it was sent."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        content, stop_reason = self._responses.pop(0)
        return SimpleNamespace(
            content=content,
            stop_reason=stop_reason,
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


def _hit(snippet="a note", run_id="run-1"):
    return retrieval.Hit(
        source_type="note", source_id=run_id, run_id=run_id,
        experiment_id="exp-1", dataset_id="ds-1", snippet=snippet, score=0.9,
    )


def test_a_direct_answer_needs_no_tools(db_session):
    client = FakeAnthropic([([_text("No reviewed history matches that.")], "end_turn")])
    result = agent.run_agent("anything?", db_session, client=client)
    assert result.answer == "No reviewed history matches that."
    assert [step.type for step in result.steps] == ["llm"]


def test_a_search_call_is_executed_and_fed_back(db_session, monkeypatch):
    monkeypatch.setattr(retrieval, "search_runs", lambda *a, **k: ([_hit()], []))
    client = FakeAnthropic(
        [
            ([_tool_use("search_runs", {"query": "ridge"})], "tool_use"),
            ([_text("Ridge won, per run-1.")], "end_turn"),
        ]
    )

    result = agent.run_agent("which model won?", db_session, client=client)
    assert result.answer == "Ridge won, per run-1."
    assert [step.type for step in result.steps] == ["llm", "tool", "llm"]
    # The second call carries the tool result back.
    assert len(client.calls[1]["messages"]) > len(client.calls[0]["messages"])


def test_retrieved_hits_are_accumulated_across_calls(db_session, monkeypatch):
    """The response's `retrieved` list is what the UI deep-links from. Keeping
    only the last search's hits would drop citations the answer actually used."""
    hits = iter([([_hit(run_id="run-1")], []), ([_hit(run_id="run-2")], [])])
    monkeypatch.setattr(retrieval, "search_runs", lambda *a, **k: next(hits))
    client = FakeAnthropic(
        [
            ([_tool_use("search_runs", {"query": "a"}, "t1")], "tool_use"),
            ([_tool_use("search_runs", {"query": "b"}, "t2")], "tool_use"),
            ([_text("Both.")], "end_turn"),
        ]
    )

    result = agent.run_agent("q", db_session, client=client)
    assert {hit.run_id for hit in result.retrieved} == {"run-1", "run-2"}


def test_a_duplicate_hit_is_not_listed_twice(db_session, monkeypatch):
    monkeypatch.setattr(retrieval, "search_runs", lambda *a, **k: ([_hit()], []))
    client = FakeAnthropic(
        [
            ([_tool_use("search_runs", {"query": "a"}, "t1")], "tool_use"),
            ([_tool_use("search_runs", {"query": "b"}, "t2")], "tool_use"),
            ([_text("Done.")], "end_turn"),
        ]
    )
    result = agent.run_agent("q", db_session, client=client)
    assert len(result.retrieved) == 1


def test_an_invalid_tool_call_returns_the_error_to_the_model(db_session):
    """The model gets a correctable message, not a 500. This is the difference
    between one wasted turn and a failed request."""
    client = FakeAnthropic(
        [
            ([_tool_use("search_runs", {})], "tool_use"),
            ([_text("Sorry — retrying.")], "end_turn"),
        ]
    )
    result = agent.run_agent("q", db_session, client=client)
    tool_step = next(step for step in result.steps if step.type == "tool")
    assert tool_step.error is not None
    assert "query" in tool_step.error
    assert result.answer == "Sorry — retrying."


def test_a_tool_that_raises_becomes_an_error_result_not_a_500(db_session, monkeypatch):
    def boom(*a, **k):
        raise retrieval.TrackingStoreUnavailable("connection refused")

    monkeypatch.setattr(retrieval, "get_run_detail", boom)
    client = FakeAnthropic(
        [
            ([_tool_use("get_run_detail", {"run_id": "run-1"})], "tool_use"),
            ([_text("The tracking store is down.")], "end_turn"),
        ]
    )

    result = agent.run_agent("q", db_session, client=client)
    tool_step = next(step for step in result.steps if step.type == "tool")
    assert "connection refused" in tool_step.error
    assert result.answer == "The tracking store is down."


def test_an_unknown_run_id_is_reported_to_the_model(db_session, monkeypatch):
    def missing(session, run_id):
        raise KeyError(run_id)

    monkeypatch.setattr(retrieval, "get_run_detail", missing)
    client = FakeAnthropic(
        [
            ([_tool_use("get_run_detail", {"run_id": "nope"})], "tool_use"),
            ([_text("That run does not exist.")], "end_turn"),
        ]
    )
    result = agent.run_agent("q", db_session, client=client)
    tool_step = next(step for step in result.steps if step.type == "tool")
    assert "nope" in tool_step.error


def test_hitting_the_turn_cap_still_produces_an_answer(db_session, monkeypatch):
    """THE cap test. Without the forced final call the user gets an empty answer,
    which is indistinguishable from a backend failure."""
    monkeypatch.setattr(agent.settings, "agent_max_turns", 2)
    monkeypatch.setattr(retrieval, "search_runs", lambda *a, **k: ([_hit()], []))
    client = FakeAnthropic(
        [
            ([_tool_use("search_runs", {"query": "a"}, "t1")], "tool_use"),
            ([_tool_use("search_runs", {"query": "b"}, "t2")], "tool_use"),
            ([_text("Best effort from what I found.")], "end_turn"),
        ]
    )

    result = agent.run_agent("q", db_session, client=client)
    assert result.answer == "Best effort from what I found."


def test_the_forced_final_call_has_no_tools(db_session, monkeypatch):
    """Offering tools to a call whose whole purpose is to stop using them
    invites another tool_use, and the loop never terminates."""
    monkeypatch.setattr(agent.settings, "agent_max_turns", 1)
    monkeypatch.setattr(retrieval, "search_runs", lambda *a, **k: ([_hit()], []))
    client = FakeAnthropic(
        [
            ([_tool_use("search_runs", {"query": "a"}, "t1")], "tool_use"),
            ([_text("Done.")], "end_turn"),
        ]
    )

    agent.run_agent("q", db_session, client=client)
    assert "tools" in client.calls[0]
    assert "tools" not in client.calls[-1] or client.calls[-1]["tools"] == []


def test_tokens_are_summed_across_every_call(db_session, monkeypatch):
    monkeypatch.setattr(retrieval, "search_runs", lambda *a, **k: ([_hit()], []))
    client = FakeAnthropic(
        [
            ([_tool_use("search_runs", {"query": "a"}, "t1")], "tool_use"),
            ([_text("Done.")], "end_turn"),
        ]
    )
    result = agent.run_agent("q", db_session, client=client)
    assert result.tokens_in == 20  # two calls at 10
    assert result.tokens_out == 10


def test_steps_never_carry_the_retrieved_text(db_session, monkeypatch):
    """A step is a receipt, not a copy of the corpus. result_summary is counts
    and ids; the text lives once, in `retrieved`."""
    monkeypatch.setattr(
        retrieval, "search_runs", lambda *a, **k: ([_hit(snippet="SECRET_SNIPPET")], [])
    )
    client = FakeAnthropic(
        [
            ([_tool_use("search_runs", {"query": "a"}, "t1")], "tool_use"),
            ([_text("Done.")], "end_turn"),
        ]
    )
    result = agent.run_agent("q", db_session, client=client)
    assert all("SECRET_SNIPPET" not in (step.result_summary or "") for step in result.steps)


def test_the_system_prompt_is_sent_but_never_returned(db_session):
    """Same rule as the loop trace (issue #9): the assembled system prompt can
    carry guardrail language and never leaves the backend."""
    client = FakeAnthropic([([_text("ok")], "end_turn")])
    result = agent.run_agent("q", db_session, client=client)
    assert client.calls[0]["system"]
    assert not hasattr(result, "system_prompt")


def test_retrieval_warnings_reach_the_result(db_session, monkeypatch):
    monkeypatch.setattr(
        retrieval, "search_runs", lambda *a, **k: ([], ["status filter was not applied"])
    )
    client = FakeAnthropic(
        [
            ([_tool_use("search_runs", {"query": "a", "status": "FINISHED"}, "t1")], "tool_use"),
            ([_text("Partial.")], "end_turn"),
        ]
    )
    result = agent.run_agent("q", db_session, client=client)
    assert result.warnings == ["status filter was not applied"]
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `poetry run pytest backend/tests/test_agent_loop.py -v`
Expected: FAIL — `agent` has no attribute `run_agent`.

- [x] **Step 3: Add the setting**

In `backend/app/config.py`, append inside `Settings`:

```python
    # The agent's tool-loop bound (3.5). Hitting it does NOT end the request
    # empty-handed: the loop makes one further call with the tools removed, and
    # that call is not counted — a model that spent its budget searching would
    # otherwise return nothing, which reads as a backend failure.
    agent_max_turns: int = 6
```

- [x] **Step 4: Implement the loop**

Append to `backend/app/agent.py`:

```python
@dataclass(frozen=True)
class AgentStep:
    """One receipt from the transcript. Never carries retrieved text — the text
    lives once, in AgentResult.retrieved."""

    type: str  # "llm" | "tool"
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    result_summary: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class AgentResult:
    answer: str
    retrieved: list[retrieval.Hit]
    warnings: list[str]
    steps: list[AgentStep]
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int


def _default_client() -> Any:
    import anthropic

    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _summarize(hits: list[retrieval.Hit]) -> str:
    """A receipt for the trace: counts and ids only."""
    return f"{len(hits)} source(s): " + ", ".join(
        f"{hit.source_type}:{hit.source_id[:8]}" for hit in hits
    )


def _render_hits(hits: list[retrieval.Hit], warnings: list[str]) -> str:
    """The tool result the MODEL sees. Ids are included because the prompt asks
    it to cite, and it cannot cite what it was not given."""
    if not hits:
        body = "No reviewed history matched. Nothing approved matches these filters."
    else:
        body = "\n\n".join(
            f"[{hit.source_type}] run_id={hit.run_id} experiment_id={hit.experiment_id} "
            f"score={hit.score:.3f}\n{hit.snippet}"
            for hit in hits
        )
    return body + ("\n\nWarnings: " + "; ".join(warnings) if warnings else "")


def _render_detail(detail: retrieval.RunDetail) -> str:
    band = "unquantified" if detail.cv_std is None else f"{detail.cv_std:.4f}"
    return (
        f"run_id={detail.run_id} model={detail.model_type} status={detail.status}\n"
        f"experiment={detail.experiment_name!r} objective={detail.experiment_objective!r}\n"
        f"params={detail.params}\nmetrics={detail.metrics}\ncv_std={band}\n"
        f"notes ({detail.notes_status}): {detail.notes}"
    )


def _execute(
    name: str, args: dict[str, Any], session: Session
) -> tuple[str, list[retrieval.Hit], list[str], str | None, str]:
    """Run one validated tool call.

    Returns (tool_result_text, hits, warnings, error, summary). Never raises: a
    tool failure is information the model can act on, and an exception here ends
    the whole request with a 500 instead.
    """
    error = validate_tool_call(name, args)
    if error:
        return error, [], [], error, "rejected"

    try:
        if name == "search_runs":
            filters = retrieval.Filters(
                model_type=args.get("model_type"),
                dataset_id=args.get("dataset_id"),
                task_type=args.get("task_type"),
                experiment_id=args.get("experiment_id"),
                status=args.get("status"),
            )
            hits, warnings = retrieval.search_runs(
                session, args["query"], filters=filters, k=args.get("k")
            )
            return _render_hits(hits, warnings), hits, warnings, None, _summarize(hits)

        detail = retrieval.get_run_detail(session, args["run_id"])
        return _render_detail(detail), [], [], None, f"run {detail.run_id[:8]}"
    except KeyError as exc:
        message = f"No run with id {exc.args[0]!r}."
        return message, [], [], message, "not found"
    except Exception as exc:  # noqa: BLE001
        message = f"{name} failed: {exc}"
        return message, [], [], message, "failed"


def run_agent(question: str, session: Session, *, client: Any | None = None) -> AgentResult:
    """Answer `question` from reviewed experiment history.

    Deliberately separate from app/loop.py: that loop is judge-gated and renders
    charts, and folding the two together would make each carry the other's
    concerns for no shared behaviour.
    """
    client = client or _default_client()
    started = time.perf_counter()
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    steps: list[AgentStep] = []
    retrieved: list[retrieval.Hit] = []
    seen: set[tuple[str, str]] = set()
    warnings: list[str] = []
    tokens_in = tokens_out = 0
    answer = ""

    with span("agent.request", question_chars=len(question)):
        for turn in range(max(1, settings.agent_max_turns) + 1):
            # The extra iteration is the forced final call: tools removed, so the
            # user gets an answer rather than an empty string that looks like a
            # backend failure. It does not count against the cap.
            forced = turn == max(1, settings.agent_max_turns)
            kwargs: dict[str, Any] = {
                "model": settings.anthropic_model,
                "max_tokens": settings.anthropic_max_tokens,
                "system": load_system_prompt(),
                "messages": messages,
            }
            if not forced:
                kwargs["tools"] = TOOLS

            call_started = time.perf_counter()
            with span("agent.llm_call", turn=turn, forced=forced):
                response = client.messages.create(**kwargs)
            latency = int((time.perf_counter() - call_started) * 1000)

            tokens_in += int(getattr(response.usage, "input_tokens", 0) or 0)
            tokens_out += int(getattr(response.usage, "output_tokens", 0) or 0)
            steps.append(
                AgentStep(
                    type="llm",
                    model=settings.anthropic_model,
                    tokens_in=int(getattr(response.usage, "input_tokens", 0) or 0),
                    tokens_out=int(getattr(response.usage, "output_tokens", 0) or 0),
                    latency_ms=latency,
                )
            )

            text_parts = [b.text for b in response.content if getattr(b, "type", "") == "text"]
            if text_parts:
                answer = "\n".join(text_parts).strip()

            tool_uses = [b for b in response.content if getattr(b, "type", "") == "tool_use"]
            if forced or not tool_uses:
                break

            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in tool_uses:
                args = dict(block.input or {})
                tool_started = time.perf_counter()
                with span("agent.tool_call", tool=block.name):
                    text, hits, tool_warnings, error, summary = _execute(block.name, args, session)
                for hit in hits:
                    key = (hit.source_type, hit.source_id)
                    if key not in seen:
                        seen.add(key)
                        retrieved.append(hit)
                for warning in tool_warnings:
                    if warning not in warnings:
                        warnings.append(warning)
                steps.append(
                    AgentStep(
                        type="tool",
                        tool_name=block.name,
                        tool_args=args,
                        result_summary=summary,
                        error=error,
                        latency_ms=int((time.perf_counter() - tool_started) * 1000),
                    )
                )
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": text}
                )
            messages.append({"role": "user", "content": results})

    return AgentResult(
        answer=answer,
        retrieved=retrieved,
        warnings=warnings,
        steps=steps,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=0.0,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
```

Extend the module's imports:

```python
import time
from dataclasses import dataclass

from app import retrieval
from app.config import settings
from app.tracing import span
from sqlalchemy.orm import Session
```

Check `app/llm.py` for how it computes `cost_usd` from token counts. If a helper
exists there, import it and use it instead of the `0.0` above; if the pricing is
inline in `llm.py`, leave `0.0` and note it in the Task 13 doc sync rather than
copy-pasting a pricing table into a second module.

- [x] **Step 5: Run the tests to verify they pass**

Run: `poetry run pytest backend/tests/test_agent_loop.py -v`
Expected: PASS (13 tests).

- [x] **Step 6: Run the gate**

Run: `make check`
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add backend/app/agent.py backend/app/config.py backend/tests/test_agent_loop.py
git commit -m "feat: run_agent — the hand-rolled tool loop with a forced final answer (3.5)"
```

---

### Task 11: `POST /agent/chat` (3.6a)

**Files:**
- Create: `backend/app/routes/agent.py`
- Modify: `backend/app/schemas.py`, `backend/app/main.py`
- Test: `backend/tests/test_agent_route.py`

**Why:** One endpoint, stateless, single-shot. **D42:** it lives at `/agent`, not
under `/experiments` — the agent answers across investigations, and nesting it
under one would imply a scope it does not have.

**Statelessness is deliberate.** No `agent_chats` table, no history. The
Project 1 chat is stateful because it accumulates charts against a fixed dataset
set; this is a question-answering surface over history that already exists
elsewhere. A durable transcript is Phase 4's problem if it turns out to be one.

**The response field is `retrieved`, not `retrieved_experiments`.** After D33
"experiments" means investigations, and hits are runs, datasets and findings.

**Interfaces:**
- Consumes: `agent.run_agent`, `agent.AgentResult`, `agent.AgentStep`, `retrieval.Hit`.
- Produces: `POST /agent/chat`; schemas `AgentChatRequest`, `AgentChatOut`, `RetrievedOut`, `AgentTraceOut`, `AgentStepOut`.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_agent_route.py`:

```python
"""POST /agent/chat (3.6).

`run_agent` is stubbed exactly as routes/chats.py's tests stub `run_loop` — the
route's job is serialization, and exercising the loop again here would need a
key for no extra coverage.
"""

from app import agent as agent_module
from app.agent import AgentResult, AgentStep
from app.retrieval import Hit


def _hit(source_type="note", run_id="run-1", dataset_id="ds-1"):
    return Hit(
        source_type=source_type,
        source_id=run_id if source_type != "eda" else dataset_id,
        run_id=None if source_type == "eda" else run_id,
        experiment_id=None if source_type == "eda" else "exp-1",
        dataset_id=dataset_id,
        snippet="the snippet",
        score=0.87,
    )


def _result(**overrides):
    base = dict(
        answer="Ridge won.",
        retrieved=[_hit()],
        warnings=[],
        steps=[AgentStep(type="llm", model="claude-sonnet-5", tokens_in=10, tokens_out=5)],
        tokens_in=10,
        tokens_out=5,
        cost_usd=0.001,
        latency_ms=1200,
    )
    base.update(overrides)
    return AgentResult(**base)


def _stub(monkeypatch, result):
    from app.routes import agent as route

    monkeypatch.setattr(route, "run_agent", lambda question, session, **kwargs: result)


def test_a_question_returns_an_answer(client, monkeypatch):
    _stub(monkeypatch, _result())
    resp = client.post("/agent/chat", json={"question": "which model won?"})
    assert resp.status_code == 200
    assert resp.json()["answer"] == "Ridge won."


def test_the_response_field_is_retrieved(client, monkeypatch):
    """Not retrieved_experiments: after D33 'experiment' means investigation, and
    these hits are runs, datasets and findings."""
    _stub(monkeypatch, _result())
    body = client.post("/agent/chat", json={"question": "q"}).json()
    assert "retrieved" in body
    assert "retrieved_experiments" not in body


def test_each_hit_carries_its_deep_link_ids(client, monkeypatch):
    _stub(monkeypatch, _result(retrieved=[_hit("note"), _hit("eda")]))
    hits = client.post("/agent/chat", json={"question": "q"}).json()["retrieved"]
    by_type = {hit["source_type"]: hit for hit in hits}
    assert by_type["note"]["experiment_id"] == "exp-1"
    assert by_type["eda"]["dataset_id"] == "ds-1"
    assert by_type["eda"]["run_id"] is None


def test_the_trace_carries_the_steps(client, monkeypatch):
    _stub(monkeypatch, _result())
    trace = client.post("/agent/chat", json={"question": "q"}).json()["trace"]
    assert trace["tokens_in"] == 10
    assert trace["steps"][0]["type"] == "llm"


def test_the_system_prompt_is_never_returned(client, monkeypatch):
    """Same rule as the loop trace (issue #9): it can carry guardrail language,
    so it is not returned, not stored, and has no UI toggle."""
    _stub(monkeypatch, _result())
    assert "system" not in client.post("/agent/chat", json={"question": "q"}).text


def test_warnings_are_returned(client, monkeypatch):
    """A silently unapplied filter is worse than a visible degradation."""
    _stub(monkeypatch, _result(warnings=["status filter was not applied"]))
    body = client.post("/agent/chat", json={"question": "q"}).json()
    assert body["warnings"] == ["status filter was not applied"]


def test_an_empty_question_is_a_422(client, monkeypatch):
    _stub(monkeypatch, _result())
    assert client.post("/agent/chat", json={"question": "   "}).status_code == 422


def test_a_missing_question_is_a_422(client):
    assert client.post("/agent/chat", json={}).status_code == 422


def test_an_empty_retrieval_is_a_200_with_no_hits(client, monkeypatch):
    """Before `make embed` has run this is the normal state, and it is an answer,
    not an error."""
    _stub(monkeypatch, _result(answer="No reviewed history matches.", retrieved=[]))
    body = client.post("/agent/chat", json={"question": "q"}).json()
    assert body["retrieved"] == []
    assert "No reviewed history" in body["answer"]


def test_the_route_takes_no_chat_id(client, monkeypatch):
    """Stateless and single-shot: no agent_chats table, no history (3.6)."""
    _stub(monkeypatch, _result())
    resp = client.post("/agent/chat", json={"question": "q", "chat_id": "whatever"})
    assert resp.status_code == 422


def test_the_route_is_registered_at_agent_not_under_experiments(client, monkeypatch):
    """D42: the agent answers ACROSS investigations."""
    _stub(monkeypatch, _result())
    assert client.post("/agent/chat", json={"question": "q"}).status_code == 200
    assert client.post("/experiments/agent/chat", json={"question": "q"}).status_code == 404


def test_module_import_needs_no_api_key(monkeypatch):
    """Importing the route must not construct an Anthropic client — the whole
    test suite runs without a key."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert agent_module.TOOLS
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `poetry run pytest backend/tests/test_agent_route.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.routes.agent'`.

- [x] **Step 3: Add the schemas**

Append to `backend/app/schemas.py`:

```python
class AgentChatRequest(BaseModel):
    """Stateless and single-shot (3.6): no chat id, no history. Extra fields are
    rejected so a client that thinks it is continuing a conversation finds out."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value


class RetrievedOut(BaseModel):
    """One retrieved source. `run_id` is null for an eda hit — it is about a
    dataset, not a run — which is what the UI switches its deep link on."""

    source_type: str
    source_id: str
    run_id: str | None
    experiment_id: str | None
    dataset_id: str | None
    snippet: str
    score: float


class AgentStepOut(BaseModel):
    type: str
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    result_summary: str | None = None
    error: str | None = None


class AgentTraceOut(BaseModel):
    steps: list[AgentStepOut]
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int


class AgentChatOut(BaseModel):
    """Deliberately has no `system_prompt` field. Same rule as the loop trace
    (issue #9): the assembled prompt can leak guardrail language, so it is not
    returned, not stored, and has no UI toggle."""

    answer: str
    retrieved: list[RetrievedOut]
    warnings: list[str]
    trace: AgentTraceOut
```

Add whatever of `ConfigDict`, `Field`, `field_validator`, `Any` the file does not
already import; check the existing imports first rather than assuming.

- [x] **Step 4: Write the route**

Create `backend/app/routes/agent.py`:

```python
"""The retrieval agent's one endpoint (3.6).

Mounted at /agent, NOT under /experiments (D42): the agent answers across
investigations, and nesting it under one would imply a scope it does not have.

Like POST /chats/{id}/messages and the two generation endpoints (D23), this calls
the LLM synchronously inside the request. It is the one request-path caller of
Voyage, because every search embeds its query — indexing stays in `make embed`
(D17), so an approval never fails because a vendor is down.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agent import AgentResult, run_agent
from app.db import get_session
from app.schemas import (
    AgentChatOut,
    AgentChatRequest,
    AgentStepOut,
    AgentTraceOut,
    RetrievedOut,
)

router = APIRouter(prefix="/agent", tags=["agent"])


def _out(result: AgentResult) -> AgentChatOut:
    return AgentChatOut(
        answer=result.answer,
        retrieved=[
            RetrievedOut(
                source_type=hit.source_type,
                source_id=hit.source_id,
                run_id=hit.run_id,
                experiment_id=hit.experiment_id,
                dataset_id=hit.dataset_id,
                snippet=hit.snippet,
                score=hit.score,
            )
            for hit in result.retrieved
        ],
        warnings=list(result.warnings),
        trace=AgentTraceOut(
            steps=[
                AgentStepOut(
                    type=step.type,
                    model=step.model,
                    tokens_in=step.tokens_in,
                    tokens_out=step.tokens_out,
                    latency_ms=step.latency_ms,
                    tool_name=step.tool_name,
                    tool_args=step.tool_args,
                    result_summary=step.result_summary,
                    error=step.error,
                )
                for step in result.steps
            ],
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_usd=result.cost_usd,
            latency_ms=result.latency_ms,
        ),
    )


@router.post("/chat", response_model=AgentChatOut)
def chat(
    body: AgentChatRequest, session: Session = Depends(get_session)
) -> AgentChatOut:
    # No try/except, matching routes/chats.py and the two generation endpoints
    # (D23): a loop failure propagates to FastAPI's default handler so the
    # behaviour stays uniform across every LLM-calling route.
    return _out(run_agent(body.question, session))
```

- [x] **Step 5: Register the router**

In `backend/app/main.py`, add `agent` to the routes import and include it
alongside the others:

```python
    from app.routes import agent, chats, datasets, experiments, findings, models, runs

    app.include_router(agent.router)
```

- [x] **Step 6: Run the tests to verify they pass**

Run: `poetry run pytest backend/tests/test_agent_route.py -v`
Expected: PASS (12 tests).

- [x] **Step 7: Run the gate**

Run: `make check`
Expected: PASS.

- [x] **Step 8: Try it against the real thing (manual)**

With `make dev` running, `ANTHROPIC_API_KEY` and `VOYAGE_API_KEY` set, and
`make embed` already run:

```bash
curl -s localhost:8000/agent/chat -H 'content-type: application/json' \
  -d '{"question":"Which model did best on the revenue panel, and by how much?"}' | jq .
```
Expected: an answer citing runs by name, a non-empty `retrieved`, and a `trace`
whose steps include at least one `search_runs` tool call. If `retrieved` is empty
and the answer says there is no reviewed history, that is the honest answer for
an empty index — approve some notes and re-run `make embed`.

- [x] **Step 9: Commit**

```bash
git add backend/app/routes/agent.py backend/app/schemas.py backend/app/main.py \
        backend/tests/test_agent_route.py
git commit -m "feat: POST /agent/chat — the agent's one stateless endpoint (3.6)"
```

---

### Task 12: `AskPage` and the Agent nav category (3.6b)

**Files:**
- Create: `frontend/src/pages/AskPage.tsx`, `frontend/src/pages/AskPage.module.css`, `frontend/src/pages/AskPage.test.tsx`
- Modify: `frontend/src/api.ts`, `frontend/src/types.ts`, `frontend/src/App.tsx`, `frontend/src/components/NavRail.tsx`

**Why:** A retrieval system whose results nobody can click through is unfalsifiable.
Every citation deep-links to the page holding the reviewed text it came from —
`eda` to `/datasets/{dataset_id}`, `note` and `diagnostic` to
`/experiments/{experiment_id}` — so a wrong citation is visibly wrong.

**Nav placement:** a **third top-level category**, `Agent`, beside `Data` and
`Machine learning`, using the same `wp-rail-collapsed` persistence with the key
`"agent"`. Not under `Machine learning` — the agent reads across both halves,
including dataset EDA.

**Testing constraint:** Vitest runs with `css: false`. Assert on roles,
accessible names, `data-*` attributes and visible text — **never** CSS-module
class names, which are `undefined` at test time.

**Interfaces:**
- Consumes: `POST /agent/chat` (Task 11).
- Produces: `api.askAgent(question: string): Promise<AgentAnswer>`; types `AgentAnswer`, `Retrieved`, `AgentTrace`, `AgentStep`; route `/ask`.

- [x] **Step 1: Add the types**

Append to `frontend/src/types.ts`:

```ts
/** One retrieved source. `run_id` is null for an `eda` hit — it is about a
 *  dataset, not a run — which is what the citation's deep link switches on. */
export interface Retrieved {
  source_type: "note" | "eda" | "diagnostic";
  source_id: string;
  run_id: string | null;
  experiment_id: string | null;
  dataset_id: string | null;
  snippet: string;
  score: number;
}

export interface AgentStep {
  type: "llm" | "tool";
  model: string;
  tokens_in: number;
  tokens_out: number;
  latency_ms: number;
  tool_name: string | null;
  tool_args: Record<string, unknown> | null;
  result_summary: string | null;
  error: string | null;
}

export interface AgentTrace {
  steps: AgentStep[];
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  latency_ms: number;
}

export interface AgentAnswer {
  answer: string;
  retrieved: Retrieved[];
  warnings: string[];
  trace: AgentTrace;
}
```

- [x] **Step 2: Add the API wrapper**

Append to `frontend/src/api.ts` (and add `AgentAnswer` to the type import at the
top of the file):

```ts
/** Ask the retrieval agent one question. Stateless: no chat id, no history. */
export async function askAgent(question: string): Promise<AgentAnswer> {
  const res = await fetch(`${API_BASE}/agent/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<AgentAnswer>;
}
```

- [x] **Step 3: Write the failing tests**

Create `frontend/src/pages/AskPage.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AskPage from "./AskPage";
import * as api from "../api";

function answer(overrides = {}) {
  return {
    answer: "Ridge beat the persistence baseline by 4.2 RMSE.",
    retrieved: [
      {
        source_type: "note" as const,
        source_id: "run-1",
        run_id: "run-1",
        experiment_id: "exp-1",
        dataset_id: "ds-1",
        snippet: "Ridge at alpha=1.0 scored 12.5 RMSE.",
        score: 0.91,
      },
    ],
    warnings: [],
    trace: {
      steps: [
        {
          type: "tool" as const,
          model: "",
          tokens_in: 0,
          tokens_out: 0,
          latency_ms: 8,
          tool_name: "search_runs",
          tool_args: { query: "ridge" },
          result_summary: "1 source(s)",
          error: null,
        },
      ],
      tokens_in: 100,
      tokens_out: 40,
      cost_usd: 0.002,
      latency_ms: 1500,
    },
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <AskPage />
    </MemoryRouter>,
  );
}

async function ask(text = "which model won?") {
  await userEvent.type(screen.getByLabelText(/question/i), text);
  await userEvent.click(screen.getByRole("button", { name: /ask/i }));
}

describe("AskPage", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("renders the answer", async () => {
    vi.spyOn(api, "askAgent").mockResolvedValue(answer());
    renderPage();
    await ask();
    expect(await screen.findByText(/beat the persistence baseline/i)).toBeInTheDocument();
  });

  it("links a note citation to its experiment", async () => {
    vi.spyOn(api, "askAgent").mockResolvedValue(answer());
    renderPage();
    await ask();
    const link = await screen.findByRole("link", { name: /run-1|ridge|note/i });
    expect(link).toHaveAttribute("href", "/experiments/exp-1");
  });

  it("links an eda citation to its dataset", async () => {
    vi.spyOn(api, "askAgent").mockResolvedValue(
      answer({
        retrieved: [
          {
            source_type: "eda" as const,
            source_id: "ds-1",
            run_id: null,
            experiment_id: null,
            dataset_id: "ds-1",
            snippet: "Revenue is right-skewed.",
            score: 0.8,
          },
        ],
      }),
    );
    renderPage();
    await ask();
    const link = await screen.findByRole("link", { name: /eda|ds-1|revenue/i });
    expect(link).toHaveAttribute("href", "/datasets/ds-1");
  });

  it("says so when nothing was retrieved", async () => {
    vi.spyOn(api, "askAgent").mockResolvedValue(
      answer({ answer: "No reviewed history matches.", retrieved: [] }),
    );
    renderPage();
    await ask();
    expect(await screen.findByText(/no sources/i)).toBeInTheDocument();
  });

  it("shows warnings returned with the answer", async () => {
    vi.spyOn(api, "askAgent").mockResolvedValue(
      answer({ warnings: ["status filter was not applied"] }),
    );
    renderPage();
    await ask();
    expect(await screen.findByText(/status filter was not applied/i)).toBeInTheDocument();
  });

  it("disables Ask while a question is in flight", async () => {
    let resolve!: (value: unknown) => void;
    vi.spyOn(api, "askAgent").mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }) as never,
    );
    renderPage();
    await ask();
    expect(screen.getByRole("button", { name: /ask/i })).toBeDisabled();
    resolve(answer());
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /ask/i })).not.toBeDisabled(),
    );
  });

  it("will not submit a blank question", async () => {
    const spy = vi.spyOn(api, "askAgent").mockResolvedValue(answer());
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: /ask/i }));
    expect(spy).not.toHaveBeenCalled();
  });

  it("shows an error banner when the request fails", async () => {
    vi.spyOn(api, "askAgent").mockRejectedValue(new Error("boom"));
    renderPage();
    await ask();
    expect(await screen.findByText(/boom/i)).toBeInTheDocument();
  });

  it("exposes the trace behind a disclosure", async () => {
    vi.spyOn(api, "askAgent").mockResolvedValue(answer());
    renderPage();
    await ask();
    expect(await screen.findByText(/search_runs/i)).toBeInTheDocument();
  });
});
```

- [x] **Step 4: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/AskPage.test.tsx`
Expected: FAIL — cannot resolve `./AskPage`.

- [x] **Step 5: Write the page**

Create `frontend/src/pages/AskPage.tsx`:

```tsx
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { Link } from "react-router-dom";

import { askAgent } from "../api";
import ErrorBanner from "../components/ErrorBanner";
import { Button, Card, Textarea } from "../ui";
import type { AgentAnswer, Retrieved } from "../types";
import styles from "./AskPage.module.css";

/** Where a citation goes. An `eda` hit is about a dataset and has no run; the
 *  other two are about a run and open its investigation. Switching on
 *  `source_type` rather than on whichever id happens to be non-null keeps the
 *  mapping readable when a hit carries several. */
function hrefFor(hit: Retrieved): string | null {
  if (hit.source_type === "eda") {
    return hit.dataset_id ? `/datasets/${hit.dataset_id}` : null;
  }
  return hit.experiment_id ? `/experiments/${hit.experiment_id}` : null;
}

function labelFor(hit: Retrieved): string {
  const what =
    hit.source_type === "eda"
      ? "EDA"
      : hit.source_type === "note"
        ? "Run note"
        : "Diagnostic";
  return `${what} · ${hit.source_id.slice(0, 8)}`;
}

export default function AskPage() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AgentAnswer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event?: React.FormEvent) {
    event?.preventDefault();
    if (!question.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await askAgent(question));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.page}>
      <h1>Ask about the experiment history</h1>
      <p className={styles.lede}>
        Answers come from <strong>approved</strong> run notes, EDA findings and
        diagnostics. Nothing that has not been reviewed is searched.
      </p>

      <form onSubmit={submit} className={styles.form}>
        <label htmlFor="agent-question">Question</label>
        <Textarea
          id="agent-question"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={3}
          placeholder="Which model did best on the revenue panel, and by how much?"
        />
        <Button type="submit" disabled={busy || !question.trim()}>
          {busy ? "Asking…" : "Ask"}
        </Button>
      </form>

      {error && <ErrorBanner message={error} />}

      {result && (
        <>
          {result.warnings.map((warning) => (
            <p key={warning} className={styles.warning} role="status">
              {warning}
            </p>
          ))}

          <Card className={styles.answer}>
            <ReactMarkdown>{result.answer}</ReactMarkdown>
          </Card>

          <h2>Sources</h2>
          {result.retrieved.length === 0 ? (
            <p className={styles.empty}>
              No sources — nothing approved matched this question.
            </p>
          ) : (
            <ul className={styles.sources}>
              {result.retrieved.map((hit) => {
                const href = hrefFor(hit);
                return (
                  <li key={`${hit.source_type}:${hit.source_id}`} data-source={hit.source_type}>
                    {href ? (
                      <Link to={href}>{labelFor(hit)}</Link>
                    ) : (
                      <span>{labelFor(hit)}</span>
                    )}
                    <span className={styles.score}>{hit.score.toFixed(2)}</span>
                    <p className={styles.snippet}>{hit.snippet}</p>
                  </li>
                );
              })}
            </ul>
          )}

          <details className={styles.trace}>
            <summary>
              Trace · {result.trace.steps.length} steps ·{" "}
              {result.trace.tokens_in + result.trace.tokens_out} tokens ·{" "}
              {result.trace.latency_ms} ms
            </summary>
            <ol>
              {result.trace.steps.map((step, index) => (
                <li key={index} data-step={step.type}>
                  {step.type === "tool"
                    ? `${step.tool_name} — ${step.error ?? step.result_summary ?? ""}`
                    : `${step.model} — ${step.tokens_in} in / ${step.tokens_out} out`}
                </li>
              ))}
            </ol>
          </details>
        </>
      )}
    </div>
  );
}
```

Check `frontend/src/components/ErrorBanner.tsx` for its actual prop name and
whether it is a default or named export, and `frontend/src/ui/index.ts` for the
exact `Button`/`Card`/`Textarea` exports; match them rather than the sketch. If
`Card` does not accept `className`, drop the prop.

- [x] **Step 6: Write the stylesheet**

Create `frontend/src/pages/AskPage.module.css`, using only the tokens defined in
`frontend/src/styles/tokens.css` — no hand-mixed colours, so both themes hold:

```css
.page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.lede {
  color: var(--fg-muted);
}

.form {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  align-items: flex-start;
}

.answer {
  padding: var(--space-4);
}

.warning {
  color: var(--fg-muted);
  border-left: 2px solid var(--border);
  padding-left: var(--space-3);
}

.sources {
  list-style: none;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.sources li {
  border: 1px solid var(--border);
  border-radius: var(--radius-2);
  padding: var(--space-3);
}

.score {
  color: var(--fg-muted);
  margin-left: var(--space-2);
  font-variant-numeric: tabular-nums;
}

.snippet {
  margin: var(--space-2) 0 0;
  color: var(--fg-muted);
}

.empty {
  color: var(--fg-muted);
}

.trace summary {
  cursor: pointer;
  color: var(--fg-muted);
}
```

Open `frontend/src/styles/tokens.css` and substitute the variable names it
actually defines — the names above are the shape, not necessarily the spelling.

- [x] **Step 7: Add the route**

In `frontend/src/App.tsx`, import `AskPage` and add:

```tsx
<Route path="/ask" element={<AskPage />} />
```

Use the same `AppShell` `width` the other content pages use for this shape —
`"wide"` matches the experiments pages and suits the source list.

- [x] **Step 8: Add the Agent category to the rail**

In `frontend/src/components/NavRail.tsx`, add a third group beside `Data` and
`Machine learning`, following the existing two exactly: a collapse key of
`"agent"` in the same `wp-rail-collapsed` set, the same `toggleGroup` handler,
the same markup shape. Its single entry is a `NavLink` to `/ask` labelled `Ask`.

It is top-level rather than nested under `Machine learning` because the agent
reads across both halves — run notes *and* dataset EDA — so filing it under one
would misdescribe what it searches.

- [x] **Step 9: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/AskPage.test.tsx`
Expected: PASS (9 tests).

- [x] **Step 10: Run the frontend gate**

```bash
cd frontend && npm run type-check && npm test && npm run build
```
Expected: all PASS. The existing `NavRail` tests must still pass — if one asserts
on the number of groups, update it to expect three.

- [x] **Step 11: Look at it (manual)**

With `make dev` and `npm run dev` running, open http://localhost:5173/ask, ask a
question, and click a citation. Confirm it lands on the page holding that text,
that the rail's Agent group collapses and stays collapsed across a reload, and
that the page reads correctly in both themes.

- [x] **Step 12: Commit**

```bash
git add frontend/src/pages/AskPage.tsx frontend/src/pages/AskPage.module.css \
        frontend/src/pages/AskPage.test.tsx frontend/src/api.ts \
        frontend/src/types.ts frontend/src/App.tsx frontend/src/components/NavRail.tsx
git commit -m "feat: AskPage — ask the agent, with deep-linked citations (3.6)"
```

---

### Task 13: Documentation sync and close-out

**Files:**
- Modify: `backend/app/models.py` (docstring only), `CLAUDE.md`, `README.md`, `doc/architecture.md`, `doc/user-manual.md`, this plan file
- Test: none new — this task changes prose and one docstring

**Why:** `CLAUDE.md` requires this before a behaviour-changing PR merges, and
this phase adds five modules, one endpoint, one page, two settings groups and a
third CI job. It also fixes a docstring that has been wrong since D33.

- [x] **Step 1: Fix the `ExperimentNoteChunk` docstring**

`backend/app/models.py:250–257` predates D33 and is wrong twice: it says chunks
are read by "the agent's `search_experiments` tool" (the tool is `search_runs`,
D41) and that `source_type="note"` keys to `experiments.notes` (that column is
`runs.notes` since the hierarchy split). Replace the docstring with:

```python
    """A chunk of reviewable text plus its embedding (D6/D21). Written by
    app/embeddings.py and read by the agent's `search_runs` tool (D41).

    `source_type` discriminates the three content types retrieval covers, and
    each keys to a different table (D30):

    | source_type  | source_id      | text comes from        |
    |--------------|----------------|------------------------|
    | "note"       | app.runs.id    | runs.notes             |
    | "diagnostic" | app.runs.id    | app.findings.text      |
    | "eda"        | app.datasets.id| app.findings.text      |

    Like `findings.source_id`, this addresses more than one table and so carries
    no FK. Only APPROVED text is ever written here (D28), and the backfill
    REAPS chunks whose source is no longer approved — the denormalised `status`
    below is a second line of defence, not the first.
    """
```

- [x] **Step 2: Update `CLAUDE.md`**

Three edits:

1. **Code layout** — add to the `backend/app/` list, in the file's existing style:
   - `tracing.py    # configure_tracing() + span() — OpenTelemetry, no-op unless OTEL_ENABLED`
   - `embeddings.py # chunk_text/embed_texts (Voyage) + the backfill reconciliation`
   - `retrieval.py  # two-stage retrieval: structured filters, then pgvector; get_run_detail`
   - `agent.py      # TOOLS, validate_tool_call, run_agent — the hand-rolled loop`
   - `routes/agent.py # POST /agent/chat (D42)`
   Plus `prompts/agent.md`, `scripts/backfill_embeddings.py`,
   `frontend/src/pages/AskPage.tsx`, and the `Agent` rail category.

2. **Commands** — add `make embed` to the backend command block with its one-line
   description, and note that `pytest -m postgres` needs `POSTGRES_TEST_URL` and
   runs as its own CI job.

3. **Non-obvious design decisions** — add these, each in the file's established
   voice (the claim, then what breaks without it):
   - **Only approved text is ever embedded (D28), and the backfill reaps.**
     `approved → rejected` must remove chunks; an append-only backfill leaves
     rejected text ranking under `status='approved'` and every other test stays green.
   - **Chunk keys are `(source_type, source_id)` across two tables (D30)**, and
     several approved findings on one key are concatenated oldest-first and
     chunked as one document — `POST /datasets/{id}/eda` can be run twice.
   - **`k` counts sources, not chunks (D31).** One four-chunk finding would
     otherwise fill the budget and hide three other runs.
   - **Structured filters run before the vector search (D15/D31)**, and a filter
     matching nothing returns `keys == ()`, which is not `keys is None`.
   - **The agent's tools are `search_runs` and `get_run_detail` (D41)** — never
     `search_experiments`, which since D33 names investigations.
   - **`POST /agent/chat` is stateless and lives at `/agent` (D42)**, and is the
     one request-path Voyage call; indexing stays in `make embed` (D17).
   - **Span attributes carry ids, counts and durations — never payloads.**
     Questions, notes and snippets do not go into traces.
   - **`_rank_chunks` is the only function that emits `<=>`**, is monkeypatched
     by the SQLite suite, and is covered for real by the `backend-postgres` job.

- [x] **Step 3: Update `README.md`**

Add to the feature list: ask the agent a question about reviewed experiment
history and click through to the source. Add to the quickstart: `make embed`
after approving notes, `VOYAGE_API_KEY` in `.env`, and one line that the index
holds only approved text, so a fresh install answers "no reviewed history" until
something is approved — the most likely first-run confusion.

- [x] **Step 4: Update `doc/architecture.md` and `doc/user-manual.md`**

`architecture.md`: add the retrieval path to the diagrammed overview — question →
`run_agent` → `search_runs` → structured filters → pgvector → grouped sources →
answer — and the offline `make embed` path feeding the index, drawn as a
*separate* arrow so its asynchrony is visible.

`user-manual.md`: add an "Ask about past experiments" section — approve notes,
run `make embed`, ask, read the citations — and say plainly that unapproved text
is invisible to the agent.

- [x] **Step 5: Tick this plan's checkboxes**

Mark every completed task's steps `- [x]` in
`doc/plans/2026-08-25-project-2-phase-3-retrieval-agent-tracing.md`, and tick the
deliverables in
`doc/plans/2026-08-25-project-2-phase-3-retrieval-agent-tracing-design.md` §2 if
that section carries checkboxes.

- [x] **Step 6: Run both gates one last time**

```bash
make check
cd frontend && npm run type-check && npm test && npm run build
```
Expected: all PASS.

- [x] **Step 7: Commit**

```bash
git add backend/app/models.py CLAUDE.md README.md doc/
git commit -m "docs: sync docs with Phase 3 — retrieval, agent, and tracing"
```

---

## Done means

- `make check` passes; `pytest -m postgres` passes against a real Postgres in CI.
- `make embed` reconciles the index in both directions — approving indexes,
  un-approving reaps.
- `POST /agent/chat` answers a real question with real citations, and `/ask`
  deep-links each one to the page holding the text it came from.
- Jaeger shows one trace per request with the LLM, tool and retrieval spans
  nested under it, and no payloads in the attributes.
- Every doc in the sync list reflects what shipped.
