# Project 1: Multi-Dataset Chat (Issue #6)

Status: **Approved**, pending implementation plan.
Related: `doc/project-1-csv-analysis-assistant-design.md` (base architecture, D1–D6).

## 1. Problem

A chat is currently scoped to exactly one dataset (`chats.dataset_id`). Issue #6 asks
for uploading multiple datasets and running analysis that spans them — comparisons,
lightweight joins, combined insights — within a single chat session.

## 2. Scope

**In scope:**
- A chat can be created over N previously-uploaded datasets (no hard cap; bounded by
  the profiler token budget, not an arbitrary count).
- Existing per-dataset tools (`histogram`, `scatter`, `correlation_matrix`) gain a
  `dataset_id` argument so Claude can target any one of the chat's datasets.
- A new `compare` tool does a lightweight, in-memory, key-based inner join across
  **exactly two** of the chat's datasets and renders a grouped bar chart of an
  aggregated metric.
- Frontend: multi-file upload, chat creation over the uploaded set, and a
  dataset-name chip on each chart/answer showing which dataset(s) produced it.

**Out of scope (explicitly deferred):**
- Attaching a dataset to a chat after it's created (mid-conversation). All datasets
  for a chat are fixed at creation time.
- General-purpose joins/merges beyond the single `compare` tool (no arbitrary
  multi-column joins, no persisted merged dataset).
- A dataset library/browse UI for picking previously-uploaded datasets into a new
  chat — datasets are uploaded fresh as part of chat creation.
- `make eval` golden-set updates for multi-dataset questions (the eval suite is
  still a stub per CLAUDE.md; noted as follow-up work, not a blocker here).

## 3. Data model

```
Chat
  id (PK)
  created_at
  # dataset_id column removed

ChatDataset (new)
  id (PK, UUID, default per Base._uuid — same convention as every other table)
  chat_id (FK -> chats.id, cascade delete)
  dataset_id (FK -> datasets.id, cascade delete)
  ordinal_position   # order dataset_ids were listed in POST /chats; used for stable labeling
  UniqueConstraint(chat_id, dataset_id)   # same pattern as DatasetColumn's uq constraint
```

`Dataset`, `DatasetColumn`, `ChatMessage`, and `Analysis` are unchanged. Each
`Dataset.profile_json` continues to be built once, independently, at upload time —
`profile_dataframe()` itself does not change.

## 4. API surface

