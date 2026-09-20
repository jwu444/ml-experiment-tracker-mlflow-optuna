# Project 2 — Phase 2b Implementation Plan: EDA, Diagnostics, and Chunk Source Types

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Design:** `doc/plans/2026-08-14-project-2-phase-2b-eda-diagnostics-design.md` (approved 2026-08-14). Read it before Task 1 — this plan implements it and does not re-argue it.

**Goal:** Produce the two reviewable content types Phase 3 retrieval needs (EDA findings, diagnostic interpretations), record a persistence baseline as a real logged run, migrate the chunk table to source types, and give the reviewer a bulk-approval queue.

**Architecture:** A new `app.findings` table holds reviewable text keyed by `(source_type, source_id)`, with `original_text` frozen at insert so the draft-vs-edit diff survives a save. Two new endpoints generate that text by calling the existing `run_loop` synchronously — no new LLM machinery, only two new *analysis* tools (`error_by_group`, `line`) so per-ticker error and learning curves are expressible. Diagnostics loads the logged MLflow model and reproduces the run's own split via `training.split_frame`, so residuals are computed on exactly the rows the run was scored on. The persistence baseline is a `MODEL_REGISTRY` entry reached through a new `ModelSpec.preprocess = False`, which is what keeps a raw prior value from being handed to the estimator scaled.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (`Mapped`/`mapped_column`), Alembic, pandas, scikit-learn, MLflow 3.x, pytest, React + Vite + TypeScript, Vitest + React Testing Library.

## Global Constraints

- Line length **100** (ruff + black). mypy is **strict** on `backend/app`.
- Imports are absolute from `app` (e.g. `from app.training import split_frame`).
- Backend app code in `backend/app/` only; backend tests in `backend/tests/` only.
- Tests run on **SQLite** via the `client` fixture in `backend/tests/conftest.py` (isolated DB per test, `tmp_path`). No API key, no network, no Postgres.
- **Endpoints never call Claude or Voyage directly** — they call `app.loop.run_loop`, which is monkeypatched in tests (pattern: `backend/tests/test_chats.py:42`).
- **Charts are never stored** for the main answer path. Findings persist text only.
- **D13 holds:** nothing at request time reads a CSV off disk, and derived frames are **never** inserted into `datasets`.
- **D20 holds:** writing text is never implicitly an approval. `status` moves only when the caller names it. Approving empty text is a **422**.
- Alembic is the schema authority on Postgres; `Base.metadata.create_all` covers SQLite. After a model change: `make migration m="…"`, review the generated file, then `make migrate`.
- New tables live in the `app` Postgres schema (`__table_args__ = {"schema": "app"}`).
- Every metric reported alongside its cross-validation standard deviation — the panel is ~224 rows and a gap smaller than the fold spread is noise.
- Frontend tests run with `css: false`: assert on roles / accessible names / `data-*` / visible text, **never** CSS-module class names.
- The CI gate is `make check` (lint + format-check + type-check + test) plus the frontend job (`npm run type-check`, `npm test`, `npm run build`). `/ci-check` runs both locally.

---

## File Structure

**Created:**

| File | Responsibility |
|---|---|
| `backend/app/findings.py` | Findings persistence + referential validation + status transitions. No HTTP, no LLM. |
| `backend/app/diagnostics.py` | `residual_frame` / `learning_curve_frame`. Two pure DataFrame-returning functions. |
| `backend/app/routes/findings.py` | `GET /findings`, `PATCH /findings/{id}`. |
| `backend/tests/test_findings.py` | Unit tests for `app/findings.py`. |
| `backend/tests/test_findings_api.py` | Route tests for `GET`/`PATCH /findings`. |
| `backend/tests/test_diagnostics.py` | Unit tests for the two frame builders. |
| `backend/tests/test_baseline.py` | `PriorValueRegressor` through the pipeline. |
| `backend/tests/test_eda_route.py` | `POST /datasets/{id}/eda`. |
| `backend/tests/test_diagnostics_route.py` | `POST /experiments/{id}/diagnostics` incl. every 409. |
| `frontend/src/pages/ReviewPage.tsx` (+ `.module.css`, `.test.tsx`) | The `/review` queue over three content types. |

**Modified:**

| File | Change |
|---|---|
| `backend/app/models.py` | Add `Finding`; rewrite `ExperimentNoteChunk` to `source_type`/`source_id`/`status`. |
| `backend/app/training.py` | Add `PriorValueRegressor`, `ModelSpec.preprocess`, the `persistence` registry entry; branch in `build_pipeline`. |
| `backend/app/analysis.py` | Add `error_by_group`, `line`. |
| `backend/app/tools.py` | Add both tool schemas + their validation branches. |
| `backend/app/charts.py` | Add both to `_DISPATCH`. |
| `backend/app/schemas.py` | Add `FindingOut`, `FindingPatchRequest`, `FindingCreatedOut`. |
| `backend/app/routes/datasets.py` | Add `POST /datasets/{id}/eda`. |
| `backend/app/routes/experiments.py` | Add `POST /experiments/{id}/diagnostics`; reject tuning a model with an empty search space. |
| `backend/app/main.py` | Register the findings router. |
| `frontend/src/api.ts` | Add `Finding`, `listFindings`, `updateFinding`, `runEda`, `runDiagnostics`. |
| `frontend/src/App.tsx` | Add the `/review` route. |
| `README.md`, `CLAUDE.md`, `doc/plans/2026-08-05-project-2-overall-implementation-plan.md` | Doc sync (Task 10). |

---

## Task 1: The `findings` table and `app/findings.py`

**Files:**
- Modify: `backend/app/models.py` (append after `Experiment`, before `ExperimentNoteChunk`)
- Create: `backend/app/findings.py`
- Create: `backend/tests/test_findings.py`
- Create: `backend/alembic/versions/<generated>_add_findings_table.py`

**Interfaces:**
- Consumes: `Base`, `_uuid` from `app.models`; the `client` fixture's session.
- Produces:
  - `app.models.Finding` with columns `id, source_type, source_id, text, original_text, status, created_at`
  - `findings.SOURCE_TYPES: frozenset[str]` = `{"eda", "diagnostic"}`
  - `findings.create_finding(session: Session, source_type: str, source_id: str, text: str) -> Finding`
  - `findings.list_findings(session: Session, status: str | None = None, source_type: str | None = None, limit: int = 50, offset: int = 0) -> list[Finding]`
  - `findings.update_finding(session: Session, finding_id: str, text: str | None = None, status: str | None = None) -> Finding`
  - `findings.FindingError(Exception)` with `.status_code: int` — routes map it to `HTTPException`.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_findings.py`:

```python
import pytest
from sqlalchemy import select

from app import findings
from app.models import Dataset, Experiment, Finding


def _dataset(session) -> Dataset:
    row = Dataset(name="d.csv", data_csv="a,b\n1,2\n", profile_json={}, content_hash="h1")
    session.add(row)
    session.flush()
    return row


def _experiment(session) -> Experiment:
    row = Experiment(mlflow_run_id="run-1", model_type="ridge", task_type="regression")
    session.add(row)
    session.flush()
    return row


def test_create_eda_finding_freezes_original_text(session) -> None:
    dataset = _dataset(session)
    row = findings.create_finding(session, "eda", dataset.id, "revenue is right-skewed")
    assert row.status == "draft"
    assert row.text == "revenue is right-skewed"
    assert row.original_text == "revenue is right-skewed"


def test_create_diagnostic_finding_validates_against_experiments(session) -> None:
    experiment = _experiment(session)
    row = findings.create_finding(session, "diagnostic", experiment.id, "residuals drift late")
    assert row.source_type == "diagnostic"
    assert row.source_id == experiment.id


def test_create_rejects_unknown_source_type(session) -> None:
    with pytest.raises(findings.FindingError) as exc:
        findings.create_finding(session, "guess", "whatever", "text")
    assert exc.value.status_code == 422


def test_eda_source_id_must_exist_in_datasets(session) -> None:
    experiment = _experiment(session)
    # An experiment id is a real id — but not a dataset id. The missing FK is
    # exactly what makes this silently insertable without the check.
    with pytest.raises(findings.FindingError) as exc:
        findings.create_finding(session, "eda", experiment.id, "text")
    assert exc.value.status_code == 404


def test_diagnostic_source_id_must_exist_in_experiments(session) -> None:
    dataset = _dataset(session)
    with pytest.raises(findings.FindingError) as exc:
        findings.create_finding(session, "diagnostic", dataset.id, "text")
    assert exc.value.status_code == 404


def test_update_text_alone_is_never_an_approval(session) -> None:
    dataset = _dataset(session)
    row = findings.create_finding(session, "eda", dataset.id, "draft text")
    updated = findings.update_finding(session, row.id, text="edited text")
    assert updated.text == "edited text"
    assert updated.status == "draft"
    assert updated.original_text == "draft text"


def test_approving_empty_text_is_422(session) -> None:
    dataset = _dataset(session)
    row = findings.create_finding(session, "eda", dataset.id, "   ")
    with pytest.raises(findings.FindingError) as exc:
        findings.update_finding(session, row.id, status="approved")
    assert exc.value.status_code == 422


def test_rejecting_empty_text_is_allowed(session) -> None:
    dataset = _dataset(session)
    row = findings.create_finding(session, "eda", dataset.id, "")
    updated = findings.update_finding(session, row.id, status="rejected")
    assert updated.status == "rejected"


def test_update_rejects_unknown_status(session) -> None:
    dataset = _dataset(session)
    row = findings.create_finding(session, "eda", dataset.id, "text")
    with pytest.raises(findings.FindingError) as exc:
        findings.update_finding(session, row.id, status="blessed")
    assert exc.value.status_code == 422


def test_update_unknown_finding_is_404(session) -> None:
    with pytest.raises(findings.FindingError) as exc:
        findings.update_finding(session, "no-such-id", text="x")
    assert exc.value.status_code == 404


def test_list_filters_by_status_and_source_type(session) -> None:
    dataset = _dataset(session)
    experiment = _experiment(session)
    a = findings.create_finding(session, "eda", dataset.id, "a")
    findings.create_finding(session, "diagnostic", experiment.id, "b")
    findings.update_finding(session, a.id, status="approved")

    assert [r.id for r in findings.list_findings(session, status="draft")] == [
        r.id for r in session.execute(
            select(Finding).where(Finding.status == "draft")
        ).scalars()
    ]
    assert len(findings.list_findings(session, source_type="eda")) == 1
    assert len(findings.list_findings(session, status="approved")) == 1
```

Add a `session` fixture to `backend/tests/conftest.py` (next to the existing `client` fixture) so unit tests get a bare session without going through HTTP. Read the existing file first and mirror its engine/`tmp_path` setup:

```python
@pytest.fixture()
def session(tmp_path):
    """A bare SQLite session for module-level unit tests (no HTTP)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models import Base

    engine = create_engine(f"sqlite:///{tmp_path}/unit.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        yield s
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `poetry run pytest backend/tests/test_findings.py -v`
Expected: FAIL — `ImportError: cannot import name 'findings' from 'app'` and `cannot import name 'Finding' from 'app.models'`.

- [x] **Step 3: Add the `Finding` model**

In `backend/app/models.py`, insert after the `Experiment` class and before the `EMBEDDING_DIM` constant:

```python
class Finding(Base):
    """Reviewable model-written text that is not an experiment note (D22).

    `source_id` addresses `datasets.id` when `source_type == "eda"` and
    `experiments.id` when it is "diagnostic". A column cannot carry two foreign
    keys, so there is none — `app/findings.py` validates the reference at write
    time instead, the same trade-off D21 already accepted for the chunk table.
    """

    __tablename__ = "findings"
    __table_args__ = {"schema": "app"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Frozen at insert, never rewritten: without it the left-hand side of 2b.4's
    # draft-vs-edit diff is gone the moment the reviewer saves, and Phase 4 loses
    # its record of how much of the ground truth is the model's words.
    original_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

- [x] **Step 4: Write `app/findings.py`**

```python
"""Findings persistence and validation (D22).

Knows nothing about HTTP or LLMs. Routes translate `FindingError.status_code`
into an `HTTPException`; the LLM layer hands this module finished text.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Dataset, Experiment, Finding

