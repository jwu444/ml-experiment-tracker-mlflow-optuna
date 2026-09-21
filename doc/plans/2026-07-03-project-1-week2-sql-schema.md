# Project 1 — Week 2 SQL Schema (`schema.sql`) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Source ticket:** `wavepoint-build/ai-engineering-workshop#11` (private repo) — "[P1 W2] schema.sql / queries.sql". **This plan covers Parts 1 & 2 only** (DDL + PK/FK/indexes). Part 3 (`queries.sql` progression) and the knowledge-base update are out of scope here.

**Goal:** Hand-author a Postgres `schema.sql` that models the full Project 1 analytics database — five tables with types, `NOT NULL`/`DEFAULT`/timestamp columns, primary keys, the ticket's one-to-many foreign-key chain, `ON DELETE` behavior, and indexes on FK columns. This is a Week 2 SQL-learning artifact and the intended foundation for the later FastAPI + SQLAlchemy integration; it is a **standalone raw-SQL file** and does **not** modify `backend/app/models.py`.

**Confirmed design decisions (from brainstorming):**
- **Primary keys:** `TEXT` columns holding UUID strings, `DEFAULT gen_random_uuid()::text` — faithful to the existing `String` + `_uuid` SQLAlchemy models, and self-sufficient for raw-SQL seeding.
- **`analyses.output_path`:** included but **nullable and unused for now** — reserved for a future chart-persistence feature. Honors the design-doc decision that charts are re-rendered from `data_csv` + `tool_calls`, not stored.
- **`chat_messages` re-parenting:** the new `chats` table sits between dataset and messages (`datasets → chats → chat_messages`). `chat_messages` carries `chat_id`, **not** `dataset_id` — the dataset is reached via `chats`. This diverges from today's `models.py` (where `chat_messages.dataset_id` → datasets directly); the divergence is intended and noted in the file header.
- **`cost_usd`:** modeled as `NUMERIC(10,6)` rather than the model's `Float` — money should not be floating point.

## Global Constraints