| Route | Change |
|---|---|
| `POST /datasets` | Unchanged — still creates one `Dataset` from one CSV. |
| `GET /datasets/{id}` | Unchanged. |
| `POST /chats` | **New.** Body `{"dataset_ids": [...]}`. Validates every ID exists (404 if not), creates `Chat` + `ChatDataset` rows, returns `{"id": ..., "datasets": [{"id", "name"}, ...]}`. |
| `POST /chats/{chat_id}/messages` | **New**, replaces `POST /datasets/{id}/chat`. Body `{"question": "..."}`. Same response shape as today (`ChatMessageOut`: content, charts, stats, errors). |
| `GET /chats/{chat_id}` | **New**, replaces `GET /datasets/{id}/chat`. Returns message history (charts re-rendered from each dataset's `data_csv` + stored `tool_calls`) plus the attached dataset list. |
| `POST /datasets/{dataset_id}/chat` (GET/POST) | **Removed**, along with its route file and tests. No back-compat shim — pre-launch code, no external consumers (D4: no users/sessions to migrate). |

## 5. Tool-calling & analysis engine

`tools.py` — `TOOL_DEFS`:
- `histogram(dataset_id, column)`
- `scatter(dataset_id, x, y)`
- `correlation_matrix(dataset_id)`
- `compare(dataset_a_id, dataset_b_id, key_a, key_b, metric_a, metric_b, agg)` — new.
  `agg` ∈ `{"mean", "sum", "count"}`. Join is always inner (only keys present in
  both datasets are compared).

`validate_tool_call(name, args, profiles)` — signature changes from a single
`profile` dict to `profiles: dict[str, dict]` keyed by `dataset_id`. Unknown
`dataset_id` → tool-error string (same graceful-error pattern as today, not an
HTTP error). For `compare`: validates both key columns exist in their respective
profiles and both metric columns are numeric.

`charts.py` — `_DISPATCH` functions take `dfs: dict[str, DataFrame]` instead of a
single `df`. New `compare` analysis function: selects `[key_a, metric_a]` /
`[key_b, metric_b]`, inner-joins on key, groups by key, aggregates with `agg`,
renders a grouped bar chart via the existing fresh-`Figure`/`Agg`-backend pattern
(no `pyplot` global state, per the base design's constraint).

`routes/chats.py` loads every attached dataset's CSV into a `dfs` dict once per
request via `load_csv()`.

## 6. Prompt assembly

`llm.run_pass()` changes to accept `profiles: dict[str, dict]` (one entry per
attached dataset) instead of a single profile, and assembles one labeled
system-prompt section per dataset (by dataset name/id) so Claude can address them
individually and by the tool's `dataset_id` arguments.

**Combined token budget:** `profile_dataframe()` and its per-dataset degrade logic
are unchanged. A second-level check in `run_pass()` sums the serialized size of all
attached profiles; if the total exceeds `settings.profile_token_budget * n_datasets`,
`sample_rows` is dropped from every attached profile (cheapest cut, same priority
order as the existing single-dataset degrade) until under budget.

## 7. Frontend

- `UploadPage`: dropzone accepts multiple files. Each is uploaded individually via
  the existing `uploadDataset()` (endpoint unchanged), collecting `DatasetOut[]`.
  On confirm, calls new `createChat(datasetIds)` and navigates to `/c/:chatId`.
- `DatasetPage` → renamed `ChatPage`; route `/d/:id` → `/c/:chatId`; fetches via
  `GET /chats/{chatId}`.
- `ChatTurn` / `ChartList`: each chart shows a dataset-name chip, derived from the
  chat's dataset list plus the `dataset_id` (or `dataset_a_id`/`dataset_b_id`) already
  present in the stored `tool_calls` for that message.
- `api.ts`: `getChatHistory` / `postChat` re-pointed at `/chats/{id}`; new
  `createChat(datasetIds)`.

## 8. Error handling

Unchanged pattern. Validation failures (unknown `dataset_id`, column not found,
non-numeric column, join key not found in one/both datasets) are collected into the
existing `errors: string[]` on the response and rendered by `ErrorBanner` — never
raised as a mid-turn HTTP error, consistent with "backend validates Claude's tool
args before executing."

## 9. Testing

Backend (new/updated, `backend/tests/`):
- `ChatDataset` model + cascade-delete behavior.
- `POST /chats`: multi-ID create, unknown-ID 404, empty-list rejection.
- `POST /chats/{id}/messages` / `GET /chats/{id}`: multi-dataset history re-render.
- `compare` tool: schema validation (unknown key, non-numeric metric), analysis
  function correctness (join + aggregate for `mean`/`sum`/`count`).
- Existing `histogram`/`scatter`/`correlation_matrix` tests updated for the new
  required `dataset_id` argument.
- Old `/datasets/{dataset_id}/chat` route tests removed.

Frontend (`frontend/src/`):
- `UploadPage.test.tsx`: multi-file selection, chat creation call.
- `DatasetPage.test.tsx` → `ChatPage.test.tsx`: dataset chips render correctly per
  tool call.

## 10. Docs to sync (per CLAUDE.md doc-sync rule)

- `README.md` — quickstart flow now describes multi-file upload.
- `CLAUDE.md` — code layout (`ChatPage` rename, `ChatDataset` table, tool schema
  changes, removed route), any design-decision notes affected.
- `doc/project-1-csv-analysis-assistant-design.md` — note the `compare`/join
  capability as an *addition* to D2 (single-pass LLM, unaffected — still one call
  per turn) and D5 (raw CSV as sole durable copy — merged data stays in-memory,
  never persisted), not a reversal of either.