SOURCE_TYPES = frozenset({"eda", "diagnostic"})
STATUSES = frozenset({"draft", "approved", "rejected"})


class FindingError(Exception):
    """A validation failure carrying the HTTP status a route should return."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _validate_source(session: Session, source_type: str, source_id: str) -> None:
    """The referential check the missing foreign key no longer performs.

    An unknown `source_id` is an error at write time, not a dangling row
    discovered later when Phase 3 retrieves a finding whose subject is gone.
    """
    if source_type not in SOURCE_TYPES:
        raise FindingError(422, f"unknown source_type; known: {sorted(SOURCE_TYPES)}")
    model = Dataset if source_type == "eda" else Experiment
    if session.get(model, source_id) is None:
        raise FindingError(404, f"no {source_type} source with id {source_id!r}")


def create_finding(session: Session, source_type: str, source_id: str, text: str) -> Finding:
    """Insert a draft finding. `original_text` is set here and never again."""
    _validate_source(session, source_type, source_id)
    row = Finding(
        source_type=source_type,
        source_id=source_id,
        text=text,
        original_text=text,
        status="draft",
    )
    session.add(row)
    session.flush()
    return row


def list_findings(
    session: Session,
    status: str | None = None,
    source_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Finding]:
    query = select(Finding).order_by(Finding.created_at.desc())
    if status:
        query = query.where(Finding.status == status)
    if source_type:
        query = query.where(Finding.source_type == source_type)
    return list(session.execute(query.limit(limit).offset(offset)).scalars())


def update_finding(
    session: Session,
    finding_id: str,
    text: str | None = None,
    status: str | None = None,
) -> Finding:
    """Edit the text, move the review status, or both (D20).

    Sending `text` alone is an edit and never an approval — the same rule
    `PATCH /experiments/{id}` established, for the same reason: a generator that
    writes through this path must not be able to bless its own output.
    """
    row = session.get(Finding, finding_id)
    if row is None:
        raise FindingError(404, "Finding not found")
    if text is not None:
        row.text = text
    if status is not None:
        if status not in STATUSES:
            raise FindingError(422, f"unknown status; known: {sorted(STATUSES)}")
        if status == "approved" and not row.text.strip():
            raise FindingError(422, "an empty finding cannot be approved")
        row.status = status
    session.flush()
    return row
```

- [x] **Step 5: Run the tests to verify they pass**

Run: `poetry run pytest backend/tests/test_findings.py -v`
Expected: PASS (11 tests).

- [x] **Step 6: Generate and review the migration**

```bash
make db-up
make migration m="add findings table"
```

Open the generated file under `backend/alembic/versions/`. Confirm it contains `op.create_table("findings", ..., schema="app")` with both indexes on `source_type` and `source_id`, and **nothing** touching MLflow's tables (the `app_schema_only` filter in `env.py` should ensure this — if MLflow tables appear, stop and fix the filter, do not hand-edit them out).

Then:

```bash
make migrate
```

- [x] **Step 7: Run the full gate and commit**

```bash
make check
git add backend/app/models.py backend/app/findings.py backend/tests/test_findings.py \
        backend/tests/conftest.py backend/alembic/versions/
git commit -m "feat: findings table and app/findings.py — reviewable text for EDA and diagnostics (D22)"
```

---

## Task 2: Migrate `experiment_note_chunks` to source types (2b.3)

**Files:**
- Modify: `backend/app/models.py:186-213` (the `ExperimentNoteChunk` class)
- Create: `backend/alembic/versions/<generated>_chunk_source_types.py`
- Modify: `backend/tests/test_models.py` (if a chunk test exists; otherwise create the assertions in `backend/tests/test_findings.py`)

**Interfaces:**
- Consumes: nothing from Task 1 — this is independent and can be reviewed on its own.
- Produces: `ExperimentNoteChunk` with `source_type`, `source_id`, `status`, and `UniqueConstraint("source_type", "source_id", "chunk_index")`. Phase 3's `app/embeddings.py` writes these columns.

The table is **empty**, so this is a pure schema change with no data migration step — which is precisely why D21 wanted it done before Phase 3 fills it.

- [x] **Step 1: Write the failing test**

Append to `backend/tests/test_findings.py`:

```python
def test_note_chunk_carries_source_type_and_status(session) -> None:
    """Phase 3 must be able to tell a note chunk from an EDA finding chunk
    from a diagnostic chunk without joining anything (D21)."""
    from app.models import EMBEDDING_DIM, ExperimentNoteChunk

    experiment = _experiment(session)
    chunk = ExperimentNoteChunk(
        source_type="note",
        source_id=experiment.id,
        chunk_text="ridge beat the baseline on rmse",
        chunk_index=0,
        status="approved",
        embedding=[0.0] * EMBEDDING_DIM,
    )
    session.add(chunk)
    session.flush()
    assert chunk.source_type == "note"
    assert chunk.status == "approved"


def test_note_chunk_status_defaults_to_draft(session) -> None:
    from app.models import EMBEDDING_DIM, ExperimentNoteChunk

    experiment = _experiment(session)
    chunk = ExperimentNoteChunk(
        source_type="note",
        source_id=experiment.id,
        chunk_text="text",
        chunk_index=0,
        embedding=[0.0] * EMBEDDING_DIM,
    )
    session.add(chunk)
    session.commit()
    session.refresh(chunk)
    assert chunk.status == "draft"
```

- [x] **Step 2: Run to verify it fails**

Run: `poetry run pytest backend/tests/test_findings.py -k note_chunk -v`
Expected: FAIL — `TypeError: 'source_type' is an invalid keyword argument for ExperimentNoteChunk`.

- [x] **Step 3: Rewrite the model**

Replace the `ExperimentNoteChunk` class in `backend/app/models.py` with:

```python
class ExperimentNoteChunk(Base):
    """A chunk of reviewable text plus its embedding (D6/D21). Written by
    Phase 3's app/embeddings.py; read by the agent's search_experiments tool.

    `source_type` discriminates the three content types Phase 3 retrieves over:
    "note" (experiments.notes), "eda", and "diagnostic" (both app.findings).
    Like `findings.source_id`, this addresses two tables and so carries no FK.
    """

    __tablename__ = "experiment_note_chunks"
    __table_args__ = (
        UniqueConstraint(
            "source_type", "source_id", "chunk_index", name="uq_note_chunks_source_chunk_index"
        ),
        {"schema": "app"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # Denormalised from the source row so a similarity search can filter to
    # approved text in the same query, without a UNION back to two tables.
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    # pgvector's VECTOR type has no SQLite equivalent, and the whole test suite
    # runs on SQLite. with_variant keeps one column definition serving both:
    # VECTOR(512) on Postgres, JSON on SQLite. Vector *operators* (<=>) remain
    # Postgres-only — Phase 3's similarity search is tested against Postgres.
    embedding: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_DIM).with_variant(JSON(), "sqlite"), nullable=False
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

- [x] **Step 4: Run to verify it passes**

Run: `poetry run pytest backend/tests/test_findings.py -k note_chunk -v`
Expected: PASS (2 tests).

- [x] **Step 5: Generate the migration and add the CASCADE comment**

```bash
make migration m="chunk source types"
make migrate
```

The autogenerated file drops `experiment_id` (and its FK) and adds the three columns. **Add this comment at the top of the `upgrade()` body** — the lost cascade is the real cost of this migration and must not be rediscovered as orphaned rows in retrieval results:

```python
    # Dropping experiment_id also drops its ON DELETE CASCADE. Deleting an
    # experiment no longer cleans up its chunks — source_id addresses two tables
    # and cannot carry a foreign key. Phase 3's app/embeddings.py owns that
    # cleanup explicitly. The table is empty at this migration, so there is no
    # data step.
```

- [x] **Step 6: Verify against Postgres**

This migration executes only on Postgres (SQLite uses `create_all`), so its correctness is not covered by a test:

```bash
make db-up && make migrate && make db-psql -- -c "\d app.experiment_note_chunks"
```

Expected: `source_type`, `source_id`, `status` present; no `experiment_id`; the unique constraint named `uq_note_chunks_source_chunk_index`.

- [x] **Step 7: Commit**

```bash
make check
git add backend/app/models.py backend/tests/test_findings.py backend/alembic/versions/
git commit -m "feat: migrate experiment_note_chunks to source_type/source_id/status (2b.3, D21)"
```

---

## Task 3: The findings read/write API

**Files:**
- Modify: `backend/app/schemas.py` (append)
- Create: `backend/app/routes/findings.py`
- Modify: `backend/app/main.py:37-39`
- Create: `backend/tests/test_findings_api.py`

**Interfaces:**
- Consumes: `findings.list_findings`, `findings.update_finding`, `findings.FindingError` (Task 1).
- Produces:
  - `schemas.FindingOut` — `id, source_type, source_id, text, original_text, status, created_at`
  - `schemas.FindingPatchRequest` — `text: str | None`, `status: str | None`
  - `GET /findings?status=&source_type=&limit=&offset=` → `list[FindingOut]`, newest first
  - `PATCH /findings/{id}` → `FindingOut`
  - Task 9's `frontend/src/api.ts` calls both.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_findings_api.py`:

```python
from app import findings
from app.models import Dataset


def _dataset_and_finding(client, text="draft text"):
    """Insert through the app's own session so the route sees the same DB."""
    from app.db import get_session
    from app.main import app

    session = next(app.dependency_overrides[get_session]())
    dataset = Dataset(name="d.csv", data_csv="a,b\n1,2\n", profile_json={}, content_hash="h1")
    session.add(dataset)
    session.flush()
    row = findings.create_finding(session, "eda", dataset.id, text)
    session.commit()
    return dataset.id, row.id


def test_list_findings_returns_newest_first(client) -> None:
    _dataset_and_finding(client, "first")
    _dataset_and_finding(client, "second")
    resp = client.get("/findings")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_findings_filters_by_status(client) -> None:
    _, finding_id = _dataset_and_finding(client)
    client.patch(f"/findings/{finding_id}", json={"status": "approved"})
    assert len(client.get("/findings?status=approved").json()) == 1
    assert client.get("/findings?status=draft").json() == []


def test_list_findings_filters_by_source_type(client) -> None:
    _dataset_and_finding(client)
    assert len(client.get("/findings?source_type=eda").json()) == 1
    assert client.get("/findings?source_type=diagnostic").json() == []


