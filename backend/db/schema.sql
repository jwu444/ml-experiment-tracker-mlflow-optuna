-- =============================================================================
-- Project 1 — CSV Analysis Assistant — analytics database schema
-- Source ticket: wavepoint-build/ai-engineering-workshop#11  ([P1 W2] schema.sql)
-- Target: PostgreSQL 13+ (gen_random_uuid() is built-in; no pgcrypto needed).
-- Run:    psql -d wavepoint -f backend/db/schema.sql
--
-- This is a Week-2 SQL-learning artifact and the intended foundation for the
-- later FastAPI + SQLAlchemy integration. It is a standalone raw-SQL file and
-- does NOT modify backend/app/models.py.
--
-- Schema design note (Part 1 & 2)
-- -------------------------------
-- * Primary keys are TEXT holding UUID strings, DEFAULT gen_random_uuid()::text.
--   This matches the existing String + uuid4 SQLAlchemy models and lets raw SQL
--   seed rows without application code.
-- * The five tables form one dependency chain rooted at a dataset:
--       datasets ─┬─< dataset_columns
--                 └─< chats ─< chat_messages ─< analyses
--   A `chats` table sits BETWEEN dataset and messages. chat_messages therefore
--   carries chat_id (NOT dataset_id) — the dataset is reached via chats. This
--   intentionally diverges from today's models.py, where chat_messages links to
--   datasets directly; the FastAPI integration will reconcile that.
-- * ON DELETE CASCADE throughout: a dataset id is the app's shareable root, so
--   deleting a dataset sweeps its columns, chats, messages, and analyses. Each
--   FK cascades to its immediate children, so a delete at any level cleans up
--   everything beneath it.
-- * analyses.output_path is nullable and UNUSED for now — reserved for a future
--   chart-persistence feature. Charts are currently re-rendered from
--   datasets.data_csv + chat_messages.tool_calls, never stored (design §D5).
-- * cost_usd is NUMERIC(10,6), not float — money should not be floating point.
-- * Postgres does not auto-index FK columns, so every FK column is indexed,
--   plus two composite indexes that support ordered-history reads.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS app;
SET search_path TO app;

-- -----------------------------------------------------------------------------
-- datasets — one row per uploaded CSV (mirrors the existing Dataset model).
-- -----------------------------------------------------------------------------
CREATE TABLE datasets (
    id          TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
    name        TEXT        NOT NULL,
    n_rows      INTEGER     NOT NULL CHECK (n_rows >= 0),
    n_cols      INTEGER     NOT NULL CHECK (n_cols >= 0),
    profile_json JSONB      NOT NULL,
    data_csv    TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- dataset_columns — per-column metadata for a dataset.
-- -----------------------------------------------------------------------------
CREATE TABLE dataset_columns (
    id               TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
    dataset_id       TEXT        NOT NULL REFERENCES datasets (id) ON DELETE CASCADE,
    name             TEXT        NOT NULL,
    ordinal_position INTEGER     NOT NULL CHECK (ordinal_position >= 0),
    inferred_type    TEXT        NOT NULL,
    null_count       INTEGER     NOT NULL DEFAULT 0 CHECK (null_count >= 0),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- A dataset cannot have two columns with the same name.
    UNIQUE (dataset_id, name)
);

-- -----------------------------------------------------------------------------
-- chats — a chat session tied to a dataset.
-- -----------------------------------------------------------------------------
CREATE TABLE chats (
    id         TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
    dataset_id TEXT        NOT NULL REFERENCES datasets (id) ON DELETE CASCADE,
    title      TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- chat_messages — individual turns in a chat. Re-parented under chats: reach
-- the dataset via chats.dataset_id, not a direct FK here.
-- -----------------------------------------------------------------------------
CREATE TABLE chat_messages (
    id         TEXT          PRIMARY KEY DEFAULT gen_random_uuid()::text,
    chat_id    TEXT          NOT NULL REFERENCES chats (id) ON DELETE CASCADE,
    role       TEXT          NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    content    TEXT          NOT NULL DEFAULT '',
    tool_calls JSONB         NOT NULL DEFAULT '[]'::jsonb,
    tokens_in  INTEGER       NOT NULL DEFAULT 0,
    tokens_out INTEGER       NOT NULL DEFAULT 0,
    cost_usd   NUMERIC(10,6) NOT NULL DEFAULT 0,
    latency_ms INTEGER       NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ   NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- analyses — a generated chart/stat result tied to a chat message.
-- (FK chain per ticket: chat_messages -> analyses.)
-- -----------------------------------------------------------------------------
CREATE TABLE analyses (
    id           TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
    message_id   TEXT        NOT NULL REFERENCES chat_messages (id) ON DELETE CASCADE,
    chart_type   TEXT        NOT NULL,
    params       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    result_stats JSONB,
    -- Reserved for a future chart-persistence feature; UNUSED for now.
    -- Charts are re-rendered from data_csv + tool_calls, not stored.
    output_path  TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- Indexes — every FK column (Postgres does not auto-index FKs), plus two
-- composites that back ordered-history reads used by queries.sql.
-- -----------------------------------------------------------------------------
CREATE INDEX idx_dataset_columns_dataset_id ON dataset_columns (dataset_id);
CREATE INDEX idx_chats_dataset_id           ON chats (dataset_id);
CREATE INDEX idx_chat_messages_chat_id      ON chat_messages (chat_id);
CREATE INDEX idx_analyses_message_id        ON analyses (message_id);

CREATE INDEX idx_chat_messages_chat_created ON chat_messages (chat_id, created_at);
CREATE INDEX idx_chats_dataset_created      ON chats (dataset_id, created_at);
