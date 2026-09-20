# Idempotent Dataset Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `POST /datasets` idempotent on file content — re-uploading identical bytes returns the existing dataset (HTTP 200) instead of creating a duplicate.

**Architecture:** SHA-256 over the raw upload bytes becomes a dataset's identity. The route computes the hash, checks `datasets.content_hash` before inserting, and returns the existing record on a hit. A new `content_hash VARCHAR(64) UNIQUE NOT NULL` column plus an Alembic migration back the constraint. Backend-only; `DatasetOut` and the frontend are unchanged.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, pytest (SQLite), Postgres (prod).

**Design doc:** `doc/project-1-idempotent-upload-design.md` (approved).

## Global Constraints

- Python **3.12**; line length **100** (ruff + black); mypy **strict** on `backend/app`.
- Tests run on **SQLite** (per-test isolated DB via the `client` fixture / `_session` helper). Migrations run on **Postgres** only — `init_db()` uses `create_all` for SQLite, so the test suite never executes Alembic.
- **D5:** raw CSV stays in Postgres; no object store. Hash is derived, not a new copy.
- Hash is computed over **raw bytes before `decode_csv`** (encoding/BOM-insensitive identity).
- `content_hash` is **internal** — do not add it to `DatasetOut`.
- Alembic-generated migration files under `backend/alembic/versions/` are excluded from ruff/black; do not hand-format them to the line limit.
- **Mid-plan red is expected:** Task 2 makes `content_hash` NOT NULL, which breaks the upload route (fixed in Task 4). Run only the *scoped* test command each task names; the full `make check` gate runs in Task 5.

---

### Task 1: `hash_csv` helper

**Files:**
- Modify: `backend/app/dataset_io.py`
- Test: `backend/tests/test_dataset_io.py`

**Interfaces:**
- Produces: `hash_csv(raw: bytes) -> str` — 64-char lowercase hex SHA-256 digest.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_dataset_io.py`:

```python
from app.dataset_io import hash_csv


def test_hash_csv_is_deterministic_64_hex():
    raw = b"a,b\n1,2\n"
    digest = hash_csv(raw)
    assert digest == hash_csv(raw)
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_hash_csv_distinguishes_content():
    assert hash_csv(b"a,b\n1,2\n") != hash_csv(b"a,b\n1,3\n")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest backend/tests/test_dataset_io.py -v`
Expected: FAIL with `ImportError: cannot import name 'hash_csv'`.

- [ ] **Step 3: Implement `hash_csv`**

In `backend/app/dataset_io.py`, add `import hashlib` at the top and the function:

```python
def hash_csv(raw: bytes) -> str:
    """SHA-256 of the raw upload bytes, as 64-char lowercase hex."""
    return hashlib.sha256(raw).hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest backend/tests/test_dataset_io.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/dataset_io.py backend/tests/test_dataset_io.py
git commit -m "feat(datasets): add hash_csv SHA-256 helper (issue #7)"
```

---

### Task 2: `content_hash` column + unique constraint

**Files:**
- Modify: `backend/app/models.py` (the `Dataset` class)
- Modify: `backend/tests/test_models.py` (two existing `Dataset(...)` constructions + new constraint test)

**Interfaces:**
- Produces: `Dataset.content_hash: Mapped[str]` (String(64), NOT NULL) with unique constraint `uq_datasets_content_hash`.
- Consumes: `hash_csv` from Task 1 (used in tests to build valid hashes).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_models.py`:

```python
import pytest
from sqlalchemy.exc import IntegrityError


def test_content_hash_unique_constraint(tmp_path):
    session = _session(tmp_path)
    session.add(Dataset(name="a.csv", n_rows=1, n_cols=1, profile_json={},
                        data_csv="x\n1\n", content_hash="h" * 64))
    session.commit()
    session.add(Dataset(name="b.csv", n_rows=1, n_cols=1, profile_json={},
                        data_csv="y\n2\n", content_hash="h" * 64))
    with pytest.raises(IntegrityError):
        session.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest backend/tests/test_models.py::test_content_hash_unique_constraint -v`