def test_patch_text_alone_does_not_approve(client) -> None:
    _, finding_id = _dataset_and_finding(client)
    resp = client.patch(f"/findings/{finding_id}", json={"text": "edited"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "edited"
    assert body["status"] == "draft"
    assert body["original_text"] == "draft text"


def test_patch_can_approve_explicitly(client) -> None:
    _, finding_id = _dataset_and_finding(client)
    resp = client.patch(f"/findings/{finding_id}", json={"text": "edited", "status": "approved"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


def test_approving_empty_finding_is_422(client) -> None:
    _, finding_id = _dataset_and_finding(client, text="  ")
    resp = client.patch(f"/findings/{finding_id}", json={"status": "approved"})
    assert resp.status_code == 422


def test_patch_unknown_finding_is_404(client) -> None:
    resp = client.patch("/findings/nope", json={"text": "x"})
    assert resp.status_code == 404
```

- [x] **Step 2: Run to verify it fails**

Run: `poetry run pytest backend/tests/test_findings_api.py -v`
Expected: FAIL — all requests return 404 (no route registered).

- [x] **Step 3: Add the schemas**

Append to `backend/app/schemas.py`:

```python
class FindingOut(BaseModel):
    id: str
    source_type: str
    source_id: str
    text: str
    original_text: str
    status: str
    created_at: dt.datetime


class FindingPatchRequest(BaseModel):
    text: str | None = None
    status: str | None = None


class FindingCreatedOut(BaseModel):
    """The 201 body of both generation endpoints (§4.4)."""

    finding_id: str
    source_type: str
    source_id: str
    status: str
    text: str
```

(If `dt` is not already imported in `schemas.py`, add `import datetime as dt` at the top — check first.)

- [x] **Step 4: Write the route module**

Create `backend/app/routes/findings.py`:

```python
"""Read and review endpoints for findings (D22).

The same D20 semantics as PATCH /experiments/{id}: sending `text` alone is an
edit, never an approval. Approval requires an explicit `status`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import findings
from app.db import get_session
from app.models import Finding
from app.schemas import FindingOut, FindingPatchRequest

router = APIRouter(prefix="/findings", tags=["findings"])


def _out(row: Finding) -> FindingOut:
    return FindingOut(
        id=row.id,
        source_type=row.source_type,
        source_id=row.source_id,
        text=row.text,
        original_text=row.original_text,
        status=row.status,
        created_at=row.created_at,
    )


@router.get("", response_model=list[FindingOut])
def list_findings(
    status: str | None = None,
    source_type: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> list[FindingOut]:
    rows = findings.list_findings(session, status, source_type, limit, offset)
    return [_out(r) for r in rows]


@router.patch("/{finding_id}", response_model=FindingOut)
def update_finding(
    finding_id: str,
    request: FindingPatchRequest,
    session: Session = Depends(get_session),
) -> FindingOut:
    try:
        row = findings.update_finding(session, finding_id, request.text, request.status)
    except findings.FindingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    session.commit()
    session.refresh(row)
    return _out(row)
```

- [x] **Step 5: Register the router**

In `backend/app/main.py`, add `findings` to the routes import and register it alongside the other three:

```python
    app.include_router(findings.router)
```

- [x] **Step 6: Run to verify it passes**

Run: `poetry run pytest backend/tests/test_findings_api.py -v`
Expected: PASS (7 tests).

- [x] **Step 7: Commit**

```bash
make check
git add backend/app/schemas.py backend/app/routes/findings.py backend/app/main.py \
        backend/tests/test_findings_api.py
git commit -m "feat: GET/PATCH /findings — the review API for EDA and diagnostic text"
```

---

## Task 4: Two new analysis tools — `error_by_group` and `line`

**Files:**
- Modify: `backend/app/analysis.py` (append two functions)
- Modify: `backend/app/tools.py` (two schema entries + two validation branches)
- Modify: `backend/app/charts.py:12-24` (two `_DISPATCH` entries)
- Modify: `backend/tests/test_analysis.py` and `backend/tests/test_tools.py` (append)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `analysis.error_by_group(df, group_column, error_column) -> tuple[str, dict[str, Any]]`
  - `analysis.line(df, x_column, y_columns: list[str]) -> tuple[str, dict[str, Any]]`
  - `_DISPATCH["error_by_group"]`, `_DISPATCH["line"]`
  - Tasks 7 and 8 rely on both being callable by the loop.

**Why these two exist (D27, amending D19).** `compare` aggregates across *two datasets*, not across groups within one, so per-ticker error is not expressible. `scatter` draws unordered points, so a learning curve and a residual trend are not readable. Without these, 2b.2 ships with two of its four items quietly dropped.

- [x] **Step 1: Write the failing analysis tests**

Append to `backend/tests/test_analysis.py`:

```python
def test_error_by_group_returns_png_and_per_group_means() -> None:
    df = pd.DataFrame(
        {
            "ticker": ["AAPL", "AAPL", "MSFT", "MSFT"],
            "abs_error": [1.0, 3.0, 10.0, 20.0],
        }
    )
    png, stats = analysis.error_by_group(df, "ticker", "abs_error")
    assert png  # base64 payload, non-empty
    assert stats["group_column"] == "ticker"
    assert stats["groups"]["AAPL"] == 2.0
    assert stats["groups"]["MSFT"] == 15.0
    assert stats["worst_group"] == "MSFT"


def test_error_by_group_ignores_rows_with_a_null_error() -> None:
    df = pd.DataFrame({"g": ["a", "a", "b"], "e": [2.0, None, 4.0]})
    _, stats = analysis.error_by_group(df, "g", "e")
    assert stats["groups"]["a"] == 2.0
    assert stats["n"] == 2


def test_line_plots_multiple_series_against_a_shared_x() -> None:
    df = pd.DataFrame(
        {
            "train_size": [10, 20, 30],
            "train_score": [5.0, 4.0, 3.5],
            "validation_score": [9.0, 8.0, 7.5],
        }
    )
    png, stats = analysis.line(df, "train_size", ["train_score", "validation_score"])
    assert png
    assert stats["x_column"] == "train_size"
    assert stats["series"]["train_score"]["last"] == 3.5
    assert stats["series"]["validation_score"]["last"] == 7.5
    assert stats["n"] == 3


def test_line_sorts_by_x_so_the_connecting_line_is_meaningful() -> None:
    """An unordered frame drawn as a line plot produces a zigzag that reads as
    instability in the data rather than in the row order."""
    df = pd.DataFrame({"x": [3, 1, 2], "y": [30.0, 10.0, 20.0]})
    _, stats = analysis.line(df, "x", ["y"])
    assert stats["series"]["y"]["first"] == 10.0
    assert stats["series"]["y"]["last"] == 30.0
```

- [x] **Step 2: Run to verify it fails**

Run: `poetry run pytest backend/tests/test_analysis.py -k "error_by_group or line" -v`
Expected: FAIL — `AttributeError: module 'app.analysis' has no attribute 'error_by_group'`.

- [x] **Step 3: Implement both functions**

Append to `backend/app/analysis.py` (follow the existing fresh-`Figure`-per-call pattern exactly — never touch pyplot):

```python
def error_by_group(
    df: pd.DataFrame, group_column: str, error_column: str
) -> tuple[str, dict[str, Any]]:
    """Mean error per group, as a bar chart. This is per-ticker error.

    `compare` aggregates across two datasets; this aggregates across groups
    within one, which is a different question and not expressible with it.
    """
    sub = df[[group_column, error_column]].copy()
    sub[error_column] = pd.to_numeric(sub[error_column], errors="coerce")
    sub = sub.dropna(subset=[error_column])
    means = sub.groupby(group_column)[error_column].mean().sort_values(ascending=False)
    fig = Figure(figsize=(6, 4))
    try:
        ax = fig.subplots()
        ax.bar([str(i) for i in means.index], means.to_numpy(), color="#4C72B0")
        ax.set_title(f"Mean {error_column} by {group_column}")
        ax.set_xlabel(group_column)
        ax.set_ylabel(f"mean {error_column}")
        ax.tick_params(axis="x", rotation=45)
        png = _fig_to_base64(fig)
    finally:
        fig.clear()
    stats: dict[str, Any] = {
        "group_column": group_column,
        "error_column": error_column,
        "n": int(len(sub)),
        "groups": {str(k): _nan_to_none(v) for k, v in means.items()},
        "worst_group": str(means.index[0]) if len(means) else None,
        "best_group": str(means.index[-1]) if len(means) else None,
    }
    return png, stats


def line(df: pd.DataFrame, x_column: str, y_columns: list[str]) -> tuple[str, dict[str, Any]]:
    """An ordered line plot of one or more series against a shared x.

    Sorting by x is the point: a learning curve or a residual-against-time plot
    drawn in arbitrary row order shows a zigzag that reads as instability in the
    data rather than in the row order.
    """
    columns = [x_column, *y_columns]
    sub = df[columns].apply(pd.to_numeric, errors="coerce").dropna()
    sub = sub.sort_values(x_column, kind="stable")
    fig = Figure(figsize=(6, 4))
    try:
        ax = fig.subplots()
        for column in y_columns:
            ax.plot(sub[x_column], sub[column], marker="o", label=column)
        ax.set_title(f"{', '.join(y_columns)} by {x_column}")
        ax.set_xlabel(x_column)
        if len(y_columns) > 1:
            ax.legend()
        else:
            ax.set_ylabel(y_columns[0])
        png = _fig_to_base64(fig)
    finally:
        fig.clear()
    stats: dict[str, Any] = {
        "x_column": x_column,
        "n": int(len(sub)),
        "series": {
            column: {
                "first": _nan_to_none(sub[column].iloc[0]) if len(sub) else None,
                "last": _nan_to_none(sub[column].iloc[-1]) if len(sub) else None,
                "min": _nan_to_none(sub[column].min()),
                "max": _nan_to_none(sub[column].max()),
                "mean": _nan_to_none(sub[column].mean()),
            }
            for column in y_columns
        },
    }
    return png, stats
```

- [x] **Step 4: Run to verify it passes**

Run: `poetry run pytest backend/tests/test_analysis.py -k "error_by_group or line" -v`
Expected: PASS (4 tests).

- [x] **Step 5: Write the failing tool-validation tests**

Append to `backend/tests/test_tools.py` (mirror the existing profile-shaped fixtures in that file):

```python
_PROFILE = {
    "columns": [
        {"name": "ticker", "dtype": "object", "n_null": 0},
        {"name": "abs_error", "dtype": "float64", "n_null": 0},
        {"name": "train_size", "dtype": "int64", "n_null": 0},
    ]
}


def test_error_by_group_accepts_a_categorical_group_and_numeric_error() -> None:
    err = validate_tool_call(
        "error_by_group",
        {"dataset_id": "d1", "group_column": "ticker", "error_column": "abs_error"},
        {"d1": _PROFILE},
    )
    assert err is None


def test_error_by_group_rejects_a_non_numeric_error_column() -> None:
    err = validate_tool_call(
        "error_by_group",
        {"dataset_id": "d1", "group_column": "abs_error", "error_column": "ticker"},
        {"d1": _PROFILE},
    )
    assert err == "Column must be numeric: ticker"


def test_error_by_group_rejects_an_unknown_group_column() -> None:
    err = validate_tool_call(
        "error_by_group",
        {"dataset_id": "d1", "group_column": "sector", "error_column": "abs_error"},
        {"d1": _PROFILE},
    )
    assert err == "Column not found: 'sector'"


def test_line_accepts_numeric_x_and_y_columns() -> None:
    err = validate_tool_call(
        "line",
        {"dataset_id": "d1", "x_column": "train_size", "y_columns": ["abs_error"]},
        {"d1": _PROFILE},
    )
    assert err is None


def test_line_rejects_an_empty_y_columns_list() -> None:
    err = validate_tool_call(
        "line", {"dataset_id": "d1", "x_column": "train_size", "y_columns": []}, {"d1": _PROFILE}
    )
    assert err == "line requires at least one y column"


def test_line_rejects_a_non_numeric_y_column() -> None:
    err = validate_tool_call(
        "line",
        {"dataset_id": "d1", "x_column": "train_size", "y_columns": ["ticker"]},
        {"d1": _PROFILE},
    )
    assert err == "Column must be numeric: ticker"
```

- [x] **Step 6: Run to verify it fails**

Run: `poetry run pytest backend/tests/test_tools.py -k "error_by_group or line" -v`
Expected: FAIL — `assert 'Unknown tool: error_by_group' is None`.

- [x] **Step 7: Add both tool schemas**

Append these two entries to `TOOL_DEFS` in `backend/app/tools.py`, after the `compare` entry:

```python
    {
        "name": "error_by_group",
        "description": (
            "Mean absolute error per group, as a bar chart. Use this to see which "
            "groups (e.g. which tickers) a model predicts worst."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_id": {
                    "type": "string",
                    "description": "The id of the dataset to read the columns from.",
                },
                "group_column": {
                    "type": "string",
                    "description": "The column to group by (e.g. a ticker or category column).",
                },
                "error_column": {
                    "type": "string",
                    "description": "The numeric error column to average within each group.",
                },
            },
            "required": ["dataset_id", "group_column", "error_column"],
        },
    },
    {
        "name": "line",
        "description": (
            "An ordered line plot of one or more numeric series against a shared x "
            "axis. Use this for learning curves and for residuals against time."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_id": {
                    "type": "string",
                    "description": "The id of the dataset to read the columns from.",
                },
                "x_column": {
                    "type": "string",
                    "description": "The numeric column for the x-axis; rows are sorted by it.",
                },
                "y_columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "One or more numeric columns to draw as series.",
                },
            },
            "required": ["dataset_id", "x_column", "y_columns"],
        },
    },
```

- [x] **Step 8: Add both validation branches**

In `backend/app/tools.py`, insert these two blocks in `validate_tool_call` **after** the `correlation_matrix` branch and **before** the trailing `compare` block (which has no `if` guard and must stay last):

```python
    if name == "error_by_group":
        group_column = args.get("group_column")
        error_column = args.get("error_column")
        if not isinstance(group_column, str) or group_column not in columns_by_name:
            return f"Column not found: {group_column!r}"
        if not isinstance(error_column, str) or error_column not in columns_by_name:
            return f"Column not found: {error_column!r}"
        # The group column is deliberately NOT required to be numeric — grouping
        # by ticker is the whole point. Only the error being averaged must be.
        if error_column not in numeric_columns:
            return f"Column must be numeric: {error_column}"
        return None

    if name == "line":
        x_column = args.get("x_column")
        y_columns = args.get("y_columns")
        if not isinstance(x_column, str) or x_column not in columns_by_name:
            return f"Column not found: {x_column!r}"
        if x_column not in numeric_columns:
            return f"Column must be numeric: {x_column}"
        if not isinstance(y_columns, list) or not y_columns:
            return "line requires at least one y column"
        for column in y_columns:
            if not isinstance(column, str) or column not in columns_by_name:
                return f"Column not found: {column!r}"
            if column not in numeric_columns:
                return f"Column must be numeric: {column}"
        return None
```

- [x] **Step 9: Add both to `_DISPATCH`**

In `backend/app/charts.py`, add to the `_DISPATCH` dict and extend the import from `app.analysis`:

```python
    "error_by_group": lambda dfs, args: error_by_group(
        dfs[args["dataset_id"]], args["group_column"], args["error_column"]
    ),
    "line": lambda dfs, args: line(dfs[args["dataset_id"]], args["x_column"], args["y_columns"]),
```

- [x] **Step 10: Run everything and commit**

Run: `poetry run pytest backend/tests/test_tools.py backend/tests/test_analysis.py -v`
Expected: PASS (all, including the pre-existing tests).

```bash
make check
git add backend/app/analysis.py backend/app/tools.py backend/app/charts.py \
        backend/tests/test_analysis.py backend/tests/test_tools.py
git commit -m "feat: error_by_group and line analysis tools (D27)"
```

---

## Task 5: `app/diagnostics.py` — the residual frame

**Files:**
- Create: `backend/app/diagnostics.py`
- Create: `backend/tests/test_diagnostics.py`

**Interfaces:**
- Consumes: `training.prepare`, `training.split_frame`, `training.cv_splitter`.
- Produces:
  - `diagnostics.residual_frame(model, frame, target_column, feature_columns, time_column, id_columns=()) -> pd.DataFrame` with columns `actual, predicted, residual, abs_error` plus each requested id column and the time column.
  - `diagnostics.learning_curve_frame(model, frame, target_column, feature_columns, time_column, scoring="neg_root_mean_squared_error") -> pd.DataFrame` with columns `train_size, train_score, validation_score`.
  - Task 8's route calls both.

**Signature note.** The design (§4.2) writes these as `(model, frame, target_column, time_column)`. `training.prepare` requires the feature list, and the route has it — MLflow logs it as the `feature_columns` param. So `feature_columns` is a real parameter here rather than something re-inferred; re-inferring it would risk diagnosing a *different* feature set than the run used, which is the exact class of silent wrongness this module exists to avoid.

Neither function loads anything, calls an LLM, or touches the database.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_diagnostics.py`:

```python
import numpy as np
import pandas as pd

from app import diagnostics, training


def _panel() -> pd.DataFrame:
    """40 rows, two tickers, a clean linear relationship and a time axis."""
    return pd.DataFrame(
        {
            "quarter_end": pd.date_range("2015-03-31", periods=40, freq="QE").astype(str),
            "ticker": ["AAPL", "MSFT"] * 20,
            "revenue": np.arange(40, dtype=float) * 100.0,
            "revenue_next": np.arange(40, dtype=float) * 100.0 + 50.0,
        }
    )


def _fitted(frame, features, time_column="quarter_end"):
    x, y = training.prepare(frame, "revenue_next", features, time_column)
    pipeline = training.build_pipeline("ridge", {}, ["revenue"], ["ticker"])
    x_train, _, y_train, _ = training.split_frame(x, y, chronological=time_column is not None)
    pipeline.fit(x_train, y_train)
    return pipeline


def test_residual_frame_scores_exactly_the_rows_split_frame_held_out() -> None:
    """The assertion that matters. A diagnostic computed on the wrong split is
    entirely plausible-looking and completely wrong."""
    frame = _panel()
    features = ["revenue", "ticker"]
    model = _fitted(frame, features)
    x, y = training.prepare(frame, "revenue_next", features, "quarter_end")
    _, x_test, _, y_test = training.split_frame(x, y, chronological=True)

    out = diagnostics.residual_frame(
        model, frame, "revenue_next", features, "quarter_end", id_columns=("ticker",)
    )
    assert len(out) == len(x_test)
    assert out["actual"].tolist() == y_test.tolist()


def test_residual_frame_columns_and_arithmetic() -> None:
    frame = _panel()
    features = ["revenue", "ticker"]
    out = diagnostics.residual_frame(
        _fitted(frame, features), frame, "revenue_next", features, "quarter_end",
        id_columns=("ticker",),
    )
    for column in ("actual", "predicted", "residual", "abs_error", "ticker", "quarter_end"):
        assert column in out.columns
    assert np.allclose(out["residual"], out["actual"] - out["predicted"])
    assert (out["abs_error"] >= 0).all()


def test_residual_frame_carries_identifiers_from_the_right_rows() -> None:
    """Identifiers are re-attached by index, not by position — a positional
    join against a time-sorted frame silently mislabels every row."""
    frame = _panel()
    features = ["revenue", "ticker"]
    out = diagnostics.residual_frame(
        _fitted(frame, features), frame, "revenue_next", features, "quarter_end",
        id_columns=("ticker",),
    )
    assert set(out["ticker"]) <= {"AAPL", "MSFT"}
    # The holdout is the tail of the time-sorted frame, so its quarter_end
    # values must all be later than the training rows'.
    assert out["quarter_end"].min() > frame["quarter_end"].sort_values().iloc[0]


def test_learning_curve_frame_shape_and_monotonic_train_size() -> None:
    frame = _panel()
    features = ["revenue", "ticker"]
    out = diagnostics.learning_curve_frame(
        _fitted(frame, features), frame, "revenue_next", features, "quarter_end"
    )
    assert list(out.columns) == ["train_size", "train_score", "validation_score"]
    assert len(out) >= 3
    assert out["train_size"].is_monotonic_increasing


def test_learning_curve_frame_uses_timeseriessplit_when_time_column_given(monkeypatch) -> None:
    """A learning curve built on shuffled folds for a temporal run reports
    optimistic scores at every training size."""
    from sklearn.model_selection import TimeSeriesSplit

    seen = {}
    real = training.cv_splitter

    def spy(chronological):
        seen["chronological"] = chronological
        return real(chronological)

    monkeypatch.setattr(diagnostics.training, "cv_splitter", spy)
    frame = _panel()
    features = ["revenue", "ticker"]
    diagnostics.learning_curve_frame(
        _fitted(frame, features), frame, "revenue_next", features, "quarter_end"
    )
    assert seen["chronological"] is True
    assert isinstance(real(True), TimeSeriesSplit)


def test_learning_curve_frame_is_random_split_without_a_time_column() -> None:
    frame = _panel().drop(columns=["quarter_end"])
    features = ["revenue", "ticker"]
    model = _fitted(frame, features, time_column=None)
    out = diagnostics.learning_curve_frame(model, frame, "revenue_next", features, None)
    assert len(out) >= 3
```

- [x] **Step 2: Run to verify it fails**

Run: `poetry run pytest backend/tests/test_diagnostics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.diagnostics'`.

- [x] **Step 3: Implement the module**

Create `backend/app/diagnostics.py`:

```python
"""Residual and learning-curve frames for a fitted run (2b.2).

Two pure functions. Neither loads anything, calls an LLM, nor touches the
database — each takes an already-loaded pipeline and returns a DataFrame.

**Why both return frames.** `charts.py:_DISPATCH` hands tools a dict of
DataFrames and nothing else; a tool has no route to a fitted estimator.
Computing here and handing the loop a frame keeps every tool a pure function of
a DataFrame, which is the property that makes the whole chart layer testable.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import learning_curve

from app import training


def residual_frame(
    model: Any,
    frame: pd.DataFrame,
    target_column: str,
    feature_columns: list[str],
    time_column: str | None,
    id_columns: Sequence[str] = (),
) -> pd.DataFrame:
    """Actual vs. predicted on the run's own holdout, plus identifying columns.

    The split is re-derived with `training.split_frame` rather than re-cut here,
    so the rows scored are identical to the rows the run was scored on. A
    diagnostic computed on a different split is plausible-looking and wrong.
    """
    x, y = training.prepare(frame, target_column, feature_columns, time_column)
    _, x_test, _, y_test = training.split_frame(x, y, chronological=time_column is not None)
    predicted = np.asarray(model.predict(x_test), dtype=float)

    out = pd.DataFrame(
        {"actual": y_test.to_numpy(dtype=float), "predicted": predicted},
        index=x_test.index,
    )
    out["residual"] = out["actual"] - out["predicted"]
    out["abs_error"] = out["residual"].abs()
    # Re-attached by INDEX, not by position: `prepare` sorts by time, so a
    # positional join against the original frame mislabels every row.
    wanted = [*id_columns, *([time_column] if time_column else [])]
    for column in wanted:
        if column in frame.columns:
            out[column] = frame.loc[out.index, column]
    return out.reset_index(drop=True)


def learning_curve_frame(
    model: Any,
    frame: pd.DataFrame,
    target_column: str,
    feature_columns: list[str],
    time_column: str | None,
    scoring: str = "neg_root_mean_squared_error",
) -> pd.DataFrame:
    """One row per training size: train_size, train_score, validation_score.

    Uses the same `cv_splitter` the run was scored with, so a temporal run gets
    `TimeSeriesSplit`. Scores are returned in the metric's natural orientation
    (lower rmse is better), so the "neg_" sign is undone here.
    """
    chronological = time_column is not None
    x, y = training.prepare(frame, target_column, feature_columns, time_column)
    x_train, _, y_train, _ = training.split_frame(x, y, chronological=chronological)
    sizes, train_scores, validation_scores = learning_curve(
        model,
        x_train,
        y_train,
        cv=training.cv_splitter(chronological),
        scoring=scoring,
        train_sizes=np.linspace(0.3, 1.0, 5),
        shuffle=False,
    )
    sign = -1.0 if scoring.startswith("neg_") else 1.0
    return pd.DataFrame(
        {
            "train_size": sizes.astype(float),
            "train_score": sign * train_scores.mean(axis=1),
            "validation_score": sign * validation_scores.mean(axis=1),
        }
    )
```

- [x] **Step 4: Run to verify it passes**

Run: `poetry run pytest backend/tests/test_diagnostics.py -v`
Expected: PASS (7 tests).

- [x] **Step 5: Commit**

```bash
make check
git add backend/app/diagnostics.py backend/tests/test_diagnostics.py
git commit -m "feat: app/diagnostics.py — residual and learning-curve frames on the run's own split"
```

---

## Task 6: The persistence baseline

**Files:**
- Modify: `backend/app/training.py` — add `PriorValueRegressor` (before `MODEL_REGISTRY`), `ModelSpec.preprocess`, the `persistence` entry, and the `build_pipeline` branch at `backend/app/training.py:195-237`
- Modify: `backend/app/routes/experiments.py` — reject `/tune` on an empty search space
- Create: `backend/tests/test_baseline.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `training.PriorValueRegressor(prior_column: str = "")` — a real `BaseEstimator`/`RegressorMixin`
  - `training.ModelSpec.preprocess: bool = True`
  - `MODEL_REGISTRY["persistence"]`
  - Task 10 fits it via `POST /experiments/train`.

**Why this is a registry entry (D25).** The baseline becomes a real logged run: on the leaderboard, in the compare table, able to carry its own note, retrievable by Phase 3. "Did anything beat persistence" becomes sorting a column rather than reading prose.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_baseline.py`:

```python
import numpy as np
import pandas as pd
import pytest

from app import training


def _panel() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "quarter_end": pd.date_range("2015-03-31", periods=40, freq="QE").astype(str),
            "ticker": ["AAPL", "MSFT"] * 20,
            "revenue": np.arange(40, dtype=float) * 100.0,
            "revenue_next": np.arange(40, dtype=float) * 100.0 + 50.0,
        }
    )


def test_persistence_is_registered_as_a_regression_model() -> None:
    spec = training.MODEL_REGISTRY["persistence"]
    assert spec.task_type == "regression"
    assert spec.objective_metric == "rmse"
    assert spec.direction == "minimize"
    assert spec.preprocess is False


def test_persistence_search_space_is_empty_so_tuning_is_meaningless() -> None:
    assert training.MODEL_REGISTRY["persistence"].search_space == {}


def test_prior_value_regressor_predicts_the_prior_column_unchanged() -> None:
    """Tested THROUGH the pipeline, not in isolation — that is what catches a
    regression if anyone flips `preprocess` back to the default. Inside the
    standard pipeline the estimator would receive a SCALED prior value and could
    never emit raw dollars; the baseline would be silently wrong, not fail."""
    pipeline = training.build_pipeline(
        "persistence", {"prior_column": "revenue"}, ["revenue"], ["ticker"]
    )
    x = pd.DataFrame({"revenue": [100.0, 200.0, 300.0], "ticker": ["A", "B", "A"]})
    y = pd.Series([150.0, 250.0, 350.0])
    pipeline.fit(x, y)
    assert pipeline.predict(x).tolist() == [100.0, 200.0, 300.0]


def test_persistence_pipeline_has_no_preprocessing_step() -> None:
    pipeline = training.build_pipeline("persistence", {"prior_column": "revenue"}, ["revenue"], [])
    assert [name for name, _ in pipeline.steps] == ["model"]


def test_other_models_keep_their_preprocessing_step() -> None:
    pipeline = training.build_pipeline("ridge", {}, ["revenue"], ["ticker"])
    assert [name for name, _ in pipeline.steps] == ["pre", "model"]


def test_persistence_is_clonable_so_cross_val_score_works() -> None:
    from sklearn.base import clone

    estimator = training.PriorValueRegressor(prior_column="revenue")
    assert clone(estimator).get_params()["prior_column"] == "revenue"


def test_persistence_scores_end_to_end_through_fit_and_score() -> None:
    result = training.fit_and_score(
        "persistence",
        {"prior_column": "revenue"},
        _panel(),
        "revenue_next",
        ["revenue", "ticker"],
        "quarter_end",
    )
    assert result.status == "FINISHED"
    # revenue_next is always revenue + 50, so persistence is off by exactly 50.
    assert result.metrics["rmse"] == pytest.approx(50.0)
    assert result.metrics["mae"] == pytest.approx(50.0)


def test_persistence_with_an_unknown_prior_column_fails_as_data_not_a_crash() -> None:
    result = training.fit_and_score(
        "persistence",
        {"prior_column": "nope"},
        _panel(),
        "revenue_next",
        ["revenue"],
        "quarter_end",
    )
    assert result.status == "FAILED"
    assert "nope" in (result.error or "")
```

And append to `backend/tests/test_experiments.py` (the existing route test module):

```python
def test_tuning_a_model_with_an_empty_search_space_is_422(client) -> None:
    """Eight identical trials is not a search. Rejected rather than run."""
    dataset_id = _upload(client)
    resp = client.post(
        "/experiments/tune",
        json={
            "dataset_id": dataset_id,
            "model_type": "persistence",
            "target_column": "revenue_next",
            "n_trials": 8,
        },
    )
    assert resp.status_code == 422
    assert "search space" in resp.json()["detail"].lower()
```

- [x] **Step 2: Run to verify it fails**

Run: `poetry run pytest backend/tests/test_baseline.py -v`
Expected: FAIL — `KeyError: 'persistence'` and `AttributeError: module 'app.training' has no attribute 'PriorValueRegressor'`.

- [x] **Step 3: Add `PriorValueRegressor` and the `preprocess` field**

In `backend/app/training.py`, add to the sklearn imports:

```python
from sklearn.base import BaseEstimator, RegressorMixin
```

Add the `preprocess` field to `ModelSpec` (last, so it can carry a default):

```python
    cv_scoring: str  # an sklearn scorer name for cross_val_score
    # When False, build_pipeline returns a bare Pipeline([("model", ...)]) and
    # the estimator receives the DataFrame with its column names intact. Only
    # the persistence baseline needs this: inside the standard pipeline it would
    # receive a SCALED prior value and could never emit raw dollars — the
    # baseline would be silently wrong rather than fail (D25).
    preprocess: bool = True
```

Insert `PriorValueRegressor` immediately before `MODEL_REGISTRY`:

```python
class PriorValueRegressor(BaseEstimator, RegressorMixin):  # type: ignore[misc]
    """Predicts next period's value as this period's: `revenue_next = revenue`.

    A real estimator rather than a number computed in a notebook, so the
    baseline is a logged run on the leaderboard that any model must beat before
    it is worth reporting (D25). `prior_column` arrives through the existing
    `hyperparams` dict, so no request field is added.
    """

    def __init__(self, prior_column: str = "") -> None:
        # sklearn's clone() requires __init__ params to be stored unmodified
        # under their own names. Anything else here breaks cross_val_score.
        self.prior_column = prior_column

    def fit(self, X: pd.DataFrame, y: Any = None) -> PriorValueRegressor:  # noqa: N803
        if self.prior_column not in X.columns:
            raise ValueError(
                f"prior_column {self.prior_column!r} is not among the feature columns "
                f"{sorted(X.columns)}"
            )
        self.is_fitted_ = True
        return self

    def predict(self, X: pd.DataFrame) -> Any:  # noqa: N803
        return X[self.prior_column].to_numpy(dtype=float)
```

Add the registry entry after `random_forest_clf`:

```python
    # Scoped to the temporal panel: predicting "next quarter equals this
    # quarter" is meaningless on the cross-sectional components dataset, and
    # nothing forces a caller to fit it there.
    "persistence": ModelSpec(
        task_type="regression",
        factory=PriorValueRegressor,
        search_space={},  # nothing to tune; /tune rejects it rather than running duplicates
        objective_metric="rmse",
        direction="minimize",
        cv_scoring="neg_root_mean_squared_error",
        preprocess=False,
    ),
```

- [x] **Step 4: Branch in `build_pipeline`**

Replace the body of `build_pipeline` in `backend/app/training.py:195-237` so the estimator is built first and the preprocessing block is skipped when the spec asks for it:

```python
def build_pipeline(
    model_type: str, hyperparams: dict[str, Any], numeric: list[str], categorical: list[str]
) -> Pipeline:
    if model_type not in MODEL_REGISTRY:
        raise ValueError(f"unknown model_type {model_type!r}; known: {sorted(MODEL_REGISTRY)}")
    spec = MODEL_REGISTRY[model_type]
    estimator = spec.factory(**hyperparams)
    # Seed anything stochastic (the forests, gradient boosting's subsampling) so
    # re-running an experiment reproduces its metrics — otherwise two rows in the
    # MLflow history differ by noise and the comparison Phase 3 retrieves is
    # meaningless. An explicit random_state in hyperparams still wins.
    if "random_state" in estimator.get_params() and "random_state" not in hyperparams:
        estimator.set_params(random_state=settings.train_test_seed)
    if not spec.preprocess:
        # The estimator reads named columns off the DataFrame itself (D25).
        return Pipeline([("model", estimator)])
    # Scaling lives INSIDE the pipeline so cross_val_score refits it per fold.
    # Scaling before the split fits the scaler on the test rows — a quiet leak
    # that no metric reveals (design §3.6).
    # sparse_output=False keeps the matrix dense: at these row counts the memory
    # cost is nil, and every estimator accepts it without a sparse-support caveat.
    pre = ColumnTransformer(
        [
            (
                "num",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="median")),
                        ("scale", StandardScaler()),
                    ]
                ),
                numeric,
            ),
            (
                "cat",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        ("ohe", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
                    ]
                ),
                categorical,
            ),
        ],
        remainder="drop",
    )
    return Pipeline([("pre", pre), ("model", estimator)])
