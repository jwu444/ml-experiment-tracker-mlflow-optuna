# Project 1 — Idempotent Dataset Upload (issue #7)

**Status:** approved — 2026-07-26
**Issue:** #7 — *Enhancement: idempotent dataset upload (deduplicate by content hash)*
**Scope:** backend only (no frontend change)

## 1. Problem

Re-uploading an identical CSV (during testing, or after a page refresh) creates
duplicate rows in `app.datasets` — wasting storage and polluting the dataset
list. Uploads should be **idempotent on file content**: the same bytes always map
to the same dataset record.

## 2. Contract

`POST /datasets` deduplicates by content:

- Compute a SHA-256 hash of the **raw uploaded bytes** (before decoding).
- If a dataset with that hash already exists, return the **existing** record with
  **HTTP 200** — identical to a fresh upload from the caller's point of view.
- Otherwise create the dataset as today, persisting the hash.

`content_hash` is **internal**. It is *not* added to `DatasetOut`; the API
response shape is unchanged (`id`, `name`, `n_rows`, `n_cols`).

**Frontend impact: none.** `UploadPage` already consumes only the returned `id`,
so a 200-with-existing-record is transparent to it.

Deduplication is **content-based, not name-based**: two different files with the
same filename remain separate datasets; two byte-identical files with different
filenames collapse to one (the first-uploaded record, with its original name).

## 3. Components

### 3.1 Hashing helper — `app/dataset_io.py`

```python
import hashlib

def hash_csv(raw: bytes) -> str:
    """SHA-256 of the raw upload bytes, as 64-char lowercase hex."""
    return hashlib.sha256(raw).hexdigest()
```

Hashing the **raw bytes before `decode_csv`** means encoding/BOM differences do
not affect identity — the hash is over exactly what was uploaded.

### 3.2 Schema — `app/models.py`

Add a column and a named unique constraint to `Dataset`, matching the codebase
style (`dataset_columns` / `chat_datasets` declare their `UniqueConstraint` in
`__table_args__`):

```python
class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        UniqueConstraint("content_hash", name="uq_datasets_content_hash"),
        {"schema": "app"},
    )
    ...
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
```

The unique constraint is backed by an index on Postgres, which also serves the
dedup lookup — so no separate `index=True` is needed (it would be redundant).

### 3.3 Migration — new Alembic revision

Adding a `NOT NULL UNIQUE` column to a possibly-populated table is a three-step
data migration (Postgres):

1. `add_column("content_hash", String(64), nullable=True)` on schema `app`.
2. **Backfill** existing rows: for each row, `content_hash = sha256(data_csv.encode("utf-8"))`.
3. `alter_column(..., nullable=False)`.
4. `create_unique_constraint("uq_datasets_content_hash", "datasets", ["content_hash"], schema="app")`
   (its backing index also serves dedup lookups — no separate index).

`downgrade` drops the constraint then the column.

**Backfill caveat:** pre-existing rows no longer have their original raw bytes,
so the backfill hashes the stored *decoded* text (`data_csv`). This can differ
from a hash of the original raw bytes if the upload had a non-UTF-8 encoding or a
BOM. This is an accepted, documented limitation; going forward all hashes are
computed over raw bytes. In the current dev database (rebuilt empty during the
issue-#7-adjacent Alembic work) there are no rows to backfill, so this step is a
no-op there.

SQLite (tests) does not run migrations — `init_db()` builds tables from ORM
metadata via `create_all`, which already includes the new column.

### 3.4 Route — `app/routes/datasets.py`

New ordering inside `upload_dataset`:

1. Read `raw`; size check (`413`); `.csv` extension check (`400`).
2. `content_hash = hash_csv(raw)`.
3. **Dedup query:** `select(Dataset).where(Dataset.content_hash == content_hash)`.
   On a hit, return the existing `Dataset` immediately (200) — this also
   short-circuits re-parsing/profiling of already-known content.
4. On a miss: `decode_csv` → `load_csv` → empty/row-limit checks → `profile_dataframe`
   → construct `Dataset(..., content_hash=content_hash)` → insert columns → commit.

## 4. Error handling — concurrent duplicates

Two identical uploads racing can both pass the step-3 pre-check before either
commits; one insert then violates `uq_datasets_content_hash`. Handle it:

```python
try:
    session.commit()
except IntegrityError:
    session.rollback()
    existing = session.execute(
        select(Dataset).where(Dataset.content_hash == content_hash)
    ).scalar_one()
    return existing
```

The rollback discards the half-inserted `Dataset` and its `DatasetColumn` rows;
the caller still gets the winning record with 200. Cheap correctness insurance
that makes the endpoint safe under concurrency, not just sequential re-uploads.

## 5. Testing

- **`hash_csv`** (`test_dataset_io.py`): deterministic; 64-char hex; distinct
  bytes → distinct hash; identical bytes → identical hash.
- **Route** (`test_datasets.py`):
  - Upload the same CSV twice → same `id` both times, HTTP 200 both times, and
    exactly one row in `datasets`.
  - Same filename, different content → two distinct `id`s.
- **Model** (`test_models.py`): the unique constraint rejects a second row with a
  duplicate `content_hash`.
- **Existing-test fixups:** any test that constructs `Dataset(...)` directly or
  uploads a fixture must now supply a `content_hash` (the column is NOT NULL).
  These updates are part of the plan, per the issue's acceptance criteria.
- **Migration:** verified out-of-band with `alembic upgrade head` + `alembic check`
  against a scratch Postgres DB (not a pytest — the suite runs on SQLite).

## 6. Acceptance criteria (from issue #7)

- [x] Uploading the same CSV twice returns the same dataset `id` both times.
- [x] No duplicate rows in `app.datasets` for identical file content.
- [x] Different files with the same filename are still stored separately.
- [x] Existing tests updated to cover the deduplication path.

## 7. Out of scope

Near-duplicate detection (same columns, different row count) — explicitly
deferred by the issue.