Expected: FAIL — `TypeError: 'content_hash' is an invalid keyword argument for Dataset` (column not defined yet).

- [ ] **Step 3: Add the column and constraint to the model**

In `backend/app/models.py`, change the `Dataset` class `__table_args__` and add the column. `UniqueConstraint` is already imported.

```python
class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        UniqueConstraint("content_hash", name="uq_datasets_content_hash"),
        {"schema": "app"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    n_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    n_cols: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    data_csv: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

- [ ] **Step 4: Fix the two existing `Dataset(...)` constructions in `test_models.py`**

`content_hash` is now NOT NULL, so both direct constructions must supply it. Any distinct 64-char string works as a test hash.

At `test_dataset_persists_profile_and_csv` (was line ~17), add `content_hash`:

```python
    dataset = Dataset(
        name="sales.csv",
        n_rows=3,
        n_cols=2,
        profile_json={"n_rows": 3, "columns": ["a", "b"]},
        data_csv="a,b\n1,2\n3,4\n5,6\n",
        content_hash="a" * 64,
    )
```

At `test_chat_message_defaults` (was line ~35):

```python
    dataset = Dataset(name="d.csv", n_rows=1, n_cols=1, profile_json={},
                      data_csv="x\n1\n", content_hash="b" * 64)
```

- [ ] **Step 5: Run the model tests to verify they pass**

Run: `poetry run pytest backend/tests/test_models.py -v`
Expected: PASS (all, including the new constraint test).

- [ ] **Step 6: Commit**

```bash
git add backend/app/models.py backend/tests/test_models.py
git commit -m "feat(datasets): add content_hash column + unique constraint (issue #7)"
```

---

### Task 3: Alembic migration

**Files:**
- Create: `backend/alembic/versions/<revision>_add_datasets_content_hash.py` (revision id auto-assigned)

**Interfaces:**
- Consumes: initial migration `f280d48505b3` (auto-set as `down_revision`).
- Produces: `datasets.content_hash` column + `uq_datasets_content_hash` on Postgres.

> Requires a running Postgres reachable via `DATABASE_URL` (the dev DB, already at head `f280d48505b3`). This task does **not** touch the pytest suite.

- [ ] **Step 1: Scaffold an empty revision**

Run: `poetry run alembic revision -m "add datasets.content_hash"`
(No `--autogenerate` — we hand-write the three-step data migration.) This creates a file under `backend/alembic/versions/` with `down_revision = "f280d48505b3"` already filled in.

- [ ] **Step 2: Write the migration body**

Replace the generated `upgrade()`/`downgrade()` and add the imports (`import hashlib` and ensure `import sqlalchemy as sa`):

```python
import hashlib

import sqlalchemy as sa
from alembic import op


def upgrade() -> None:
    # 1. Add the column nullable so existing rows don't violate NOT NULL yet.
    op.add_column(
        "datasets",
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        schema="app",
    )
    # 2. Backfill from the stored CSV text. Best-effort: the original raw bytes
    #    are gone, so this hashes the decoded text — see the design doc caveat.
    #    No-op on an empty table.
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, data_csv FROM app.datasets")).fetchall()
    for row in rows:
        digest = hashlib.sha256(row.data_csv.encode("utf-8")).hexdigest()
        bind.execute(
            sa.text("UPDATE app.datasets SET content_hash = :h WHERE id = :id"),
            {"h": digest, "id": row.id},
        )
    # 3. Enforce NOT NULL now that every row has a value.
    op.alter_column(
        "datasets", "content_hash",
        existing_type=sa.String(length=64), nullable=False, schema="app",
    )
    # 4. Uniqueness (its backing index also serves dedup lookups).
    op.create_unique_constraint(
        "uq_datasets_content_hash", "datasets", ["content_hash"], schema="app"
    )