```

- [x] **Step 5: Reject tuning an empty search space**

In `backend/app/routes/experiments.py`, in `tune_experiment`, add immediately after `spec = training.MODEL_REGISTRY[request.model_type]`:

```python
    if not spec.search_space:
        raise HTTPException(
            status_code=422,
            detail=f"{request.model_type!r} has an empty search space; there is nothing to tune",
        )
```

- [x] **Step 6: Run to verify it passes**

Run: `poetry run pytest backend/tests/test_baseline.py backend/tests/test_experiments.py backend/tests/test_training.py -v`
Expected: PASS. Every pre-existing training test must still pass — `preprocess` defaults to `True`, so no existing spec changes behaviour.

- [x] **Step 7: Commit**

```bash
make check
git add backend/app/training.py backend/app/routes/experiments.py \
        backend/tests/test_baseline.py backend/tests/test_experiments.py
git commit -m "feat: persistence baseline as a MODEL_REGISTRY entry via ModelSpec.preprocess (D25)"
```

---

## Task 7: `POST /datasets/{id}/eda`

**Files:**
- Modify: `backend/app/routes/datasets.py` (append the route; import `run_loop`, `findings`, `profile_dataframe`)
- Create: `backend/tests/test_eda_route.py`

**Interfaces:**
- Consumes: `findings.create_finding` (Task 1), `analysis.error_by_group`/`line` via the loop (Task 4), `app.loop.run_loop`, `app.profiler.profile_dataframe`, `app.dataset_io.load_csv`.
- Produces: `POST /datasets/{id}/eda` → **201** `FindingCreatedOut`. Task 9's `runEda` calls it; Task 10 runs it for real.

**The EDA question** is fixed in the route rather than taken from the caller — this endpoint produces one specific artifact type, and a free-text question would make it `/chats` with extra steps.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_eda_route.py`:

```python
import pytest

import app.routes.datasets as datasets_route
from app.loop import LoopResult

_CSV = "ticker,quarter_end,revenue,revenue_next\nAAPL,2015-03-31,100,150\nMSFT,2015-06-30,200,250\n"


def _fake_loop(monkeypatch, text="Revenue is right-skewed across both tickers.") -> None:
    def fake_run_loop(datasets, dfs, prior_messages, question, *, client=None):
        # The route must hand the loop the dataset it was asked about, profiled.
        assert len(datasets) == 1
        assert datasets[0]["profile"]["columns"]
        return LoopResult(interpretation=text, pass_count=2, judge_score=85)

    monkeypatch.setattr(datasets_route, "run_loop", fake_run_loop)


def _upload(client) -> str:
    return client.post("/datasets", files={"file": ("panel.csv", _CSV, "text/csv")}).json()["id"]


def test_eda_creates_a_draft_finding(client, monkeypatch) -> None:
    _fake_loop(monkeypatch)
    dataset_id = _upload(client)
    resp = client.post(f"/datasets/{dataset_id}/eda")
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "draft"
    assert body["source_type"] == "eda"
    assert body["source_id"] == dataset_id
    assert body["text"] == "Revenue is right-skewed across both tickers."


def test_eda_finding_is_readable_through_the_findings_api(client, monkeypatch) -> None:
    _fake_loop(monkeypatch)
    dataset_id = _upload(client)
    finding_id = client.post(f"/datasets/{dataset_id}/eda").json()["finding_id"]
    listed = client.get("/findings?source_type=eda").json()
    assert [f["id"] for f in listed] == [finding_id]
    assert listed[0]["original_text"] == listed[0]["text"]


def test_eda_on_an_unknown_dataset_is_404(client, monkeypatch) -> None:
    _fake_loop(monkeypatch)
    resp = client.post("/datasets/no-such-id/eda")
    assert resp.status_code == 404


def test_eda_writes_no_finding_when_the_loop_fails(client, monkeypatch) -> None:
    """A loop failure surfaces exactly as it does on /chats — unwrapped. The
    guarantee this test pins is the other half: no partial finding is written,
    because `create_finding` is only reached after the loop returns."""

    def boom(datasets, dfs, prior_messages, question, *, client=None):
        raise RuntimeError("anthropic exploded")

    monkeypatch.setattr(datasets_route, "run_loop", boom)
    dataset_id = _upload(client)
    with pytest.raises(RuntimeError):
        client.post(f"/datasets/{dataset_id}/eda")
    assert client.get("/findings").json() == []


def test_eda_never_inserts_the_dataset_twice(client, monkeypatch) -> None:
    """D13: the EDA path reads `datasets`, it does not write to it."""
    _fake_loop(monkeypatch)
    dataset_id = _upload(client)
    client.post(f"/datasets/{dataset_id}/eda")
    assert len(client.get("/datasets").json()) == 1
```

