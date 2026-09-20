# Project 1 — Week 2 End-to-End Flow Design

**Source ticket:** [wavepoint-build/ai-engineering-workshop#12](https://github.com/wavepoint-build/ai-engineering-workshop/issues/12) — "[P1 W2] Core user flow: CSV upload → chart + LLM interpretation".
**Status:** Approved 2026-07-03. Builds on the approved architecture in `doc/project-1-csv-analysis-assistant-design.md` and the schema in `backend/db/schema.sql` (#11).

## Goal

Ship the core user flow end-to-end: upload a CSV, ask a natural-language question, get a chart plus an LLM interpretation, rendered in a React UI. A **single Claude pass** reads the dataset profile, selects tools from a fixed menu, and writes the interpretation.

## Scope

Full flow, delivered in four phases matching the workshop's "1 PR/day Mon–Thu" cadence: (1) schema reconcile + `dataset_columns` on upload, (2) analysis engine + tool defs, (3) LLM orchestrator + chat persistence, (4) React/Vite frontend. There is no auth (D4) — a dataset `id` is its own shareable link.

## Confirmed decisions

- **Charts are base64, never stored.** Analysis functions return PNG-as-base64 in the response; on history reload the backend re-renders from `datasets.data_csv` + a message's `tool_calls`. `analyses.output_path` stays `NULL` — reserved for a future chart-persistence feature.
- **Auto single chat per dataset.** `POST /datasets/{id}/chat` gets-or-creates the dataset's one `Chat`. The schema still permits multiple chats per dataset for a later iteration.
- **`models.py` reconciled to `schema.sql`.** The just-pushed SQLAlchemy models diverge from the canonical hand-authored DDL; Phase 1 aligns them (see below). All tables remain in the `app` Postgres schema.
- **Model is configurable.** `Settings.anthropic_model` defaults to `claude-sonnet-5` (the ticket named `claude-sonnet-4-6 or latest`; Sonnet 5 is the current Sonnet — near-Opus quality at Sonnet cost for single-pass tool-calling). Overridable via `.env` for dev/eval.

## Architecture

New modules under `backend/app/`, each with one responsibility:

| Module | Responsibility | Depends on |
|---|---|---|
| `analysis.py` | Chart/stat engine: `histogram(df, column)`, `scatter(df, x, y)`, `correlation_matrix(df)`. Each renders on a fresh matplotlib **Agg** `Figure`, returns `(png_base64: str, result_stats: dict)`, and closes the figure. Never touches `pyplot`. | pandas, matplotlib |
| `tools.py` | Static Claude tool definitions (JSON schema) for the three charts, plus `validate_tool_call(name, args, profile) -> None | error` that checks referenced columns exist and are numeric where required, **before** execution. | schemas only |
| `llm.py` | Single-pass orchestrator `run_pass(profile, prior_messages, question) -> LLMResult`. Builds messages (system prompt + profile JSON + prior turns + question), calls Claude with `tools=`, returns tool_use blocks + interpretation text + usage (tokens/cost/latency). API key from `ANTHROPIC_API_KEY`. | `anthropic` SDK, `tools.py` |
| `charts.py` | `render_message_charts(dataset, message) -> list[str]` — re-renders base64 charts from `data_csv` + `message.tool_calls` for the history path. | `dataset_io.load_csv`, `analysis.py` |
| `routes/chats.py` | `POST /datasets/{id}/chat`, `GET /datasets/{id}/chat`. | all of the above |
| `prompts/system.md` | Authored system prompt: tool-menu usage, interpretation style, single-pass framing. | — |

Frontend: new `frontend/` — React + Vite + TypeScript, a single page: upload panel → chat view (question box, rendered chart images, interpretation text, conversation history).

## Data flow (one question)

1. **Upload** (`POST /datasets`, exists) — additionally writes one `dataset_columns` row per column (name, ordinal_position, inferred_type, null_count) during the same transaction that persists the `Dataset`.
2. **Ask** (`POST /datasets/{id}/chat {question}`):
   - get-or-create the dataset's single `Chat`;
   - persist the user `ChatMessage`;
   - `llm.run_pass(profile, prior_messages, question)`;
   - `validate_tool_call(...)` each requested tool — on failure, record a graceful per-chart error entry and skip execution (never pass unchecked args to `analysis.py`);
   - execute valid calls via `analysis.py`;
   - persist the assistant `ChatMessage` (`tool_calls`, `tokens_in/out`, `cost_usd`, `latency_ms`) and one `Analysis` row per chart;
   - return `{ interpretation, charts: [base64...], stats, errors: [...] }`.
3. **History** (`GET /datasets/{id}/chat`) — messages ordered by `created_at`; charts re-rendered via `charts.render_message_charts` from `data_csv` + `tool_calls`. No stored images.

## Phase 1 detail — schema reconciliation

Align `backend/app/models.py` to the canonical `backend/db/schema.sql`:

- `analyses`: rename `chat_message_id` → `message_id`; add `result_stats` (JSON, nullable); keep `output_path` nullable/unused.
- `dataset_columns`: add `ordinal_position` (int, not null) and `UNIQUE(dataset_id, name)`.
- `chat_messages.cost_usd`: `Float` → `Numeric(10, 6)`.
- Add indexes on FK columns (`dataset_columns.dataset_id`, `chats.dataset_id`, `chat_messages.chat_id`, `analyses.message_id`) plus the `(…, created_at)` composites, via `index=True` / `__table_args__`.
- Populate `dataset_columns` in the upload route from the profile.

Tests build the DB from `models.py` against SQLite; production uses Postgres via `schema.sql`. After this phase the two agree on names, columns, and constraints.

## Configuration

New `Settings` fields (pydantic-settings, `.env`-overridable; documented in `.env.example`):

- `anthropic_api_key: str` (required for `/chat`; never hardcoded).
- `anthropic_model: str = "claude-sonnet-5"`.
- `anthropic_max_tokens: int = 4096`.

## Error handling

- **Tool-arg validation** is mandatory before execution; column/type mismatch → graceful error entry in the response, not an exception.
- **LLM failures** (network, 429, 5xx) — rely on the Anthropic SDK's built-in retries; surface a clean 502-style error to the client if the pass ultimately fails, and do not persist a partial assistant message.
- **matplotlib** — every chart uses a fresh `Figure` and is closed in a `finally`, so a render error in one chart can't leak state into another (Agg backend, thread-safe under FastAPI).

## Testing

- `analysis.py`: unit test each chart on a small fixed `DataFrame` — assert a non-empty base64 PNG and expected `result_stats`; assert the invalid-column path is rejected by the validator.
- `llm.py`: orchestrator test with a **mocked** Anthropic client — assert message assembly (system + profile + prior turns + question), tool wiring, and that returned tool_use blocks map to executed charts. No network in `make test`.
- `routes/chats.py`: integration — upload → chat (mocked LLM) → assert `chats`/`chat_messages`/`analyses` rows, response shape, and that `GET` re-renders charts from `data_csv` + `tool_calls`.
- Eval suite (`make eval`) stays separate and hits the real API.

## Out of scope (this milestone)

- Multiple chats per dataset (schema supports it; UI/endpoints deferred).
- Stored/persisted charts and `analyses.output_path` population (future feature; see the #12 flag comment).
- Auth / users (Project 2 fork).
- 2-pass LLM (revisit only if the eval keyword pass-rate drops below 80%, per D2).