def downgrade() -> None:
    op.drop_constraint("uq_datasets_content_hash", "datasets", schema="app", type_="unique")
    op.drop_column("datasets", "content_hash", schema="app")
```

- [ ] **Step 3: Apply the migration**

Run: `make migrate`
Expected: `Running upgrade f280d48505b3 -> <revision>`.

- [ ] **Step 4: Verify no drift against the model**

Run: `poetry run alembic check`
Expected: `No new upgrade operations detected.`

- [ ] **Step 5: Verify downgrade is clean, then re-upgrade**

```bash
poetry run alembic downgrade -1   # drops constraint + column
poetry run alembic upgrade head   # back to head
poetry run alembic check          # No new upgrade operations detected.
```

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/
git commit -m "feat(db): migration for datasets.content_hash (issue #7)"
```

---

### Task 4: Dedup logic in the upload route

**Files:**
- Modify: `backend/app/routes/datasets.py`
- Test: `backend/tests/test_datasets.py`

**Interfaces:**
- Consumes: `hash_csv` (Task 1), `Dataset.content_hash` (Task 2).

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_datasets.py`:

```python
def test_duplicate_upload_returns_same_id(client):
    files = {"file": ("sales.csv", io.BytesIO(_csv_bytes()), "text/csv")}
    first = client.post("/datasets", files=files)
    assert first.status_code == 200
    files = {"file": ("sales.csv", io.BytesIO(_csv_bytes()), "text/csv")}
    second = client.post("/datasets", files=files)
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]