- [x] **Step 2: Run to verify it fails**

Run: `poetry run pytest backend/tests/test_eda_route.py -v`
Expected: FAIL — 405/404 on `POST /datasets/{id}/eda`.

- [x] **Step 3: Implement the route**

Append to `backend/app/routes/datasets.py` (add the imports it needs at the top: `from app import findings`, `from app.loop import run_loop`, `from app.schemas import FindingCreatedOut`, and `from app.config import settings` / `from app.profiler import profile_dataframe` if not already present):

```python
EDA_QUESTION = (
    "Perform exploratory data analysis on this dataset. Describe the distribution of the "
    "key numeric columns, the coverage of each group (for example, rows per ticker), and "
    "the correlation structure between the candidate features and the target. Call out "
    "anything a modeller should know before fitting: skew, gaps, outliers, or columns that "
    "look like leakage. Be specific and quantitative."
)


@router.post("/{dataset_id}/eda", status_code=201, response_model=FindingCreatedOut)
def run_eda(dataset_id: str, session: Session = Depends(get_session)) -> FindingCreatedOut:
    """Generate a reviewable EDA write-up for one dataset (2b.1).

    Calls `run_loop` synchronously, exactly as `/chats` does — no new LLM
    machinery (D19/D23). Charts are rendered for the judge and discarded; only
    the findings text persists.
    """
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    df = load_csv(dataset.data_csv)
    profile = profile_dataframe(
        df,
        sample_rows=settings.profile_sample_rows,
        max_cardinality=settings.profile_max_cardinality,
        max_corr_cols=settings.profile_max_corr_cols,
        top_corr_pairs=settings.profile_top_corr_pairs,
        token_budget=settings.profile_token_budget,
    )
    # Deliberately NOT wrapped: `/chats` lets a loop failure propagate, and this
    # endpoint uses the same mapping (§6). The "no partial finding" guarantee
    # comes from ordering, not from a handler — create_finding is below the loop,
    # so a failure leaves nothing half-generated in the review queue.
    result = run_loop(
        [{"id": dataset.id, "name": dataset.name, "profile": profile}],
        {dataset.id: df},
        [],
        EDA_QUESTION,
    )

    row = findings.create_finding(session, "eda", dataset.id, result.interpretation)
    session.commit()
    session.refresh(row)
    return FindingCreatedOut(
        finding_id=row.id,
        source_type=row.source_type,
        source_id=row.source_id,
        status=row.status,
        text=row.text,
    )
```

- [x] **Step 4: Run to verify it passes**

Run: `poetry run pytest backend/tests/test_eda_route.py -v`
Expected: PASS (5 tests).

- [x] **Step 5: Commit**

```bash
make check
git add backend/app/routes/datasets.py backend/tests/test_eda_route.py
git commit -m "feat: POST /datasets/{id}/eda — reviewable EDA findings (2b.1)"
```

---

## Task 8: `POST /experiments/{id}/diagnostics`

**Files:**
- Modify: `backend/app/routes/experiments.py` (append the route)
- Create: `backend/tests/test_diagnostics_route.py`

**Interfaces:**
- Consumes: `diagnostics.residual_frame`/`learning_curve_frame` (Task 5), `findings.create_finding` (Task 1), `experiment_log.fetch_runs`, `mlflow.sklearn.load_model`, `run_loop`.
- Produces: `POST /experiments/{id}/diagnostics` → **201** `FindingCreatedOut`. Task 9's `runDiagnostics` calls it; Task 10 runs it for real.

**Why the logged model and never a refit (D24).** Refitting from logged params produces a close-but-different model reported as the one that was scored — the worse failure, because nothing about it looks wrong. A missing artifact is a 409.

The two derived frames go to `run_loop` as in-memory datasets with ephemeral ids. The loop is already multi-dataset (issue #6), so two frames need no new plumbing. Neither is **ever** inserted into `datasets` — D13 makes that table the single *source*-data path, and a derived diagnostic frame is not source data.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_diagnostics_route.py`:

```python
import numpy as np
import pandas as pd
import pytest

import app.routes.experiments as experiments_route
from app import experiment_log, training
from app.dataset_io import load_csv
from app.loop import LoopResult
from app.models import Experiment

_CSV = pd.DataFrame(
    {
        "quarter_end": pd.date_range("2015-03-31", periods=40, freq="QE").astype(str),
        "ticker": ["AAPL", "MSFT"] * 20,
        "revenue": np.arange(40, dtype=float) * 100.0,
        "revenue_next": np.arange(40, dtype=float) * 100.0 + 50.0,
    }
).to_csv(index=False)


def _upload(client) -> str:
    return client.post("/datasets", files={"file": ("panel.csv", _CSV, "text/csv")}).json()["id"]


def _experiment(client, dataset_id, status="FINISHED", task_type="regression") -> str:
    from app.db import get_session
    from app.main import app

    session = next(app.dependency_overrides[get_session]())
    row = Experiment(
        mlflow_run_id="run-1",
        dataset_id=dataset_id,
        model_type="ridge",
        task_type=task_type,
    )
    session.add(row)
    session.commit()
    return row.id


def _fake_mlflow(monkeypatch, status="FINISHED", model=None, load_raises=None) -> None:
    """Stub the MLflow boundary: the run's metadata and its logged model."""
    run = experiment_log.RunData(
        run_id="run-1",
        status=status,
        params={
            "target_column": "revenue_next",
            "feature_columns": "revenue,ticker",
            "time_column": "quarter_end",
        },
        metrics={"rmse": 42.0},
    )
    monkeypatch.setattr(experiments_route.experiment_log, "fetch_runs", lambda ids: {"run-1": run})

    def fake_load(uri):
        if load_raises is not None:
            raise load_raises
        return model

    monkeypatch.setattr(experiments_route, "load_logged_model", fake_load)


def _fitted_model():
    frame = load_csv(_CSV)
    x, y = training.prepare(frame, "revenue_next", ["revenue", "ticker"], "quarter_end")
    pipeline = training.build_pipeline("ridge", {}, ["revenue"], ["ticker"])
    x_train, _, y_train, _ = training.split_frame(x, y, chronological=True)
    pipeline.fit(x_train, y_train)
    return pipeline


def _fake_loop(monkeypatch, text="Residuals grow in the last four quarters.") -> None:
    def fake_run_loop(datasets, dfs, prior_messages, question, *, client=None):
        # Both derived frames must reach the loop, and neither may be a dataset row.
        assert len(datasets) == 2
        assert {d["name"] for d in datasets} == {"residuals", "learning_curve"}
        return LoopResult(interpretation=text, pass_count=2, judge_score=90)

    monkeypatch.setattr(experiments_route, "run_loop", fake_run_loop)


def test_diagnostics_creates_a_draft_finding(client, monkeypatch) -> None:
    dataset_id = _upload(client)
    experiment_id = _experiment(client, dataset_id)
    _fake_mlflow(monkeypatch, model=_fitted_model())
    _fake_loop(monkeypatch)

    resp = client.post(f"/experiments/{experiment_id}/diagnostics")
    assert resp.status_code == 201
    body = resp.json()
    assert body["source_type"] == "diagnostic"
    assert body["source_id"] == experiment_id
    assert body["status"] == "draft"


def test_diagnostics_on_an_unknown_experiment_is_404(client, monkeypatch) -> None:
    resp = client.post("/experiments/no-such-id/diagnostics")
    assert resp.status_code == 404


def test_diagnostics_on_a_failed_run_is_409(client, monkeypatch) -> None:
    """There is no logged model to load."""
    dataset_id = _upload(client)
    experiment_id = _experiment(client, dataset_id)
    _fake_mlflow(monkeypatch, status="FAILED", model=None)
    resp = client.post(f"/experiments/{experiment_id}/diagnostics")
    assert resp.status_code == 409
    assert "FAILED" in resp.json()["detail"]


def test_diagnostics_with_a_missing_artifact_is_409_naming_the_run(client, monkeypatch) -> None:
    dataset_id = _upload(client)
    experiment_id = _experiment(client, dataset_id)
    _fake_mlflow(monkeypatch, model=None, load_raises=OSError("no such artifact"))
    resp = client.post(f"/experiments/{experiment_id}/diagnostics")
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "run-1" in detail and "model" in detail


def test_diagnostics_on_a_classification_run_is_409(client, monkeypatch) -> None:
    """Residuals are regression-only; 2b scopes to the panel."""
    dataset_id = _upload(client)
    experiment_id = _experiment(client, dataset_id, task_type="classification")
    _fake_mlflow(monkeypatch, model=_fitted_model())
    resp = client.post(f"/experiments/{experiment_id}/diagnostics")
    assert resp.status_code == 409
    assert "regression" in resp.json()["detail"].lower()


def test_diagnostics_when_mlflow_is_unreachable_is_503(client, monkeypatch) -> None:
    dataset_id = _upload(client)
    experiment_id = _experiment(client, dataset_id)

    def boom(ids):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(experiments_route.experiment_log, "fetch_runs", boom)
    resp = client.post(f"/experiments/{experiment_id}/diagnostics")
    assert resp.status_code == 503


def test_diagnostics_writes_no_finding_when_the_loop_fails(client, monkeypatch) -> None:
    dataset_id = _upload(client)
    experiment_id = _experiment(client, dataset_id)
    _fake_mlflow(monkeypatch, model=_fitted_model())

    def boom(datasets, dfs, prior_messages, question, *, client=None):
        raise RuntimeError("anthropic exploded")

    monkeypatch.setattr(experiments_route, "run_loop", boom)
    with pytest.raises(RuntimeError):
        client.post(f"/experiments/{experiment_id}/diagnostics")
    assert client.get("/findings").json() == []


def test_diagnostics_does_not_insert_the_derived_frames_as_datasets(client, monkeypatch) -> None:
    """D13: `datasets` is the single SOURCE-data path. A residual frame is not
    source data and must never appear there."""
    dataset_id = _upload(client)
    experiment_id = _experiment(client, dataset_id)
    _fake_mlflow(monkeypatch, model=_fitted_model())
    _fake_loop(monkeypatch)
    client.post(f"/experiments/{experiment_id}/diagnostics")
    assert len(client.get("/datasets").json()) == 1
```

- [x] **Step 2: Run to verify it fails**

Run: `poetry run pytest backend/tests/test_diagnostics_route.py -v`
Expected: FAIL — 405/404 on the new path.

- [x] **Step 3: Implement the route**

Append to `backend/app/routes/experiments.py`, adding the imports it needs (`from app import diagnostics, findings`, `from app.loop import run_loop`, `from app.profiler import profile_dataframe`, `from app.schemas import FindingCreatedOut`):

```python
DIAGNOSTICS_QUESTION = (
    "These two frames describe one trained model. `residuals` holds the model's holdout "
    "predictions with actual, predicted, residual and abs_error, plus the identifying "
    "columns. `learning_curve` holds train and validation score at increasing training "
    "sizes. Interpret the model's behaviour: where the errors concentrate, whether they "
    "drift over time, which groups are predicted worst, and whether the learning curve "
    "indicates underfitting, overfitting, or that more data would help. Be quantitative "
    "and say plainly if the model looks unusable."
)


def load_logged_model(model_uri: str) -> Any:
    """Seam for the MLflow model loader, so tests can stub it (D24).

    Loading the LOGGED model is the point: refitting from logged params yields a
    close-but-different model reported as the one that was scored, and nothing
    about that failure looks wrong.
    """
    import mlflow.sklearn

    return mlflow.sklearn.load_model(model_uri)


@router.post("/{experiment_id}/diagnostics", status_code=201, response_model=FindingCreatedOut)
def run_diagnostics(
    experiment_id: str, session: Session = Depends(get_session)
) -> FindingCreatedOut:
    """Generate a reviewable diagnostic interpretation for one run (2b.2)."""
    row = session.get(Experiment, experiment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    if row.task_type != "regression":
        raise HTTPException(
            status_code=409,
            detail="diagnostics are regression-only; residuals are undefined for a "
            f"{row.task_type} run",
        )
    if row.dataset_id is None:
        raise HTTPException(
            status_code=409, detail="this run has no dataset_id; its rows cannot be reloaded"
        )

    try:
        runs = experiment_log.fetch_runs([row.mlflow_run_id])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail="MLflow tracking store unavailable"
        ) from exc
    run = runs.get(row.mlflow_run_id)
    if run is None:
        raise HTTPException(
            status_code=409, detail=f"run {row.mlflow_run_id} is not in the tracking store"
        )
    if run.status != "FINISHED":
        raise HTTPException(
            status_code=409,
            detail=f"run {row.mlflow_run_id} is {run.status}; there is no logged model to load",
        )

    model_uri = f"runs:/{row.mlflow_run_id}/model"
    try:
        model = load_logged_model(model_uri)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=409,
            detail=f"no loadable model for run {row.mlflow_run_id} at {model_uri}: {exc}",
        ) from exc

    target = run.params.get("target_column", "")
    features = [f for f in run.params.get("feature_columns", "").split(",") if f]
    time_column = run.params.get("time_column") or None
    frame, _ = _load_training_frame(session, row.dataset_id)

    try:
        residuals = diagnostics.residual_frame(
            model, frame, target, features, time_column, id_columns=("ticker",)
        )
        curve = diagnostics.learning_curve_frame(model, frame, target, features, time_column)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=f"cannot diagnose this run: {exc}") from exc

    # Ephemeral ids: these frames go to the loop in memory and are NEVER
    # inserted into `datasets` — D13 makes that table the single source-data
    # path, and a derived diagnostic frame is not source data.
    derived = {f"residuals-{row.id}": residuals, f"learning_curve-{row.id}": curve}
    names = {f"residuals-{row.id}": "residuals", f"learning_curve-{row.id}": "learning_curve"}
    # Unwrapped, as on /chats and /datasets/{id}/eda (§6). create_finding is
    # below the loop, so a failure writes no partial finding.
    result = run_loop(
        [
            {"id": key, "name": names[key], "profile": profile_dataframe(df)}
            for key, df in derived.items()
        ],
        derived,
        [],
        DIAGNOSTICS_QUESTION,
    )

    finding = findings.create_finding(session, "diagnostic", row.id, result.interpretation)
    session.commit()
    session.refresh(finding)
    return FindingCreatedOut(
        finding_id=finding.id,
        source_type=finding.source_type,
        source_id=finding.source_id,
        status=finding.status,
        text=finding.text,
    )
```

- [x] **Step 4: Run to verify it passes**

Run: `poetry run pytest backend/tests/test_diagnostics_route.py -v`
Expected: PASS (8 tests).

- [x] **Step 5: Commit**

```bash
make check
git add backend/app/routes/experiments.py backend/tests/test_diagnostics_route.py
git commit -m "feat: POST /experiments/{id}/diagnostics — residuals and learning curves (2b.2, D24)"
```

---

## Task 9: `/review` — the bulk approval queue

**Files:**
- Modify: `frontend/src/api.ts` (append types + four functions)
- Create: `frontend/src/pages/ReviewPage.tsx`, `ReviewPage.module.css`, `ReviewPage.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `GET /findings`, `PATCH /findings/{id}` (Task 3), `GET /experiments?notes_status=draft`, `PATCH /experiments/{id}` (2a).
- Produces: the `/review` route. Task 10 uses it to approve the real content.

`ExperimentsPage`'s existing per-run dialog is **unchanged** — it remains the right surface for editing one note in the context of its run. `/review` is the right surface for working through a queue.

- [x] **Step 1: Write the failing tests**

Create `frontend/src/pages/ReviewPage.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ReviewPage from "./ReviewPage";

const finding = {
  id: "f1",
  source_type: "eda",
  source_id: "d1",
  text: "Revenue is right-skewed.",
  original_text: "Revenue is right-skewed.",
  status: "draft",
  created_at: "2026-08-14T00:00:00Z",
};

const note = {
  id: "e1",
  mlflow_run_id: "run-1",
  dataset_id: "d1",
  dataset_version: "h1",
  model_type: "ridge",
  task_type: "regression",
  notes: "Ridge beat the baseline.",
  notes_status: "draft",
  created_at: "2026-08-14T00:00:00Z",
  status: "FINISHED",
  params: { alpha: "1.0" },
  metrics: { rmse: 42.0 },
  mlflow_available: true,
};

function mockFetch(overrides: Record<string, unknown> = {}) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/findings") && (init?.method ?? "GET") === "GET") {
      return new Response(JSON.stringify([finding]), { status: 200 });
    }
    if (url.includes("/experiments") && (init?.method ?? "GET") === "GET") {
      return new Response(JSON.stringify([note]), { status: 200 });
    }
    if (init?.method === "PATCH") {
      const failing = overrides.failPatchFor as string | undefined;
      if (failing && url.includes(failing)) {
        return new Response(JSON.stringify({ detail: "nope" }), { status: 422 });
      }
      return new Response(JSON.stringify({ ...finding, status: "approved" }), { status: 200 });
    }
    return new Response("[]", { status: 200 });
  });
}