- Target: **PostgreSQL** (local `wavepoint` database — the existing local DB; ticket #10 names it `csv_assistant`, but this environment provisions it as `wavepoint`). `gen_random_uuid()` is built-in on Postgres 13+; no `pgcrypto` extension needed.
- **Namespace:** all objects live in a dedicated `app` schema (`CREATE SCHEMA` per Part 1). The file sets `search_path` so unqualified names resolve.
- Idempotent where practical: `CREATE SCHEMA IF NOT EXISTS`; tables use plain `CREATE TABLE` (a fresh build target).
- Every table: single-column PK, a `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, and explicit `NOT NULL` on required columns.
- JSON columns use `JSONB`.
- The required PR "schema design note" lives as a **comment header block** at the top of `schema.sql` (no separate design doc, given scope).

---

### Task 1: File scaffold, header note, schema namespace

**Files:**
- Create: `backend/db/schema.sql`

**Interfaces:**
- Consumes: a running local `wavepoint` Postgres database.
- Produces: `backend/db/schema.sql` — runnable end-to-end via `psql -d wavepoint -f backend/db/schema.sql`.

- [ ] **Step 1:** Write the header comment block: purpose, source ticket (#11), the four confirmed design decisions above, and the `ON DELETE` rationale (dataset id is the shareable root; deletes cascade down `dataset_columns`, `chats → chat_messages → analyses`).
- [ ] **Step 2:** `CREATE SCHEMA IF NOT EXISTS app;` then `SET search_path TO app;`.
- [ ] **Verify:** `psql -d wavepoint -f backend/db/schema.sql` runs clean so far (schema created).

### Task 2: `datasets` and `dataset_columns`

**Files:**
- Modify: `backend/db/schema.sql`

- [ ] **Step 1: `datasets`** — mirrors the existing model:
  - `id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text`
  - `name TEXT NOT NULL`
  - `n_rows INTEGER NOT NULL CHECK (n_rows >= 0)`
  - `n_cols INTEGER NOT NULL CHECK (n_cols >= 0)`
  - `profile_json JSONB NOT NULL`
  - `data_csv TEXT NOT NULL`
  - `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- [ ] **Step 2: `dataset_columns`** — per-column metadata:
  - `id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text`
  - `dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE`
  - `name TEXT NOT NULL`
  - `ordinal_position INTEGER NOT NULL CHECK (ordinal_position >= 0)`
  - `inferred_type TEXT NOT NULL`
  - `null_count INTEGER NOT NULL DEFAULT 0 CHECK (null_count >= 0)`
  - `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
  - `UNIQUE (dataset_id, name)` — a dataset cannot have two columns with the same name.
- [ ] **Verify:** file re-runs clean on a fresh database; both tables present via `\dt app.*`.

### Task 3: `chats` and `chat_messages`

**Files:**
- Modify: `backend/db/schema.sql`

- [ ] **Step 1: `chats`** — session tied to a dataset:
  - `id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text`
  - `dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE`
  - `title TEXT` (nullable)
  - `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- [ ] **Step 2: `chat_messages`** — re-parented under `chats`:
  - `id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text`
  - `chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE`
  - `role TEXT NOT NULL CHECK (role IN ('user','assistant','system','tool'))`
  - `content TEXT NOT NULL DEFAULT ''`
  - `tool_calls JSONB NOT NULL DEFAULT '[]'::jsonb`
  - `tokens_in INTEGER NOT NULL DEFAULT 0`
  - `tokens_out INTEGER NOT NULL DEFAULT 0`
  - `cost_usd NUMERIC(10,6) NOT NULL DEFAULT 0`
  - `latency_ms INTEGER NOT NULL DEFAULT 0`
  - `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- [ ] **Verify:** file re-runs clean; FK from `chat_messages.chat_id` → `chats.id` present.

### Task 4: `analyses`

**Files:**
- Modify: `backend/db/schema.sql`

- [ ] **Step 1: `analyses`** — result tied to a message (ticket FK chain `chat_messages → analyses`):
  - `id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text`
  - `message_id TEXT NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE`
  - `chart_type TEXT NOT NULL`
  - `params JSONB NOT NULL DEFAULT '{}'::jsonb`
  - `result_stats JSONB` (nullable)
  - `output_path TEXT` — nullable, **reserved for future chart-persistence; unused now** (inline comment)
  - `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- [ ] **Verify:** file re-runs clean; all five tables present.

### Task 5: Indexes (Part 2 — FK indexes + ordered-read support)

**Files:**
- Modify: `backend/db/schema.sql`

- [ ] **Step 1:** Index every FK column (Postgres does not auto-index FKs):
  - `idx_dataset_columns_dataset_id` on `dataset_columns(dataset_id)`
  - `idx_chats_dataset_id` on `chats(dataset_id)`
  - `idx_chat_messages_chat_id` on `chat_messages(chat_id)`
  - `idx_analyses_message_id` on `analyses(message_id)`
- [ ] **Step 2:** Composite indexes to support ordered-history reads used later by `queries.sql`:
  - `idx_chat_messages_chat_created` on `chat_messages(chat_id, created_at)`
  - `idx_chats_dataset_created` on `chats(dataset_id, created_at)`
- [ ] **Verify:** `\di app.*` lists all six indexes.

### Task 6: Full-file validation

**Files:**
- None (validation only).

- [ ] **Step 1:** Drop and recreate a scratch database (or `DROP SCHEMA app CASCADE`), then run `psql -d wavepoint -f backend/db/schema.sql` top-to-bottom — must complete with zero errors.
- [ ] **Step 2:** Sanity-check the FK chain with a manual insert + `DELETE FROM datasets` and confirm cascade removes rows from all descendant tables.
- [ ] **Step 3:** Confirm the header note satisfies the ticket's "short note explaining schema design choices" acceptance criterion (table shapes, FK decisions, `ON DELETE` rationale).

---

## Out of scope (tracked for a follow-up plan)

- **Part 3 — `queries.sql`:** simple / join / aggregation / advanced (CTE + window) query progression + seed data.
- **Knowledge-base update** (`wavepoint-build/knowledge-base`, private repo).
- **SQLAlchemy alignment:** reconciling `models.py` (currently `chat_messages.dataset_id` → datasets, `cost_usd` Float, no `chats`/`dataset_columns`/`analyses`) with this schema — belongs to the FastAPI integration milestone, not this SQL exercise.