def test_same_filename_different_content_distinct_ids(client):
    a = client.post("/datasets", files={"file": ("d.csv", io.BytesIO(b"a\n1\n"), "text/csv")})
    b = client.post("/datasets", files={"file": ("d.csv", io.BytesIO(b"a\n2\n"), "text/csv")})
    assert a.json()["id"] != b.json()["id"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest backend/tests/test_datasets.py -v`
Expected: FAIL — the route still inserts a duplicate (distinct ids), and inserts without `content_hash` raise `IntegrityError` (NOT NULL) after Task 2.

- [ ] **Step 3: Implement the dedup route**

Rewrite `upload_dataset` in `backend/app/routes/datasets.py`. Add imports at the top: `from sqlalchemy import select` and `from sqlalchemy.exc import IntegrityError`, plus `hash_csv` to the existing `app.dataset_io` import.

```python
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.dataset_io import decode_csv, hash_csv, load_csv
from app.db import get_session
from app.models import Dataset, DatasetColumn
from app.profiler import profile_dataframe
from app.schemas import DatasetOut

router = APIRouter(prefix="/datasets", tags=["datasets"])


def _find_by_hash(session: Session, content_hash: str) -> Dataset | None:
    return session.execute(
        select(Dataset).where(Dataset.content_hash == content_hash)
    ).scalar_one_or_none()


@router.post("", response_model=DatasetOut)
def upload_dataset(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> Dataset:
    raw = file.file.read()
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="File exceeds size limit")
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are accepted")

    content_hash = hash_csv(raw)
    existing = _find_by_hash(session, content_hash)
    if existing is not None:
        return existing  # idempotent: same content -> same record (200)

    try:
        data_csv = decode_csv(raw)
        df = load_csv(data_csv)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {exc}") from exc
    if df.empty:
        raise HTTPException(status_code=400, detail="CSV has no rows")
    if len(df) > settings.max_rows:
        raise HTTPException(status_code=413, detail="CSV exceeds row limit")

    dataset = Dataset(
        name=file.filename or "dataset.csv",
        n_rows=int(len(df)),
        n_cols=int(df.shape[1]),
        profile_json=profile_dataframe(
            df,
            sample_rows=settings.profile_sample_rows,
            max_cardinality=settings.profile_max_cardinality,
            max_corr_cols=settings.profile_max_corr_cols,
            top_corr_pairs=settings.profile_top_corr_pairs,
            token_budget=settings.profile_token_budget,
        ),
        data_csv=data_csv,
        content_hash=content_hash,
    )
    session.add(dataset)
    session.flush()
    for ordinal_position, col in enumerate(dataset.profile_json["columns"]):
        session.add(
            DatasetColumn(
                dataset_id=dataset.id,
                name=col["name"],
                ordinal_position=ordinal_position,
                inferred_type=col["dtype"],
                null_count=col["n_null"],
            )
        )
    try:
        session.commit()
    except IntegrityError:
        # A concurrent upload won the race on the unique hash — return the winner.
        session.rollback()
        winner = _find_by_hash(session, content_hash)
        if winner is None:
            raise
        return winner
    session.refresh(dataset)
    return dataset
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest backend/tests/test_datasets.py -v`
Expected: PASS (existing upload tests + the two new dedup tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/datasets.py backend/tests/test_datasets.py
git commit -m "feat(datasets): dedup uploads by content hash (issue #7)"
```

---

### Task 5: Full gate + doc sync

**Files:**
- Modify: `README.md`, `CLAUDE.md`
- Verify: `doc/project-1-idempotent-upload-design.md` (acceptance boxes), this plan (checkboxes)

- [ ] **Step 1: Run the full CI gate**

Run: `make check`
Expected: ruff, black --check, mypy strict, and **all** pytest green (the mid-plan red from Task 2 is resolved once Task 4 landed).

- [ ] **Step 2: Confirm no frontend change is needed**

The dedup path returns a normal `DatasetOut` with 200; `frontend/src/pages/UploadPage.tsx` already consumes only `dataset.id`. No frontend edit. (Sanity check, no code change: `cd frontend && npm test` still green.)

- [ ] **Step 3: Update README**

In `README.md`, add a one-line note to the upload/feature description: uploading an identical CSV returns the existing dataset (deduplicated by SHA-256 content hash) rather than creating a duplicate.

- [ ] **Step 4: Update CLAUDE.md**

Add a non-obvious design-decision bullet under the existing list:

> **Idempotent upload (issue #7).** `POST /datasets` deduplicates by a SHA-256 hash of the raw upload bytes, stored in `datasets.content_hash` (`VARCHAR(64)`, unique). A re-upload of identical content returns the existing record with 200; `content_hash` is internal and not exposed in `DatasetOut`. Backfill for pre-existing rows hashes the stored decoded CSV (best-effort — original raw bytes are not retained).

Also update the `datasets.py` and `dataset_io.py` one-line descriptions in the code-layout block to mention dedup / `hash_csv`.

- [ ] **Step 5: Tick the design-doc acceptance criteria and this plan's checkboxes**

Confirm the four acceptance boxes in `doc/project-1-idempotent-upload-design.md` §6 are checked.

- [ ] **Step 6: Commit**

```bash
git add README.md CLAUDE.md doc/project-1-idempotent-upload-design.md doc/plans/2026-07-26-project-1-idempotent-upload.md
git commit -m "docs: sync README/CLAUDE for idempotent upload (issue #7)"
```

---

## Self-Review

**Spec coverage:** SHA-256 over raw bytes (Task 1) ✓; dedup returning existing with 200 (Task 4) ✓; `content_hash VARCHAR(64) UNIQUE NOT NULL` (Task 2) ✓; migration with backfill (Task 3) ✓; content-based not name-based (Task 4 test `test_same_filename_different_content_distinct_ids`) ✓; existing tests updated (Task 2 fixups, Task 4) ✓; concurrency (Task 4 `IntegrityError` fallback) ✓.

**Placeholder scan:** none — every code and test step is full.

**Type consistency:** `hash_csv(raw: bytes) -> str` used identically in Tasks 1/4; `content_hash` is `String(64)`/`VARCHAR(64)` everywhere; constraint name `uq_datasets_content_hash` matches across model (Task 2) and migration (Task 3); `down_revision = "f280d48505b3"` matches the existing initial revision.