function renderPage() {
  return render(
    <MemoryRouter>
      <ReviewPage />
    </MemoryRouter>,
  );
}

describe("ReviewPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch());
  });

  it("lists drafts from both sources in one queue", async () => {
    renderPage();
    expect(await screen.findByText(/Revenue is right-skewed/)).toBeInTheDocument();
    expect(await screen.findByText(/Ridge beat the baseline/)).toBeInTheDocument();
  });

  it("labels each row with its content type", async () => {
    renderPage();
    expect(await screen.findByText("eda")).toBeInTheDocument();
    expect(await screen.findByText("note")).toBeInTheDocument();
  });

  it("disables the approve checkbox until the row has been opened", async () => {
    const user = userEvent.setup();
    renderPage();
    const checkbox = await screen.findByRole("checkbox", {
      name: /select .*Revenue is right-skewed/i,
    });
    expect(checkbox).toBeDisabled();

    await user.click(screen.getByRole("button", { name: /open .*Revenue is right-skewed/i }));
    await waitFor(() => expect(checkbox).toBeEnabled());
  });

  it("states how many selected rows still need opening", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/Revenue is right-skewed/);
    await user.click(screen.getByRole("button", { name: /open .*Revenue is right-skewed/i }));
    await user.click(
      screen.getByRole("checkbox", { name: /select .*Revenue is right-skewed/i }),
    );
    expect(screen.getByRole("button", { name: /approve 1 selected/i })).toBeInTheDocument();
    expect(screen.getByText(/1 more needs? opening/i)).toBeInTheDocument();
  });

  it("allows rejecting an unopened row", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/Revenue is right-skewed/);
    const reject = screen.getAllByRole("button", { name: /^reject$/i })[0];
    expect(reject).toBeEnabled();
    await user.click(reject);
    await waitFor(() => expect(fetch).toHaveBeenCalled());
  });

  it("shows a draft-vs-edit diff for a finding once edited", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/Revenue is right-skewed/);
    await user.click(screen.getByRole("button", { name: /open .*Revenue is right-skewed/i }));
    const textarea = await screen.findByRole("textbox", { name: /finding text/i });
    await user.clear(textarea);
    await user.type(textarea, "Revenue is left-skewed.");
    expect(screen.getByTestId("diff-original")).toHaveTextContent("Revenue is right-skewed.");
    expect(screen.getByTestId("diff-current")).toHaveTextContent("Revenue is left-skewed.");
  });

  it("reports partial failure honestly instead of claiming success", async () => {
    vi.stubGlobal("fetch", mockFetch({ failPatchFor: "/experiments/e1" }));
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/Revenue is right-skewed/);
    await user.click(screen.getByRole("button", { name: /open .*Revenue is right-skewed/i }));
    await user.click(screen.getByRole("button", { name: /open .*Ridge beat the baseline/i }));
    await user.click(screen.getByRole("checkbox", { name: /select .*Revenue is right-skewed/i }));
    await user.click(screen.getByRole("checkbox", { name: /select .*Ridge beat the baseline/i }));
    await user.click(screen.getByRole("button", { name: /approve 2 selected/i }));
    expect(await screen.findByText(/approved 1 of 2/i)).toBeInTheDocument();
    expect(await screen.findByText(/e1/)).toBeInTheDocument();
  });
});
```

- [x] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/pages/ReviewPage.test.tsx`
Expected: FAIL — `Failed to resolve import "./ReviewPage"`.

- [x] **Step 3: Add the API functions**

Append to `frontend/src/api.ts`:

```ts
export type Finding = {
  id: string;
  source_type: "eda" | "diagnostic";
  source_id: string;
  text: string;
  original_text: string;
  status: "draft" | "approved" | "rejected";
  created_at: string;
};

export type FindingCreated = {
  finding_id: string;
  source_type: string;
  source_id: string;
  status: string;
  text: string;
};

export async function listFindings(
  params: { status?: string; source_type?: string } = {},
): Promise<Finding[]> {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.source_type) query.set("source_type", params.source_type);
  const suffix = query.toString() ? `?${query}` : "";
  const res = await fetch(`${API_BASE}/findings${suffix}`);
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<Finding[]>;
}

export async function updateFinding(
  id: string,
  body: { text?: string; status?: string },
): Promise<Finding> {
  const res = await fetch(`${API_BASE}/findings/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<Finding>;
}

export async function runEda(datasetId: string): Promise<FindingCreated> {
  const res = await fetch(`${API_BASE}/datasets/${datasetId}/eda`, { method: "POST" });
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<FindingCreated>;
}

export async function runDiagnostics(experimentId: string): Promise<FindingCreated> {
  const res = await fetch(`${API_BASE}/experiments/${experimentId}/diagnostics`, {
    method: "POST",
  });
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<FindingCreated>;
}
```

`api.ts` has **no** shared request wrapper — each function does its own `fetch` and funnels failures through `failFrom(res)` (`frontend/src/api.ts:22`). The code above matches that pattern; do not introduce a wrapper as part of this task.

- [x] **Step 4: Write `ReviewPage.tsx`**

Create `frontend/src/pages/ReviewPage.tsx`. The shape that matters:

```tsx
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  type ExperimentRow,
  type Finding,
  listExperiments,
  listFindings,
  updateExperiment,
  updateFinding,
} from "../api";
import AppShell from "../components/AppShell";
import ErrorBanner from "../components/ErrorBanner";
import { Badge, Button, Textarea } from "../ui";
import styles from "./ReviewPage.module.css";

type Kind = "note" | "eda" | "diagnostic";

/** One queue over three content types (§5.1). Notes and findings live in
 *  different tables with different routes; normalising here keeps the queue a
 *  single list rather than three parallel ones. */
type Row = {
  kind: Kind;
  id: string;
  context: string;
  text: string;
  originalText: string | null; // null for notes — see the asymmetry below
};

function toRows(findings: Finding[], experiments: ExperimentRow[]): Row[] {
  return [
    ...findings.map((f) => ({
      kind: f.source_type as Kind,
      id: f.id,
      context: `${f.source_type} · ${f.source_id}`,
      text: f.text,
      originalText: f.original_text,
    })),
    ...experiments.map((e) => ({
      kind: "note" as const,
      id: e.id,
      context: `${e.model_type} · ${Object.entries(e.metrics)
        .map(([k, v]) => `${k}=${v}`)
        .join(" ")}`,
      text: e.notes,
      // Experiments have no `original_notes` column, so a note's diff is the
      // stored draft against the current textarea and is gone once saved.
      // Deliberate: adding a column to a table 2a just shipped is not worth the
      // symmetry (§5.3).
      originalText: null,
    })),
  ];
}

export default function ReviewPage() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [opened, setOpened] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [outcome, setOutcome] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [findings, experiments] = await Promise.all([
        listFindings({ status: "draft" }),
        listExperiments({ notes_status: "draft" }),
      ]);
      setRows(toRows(findings, experiments));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /** The opened-rows guard (§5.2, D26). Proves the text was RENDERED, not that
   *  anyone read it — it removes the accident (one select-all click approving 32
   *  unread drafts), not the intent. Stated plainly because Phase 4 treats
   *  approved rows as known-relevant ground truth, and a rubber-stamped batch
   *  corrupts that measurement silently. */
  const selectable = (row: Row) => opened.has(row.id);

  const needsOpening = useMemo(
    () => [...selected].filter((id) => !opened.has(id)).length,
    [selected, opened],
  );

  async function patch(row: Row, body: { text?: string; status?: string }) {
    if (row.kind === "note") {
      await updateExperiment(row.id, {
        notes: body.text,
        notes_status: body.status,
      });
    } else {
      await updateFinding(row.id, body);
    }
  }

  /** Issues N PATCHes and reports partial failure honestly rather than rolling
   *  back or claiming success (§5.4). */
  async function bulkApprove() {
    const targets = (rows ?? []).filter((r) => selected.has(r.id) && opened.has(r.id));
    const failures: string[] = [];
    for (const row of targets) {
      try {
        await patch(row, { text: edits[row.id] ?? row.text, status: "approved" });
      } catch {
        failures.push(row.id);
      }
    }
    setOutcome(
      failures.length === 0
        ? `Approved ${targets.length} of ${targets.length}.`
        : `Approved ${targets.length - failures.length} of ${targets.length}; ` +
          `${failures.join(", ")} failed.`,
    );
    setSelected(new Set());
    await load();
  }

  // ... render: AppShell wrapper, ErrorBanner, the bulk bar, and the row list.
}
```

Render requirements the tests pin down — implement each:

1. Each row renders a `Badge` whose text is the bare kind (`"eda"`, `"diagnostic"`, `"note"`).
2. Each row has a **button** with accessible name `Open — {first ~40 chars of text}` that toggles the row into `opened` and expands it.
3. Each row has a **checkbox** with accessible name `Select — {first ~40 chars of text}`, `disabled={!selectable(row)}`.
4. Each row has a **Reject** button, always enabled (rejecting unread text is coherent; approving it is not).
5. The bulk bar renders a button labelled `Approve {n} selected` and, when `needsOpening > 0`, the text `{needsOpening} more needs opening` (pluralise: `need` when > 1).
6. An expanded row renders a `Textarea` with accessible label `Finding text` (findings) / `Note text` (notes), bound to `edits[row.id] ?? row.text`.
7. When `row.originalText !== null` and the current text differs, render two elements: `data-testid="diff-original"` holding `originalText` and `data-testid="diff-current"` holding the current text. For notes (`originalText === null`), diff against `row.text` — the stored draft — and label it as ephemeral.
8. `outcome` renders as visible text.

Write `ReviewPage.module.css` with tokenized values from `frontend/src/styles/tokens.css` only — no hard-coded colours.

- [x] **Step 5: Register the route**

In `frontend/src/App.tsx`:

```tsx
import ReviewPage from "./pages/ReviewPage";
// ...
      <Route path="/review" element={<ReviewPage />} />
```

- [x] **Step 6: Run to verify it passes**

Run: `cd frontend && npx vitest run src/pages/ReviewPage.test.tsx`
Expected: PASS (8 tests).

- [x] **Step 7: Run the whole frontend gate and commit**

```bash
cd frontend && npm run type-check && npm test && npm run build && cd ..
git add frontend/src/api.ts frontend/src/App.tsx frontend/src/pages/ReviewPage.tsx \
        frontend/src/pages/ReviewPage.module.css frontend/src/pages/ReviewPage.test.tsx
git commit -m "feat: /review — bulk approval under the opened-rows guard, with a draft-vs-edit diff (2b.4, D26)"
```

---

## Task 10: Generate the real content, record the baseline, sync the docs

**Files:**
- Modify: `README.md`, `CLAUDE.md`
- Modify: `doc/plans/2026-08-05-project-2-overall-implementation-plan.md` (tick §3b)
- Modify: `doc/plans/2026-08-14-project-2-phase-2b-eda-diagnostics-design.md` (status line)

**Interfaces:**
- Consumes: every prior task.
- Produces: the approved rows Phase 3 embeds, and the exit criteria of §8.

This task needs the live stack: `make db-up`, `make mlflow-init` (once), `make dev`, `ANTHROPIC_API_KEY` set. It is the only task that spends tokens.

- [x] **Step 1: Bring the stack up and confirm the seeded history is present**

```bash
make db-up
make dev   # separate terminal
curl -s localhost:8000/experiments | python3 -c "import json,sys; print(len(json.load(sys.stdin)))"
```

Expected: 32 (the runs seeded in 2a Task 10). If 0, run `make data-fetch && make seed-history` first.

- [x] **Step 2: Fit the persistence baseline on the revenue panel**

```bash
DATASET_ID=$(curl -s localhost:8000/datasets | python3 -c \
  "import json,sys; print(next(d['id'] for d in json.load(sys.stdin) if 'revenue' in d['name']))")

curl -s -X POST localhost:8000/experiments/train \
  -H 'Content-Type: application/json' \
  -d "{\"dataset_id\":\"$DATASET_ID\",\"model_type\":\"persistence\",
       \"target_column\":\"revenue_next\",\"time_column\":\"quarter_end\",
       \"hyperparams\":{\"prior_column\":\"revenue\"}}"
```

Expected: `200` with `status: "FINISHED"` and an `rmse` in `metrics`. **Write that rmse down** — it is the number every tuned run is now measured against.

- [x] **Step 3: Confirm the baseline is on the leaderboard**

Open http://localhost:5173/experiments. The `persistence` run must appear in the table alongside the tuned models, sortable by `rmse`. Note whether anything beats it.

- [x] **Step 4: Generate the EDA finding**

```bash
curl -s -X POST "localhost:8000/datasets/$DATASET_ID/eda"
```

Expected: `201`, `status: "draft"`. Read the text — if it is generic or wrong, that is a finding about the loop, not something to paper over; note it in the write-up.

- [x] **Step 5: Generate a diagnostic for the best tuned run**

Pick the best-scoring tuned run id from `/experiments`, then:

```bash
curl -s -X POST "localhost:8000/experiments/$BEST_ID/diagnostics"
```

Expected: `201`, `status: "draft"`.

- [x] **Step 6: Review and approve through `/review`**

Open http://localhost:5173/review. Open each draft, read it, edit where the model overstated or got something wrong, and approve. Reject anything not worth retrieving.

**Exit criteria — verify each:**

```bash
curl -s "localhost:8000/findings?status=approved&source_type=eda"        # ≥ 1 row
curl -s "localhost:8000/findings?status=approved&source_type=diagnostic" # ≥ 1 row
```

- [x] **Step 7: Sync `CLAUDE.md`**

Add to **Code layout**: `app/findings.py`, `app/diagnostics.py`, `routes/findings.py`, `pages/ReviewPage.tsx`; update the `models.py` line to include `Finding` and the chunk table's new columns; add `error_by_group`/`line` to the `analysis.py`, `tools.py`, and `charts.py` lines; add the two new endpoints to the `routes/` lines.

Add to **Non-obvious design decisions**:

```markdown
**Findings are a separate table from experiment notes (D22).** EDA write-ups and
diagnostic interpretations live in `app.findings`, keyed by `(source_type, source_id)` —
`datasets.id` for `eda`, `experiments.id` for `diagnostic`. `source_id` carries **no
foreign key** because it addresses two tables; `app/findings.py` validates the reference
at write time instead. `original_text` is frozen at insert and never rewritten, which is
what keeps 2b.4's draft-vs-edit diff from losing its left-hand side the moment a reviewer
saves. `experiments.notes` was deliberately **not** folded in — migrating 32 live drafts
and breaking a route 2a just shipped is not worth the uniformity, and Phase 3 reads two
sources with a UNION.

**The persistence baseline is a registry entry, not a number in prose (D25).**
`MODEL_REGISTRY["persistence"]` fits `PriorValueRegressor`, whose `predict` returns
`X[prior_column]` unchanged, so the baseline is a real logged run — on the leaderboard, in
the compare table, retrievable by Phase 3. It requires `ModelSpec.preprocess = False`:
inside the standard `build_pipeline` the estimator would receive a **scaled** prior value
and could never emit raw dollars, so the baseline would be silently wrong rather than
fail. Its `search_space` is empty and `POST /experiments/tune` **422s** on it rather than
running N identical trials.

**Diagnostics loads the logged MLflow model; a missing artifact is a 409 (D24).**
`POST /experiments/{id}/diagnostics` calls `mlflow.sklearn.load_model` and never refits
from logged params — a close-but-different model reported as the one that was scored is
the worse failure, because nothing about it looks wrong. `app/diagnostics.py` re-derives
the holdout with `training.split_frame`, so residuals are computed on exactly the rows the
run was scored on. Both frames are handed to `run_loop` as in-memory datasets with
ephemeral ids and are **never** inserted into `datasets` — D13 makes that table the single
*source*-data path, and a derived frame is not source data.

**Bulk approval is gated on having opened the row (D26).** `/review` enables a row's
approve checkbox only after that row has been expanded in the current session; unopened
rows stay selectable for **reject**. This proves the text was rendered, not that anyone
read it — it removes the accident, not the intent. Stated explicitly because Phase 4's
eval harness treats approved rows as known-relevant ground truth, and a rubber-stamped
batch corrupts that measurement silently.
```

- [x] **Step 8: Sync `README.md`**

Document the two new endpoints, `GET`/`PATCH /findings`, the `/review` page, and the `persistence` model type in the feature list and any endpoint table.

- [x] **Step 9: Tick off the plan and close out the design doc**

In `doc/plans/2026-08-05-project-2-overall-implementation-plan.md` §3b, mark 2b.1–2b.4 complete and record the baseline result — **including if nothing beat it**. 224 rows with a ~30-row holdout is a small panel; if persistence wins, that is the finding, and the deliverable is a working experiment-tracking system, not a winning model.

In the design doc header, change `Status: approved 2026-08-14` to note the implementation landed.

- [x] **Step 10: Full CI gate and commit**

```bash
make check
cd frontend && npm run type-check && npm test && npm run build && cd ..
git add README.md CLAUDE.md doc/plans/
git commit -m "docs: sync docs with Phase 2b (Task 10)"
```

---

## Self-Review

**Spec coverage** — every section of the design maps to a task:

| Design § | Task |
|---|---|
| §3.1 `findings` table | 1 |
| §3.2 chunk migration (2b.3) | 2 |
| §4.1 `app/findings.py` | 1 |
| §4.2 `app/diagnostics.py` | 5 |
| §4.3 two analysis tools | 4 |
| §4.4 two generation endpoints | 7, 8 |
| §4.5 findings read/write API | 3 |
| §4.6 persistence baseline | 6 |
| §5.1–5.4 `/review` | 9 |
| §6 error handling | 7 (404, loop failure), 8 (404 / 409×4 / 503 / loop failure), 1+3 (422) |
| §7 testing | every task's test step |
| §8 exit criteria | 10 |
| §9 D22–D27 | D22→1, D23→7+8, D24→8, D25→6, D26→9, D27→4 |

**Deviations from the design, and why:**

1. **`residual_frame`/`learning_curve_frame` take `feature_columns`.** The design writes them as `(model, frame, target_column, time_column)`, but `training.prepare` requires the feature list. The route has it from MLflow's `feature_columns` param. Re-inferring it inside the module would risk diagnosing a different feature set than the run used — precisely the silent wrongness this module exists to prevent.
2. **`load_logged_model` is a module-level seam in `routes/experiments.py`.** The design does not name it; it exists so Task 8's tests can stub the MLflow loader without a tracking store, consistent with "everything runs on SQLite with no API key."
3. **Loop failure is left unwrapped.** The design says "the same mapping `/chats` uses" without naming a code. Checked: `routes/chats.py` does **not** wrap its `run_loop` call at all, so a loop failure propagates to FastAPI's default handler. Both new endpoints match that exactly rather than inventing a 502, and the "no partial finding" guarantee comes from statement ordering — `create_finding` sits below the loop call — not from an exception handler. The two tests assert `pytest.raises` plus an empty `/findings`.

**Known gaps, carried from the design:**

- The chunk migration executes only on Postgres (SQLite uses `create_all`), so its correctness is verified by `make migrate` against the dev Postgres (Task 2, Step 6), not by a test. Same limitation as every existing migration.
- The opened-rows guard proves rendering, not reading. Task 9 states this in a code comment and Task 10 restates it in `CLAUDE.md` rather than leaving it implied.
