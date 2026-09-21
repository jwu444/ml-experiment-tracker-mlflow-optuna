# Project 1 — Week 2 Frontend Design

**Source ticket:** `wavepoint-build/ai-engineering-workshop#12` (private repo) — "[P1 W2] Core user flow: CSV upload → chart + LLM interpretation", Phase 4 (React/Vite frontend).
**Status:** Approved 2026-07-04. Builds on the backend delivered in Phases 1–3 (see `doc/project-1-week2-end-to-end-flow-design.md`) and consumes its HTTP contract unchanged.

## Goal

Ship the React single-page UI for the core flow: upload a CSV, land on a dataset page, ask natural-language questions, and see the assistant's chart images, prose interpretation, collapsible raw stats, and any per-chart error warnings — with the dataset `id` carried in the URL so a page is shareable and reload-safe.

## Confirmed decisions

- **Fidelity: clean functional demo.** A tested SPA with plain CSS (CSS Modules), no design system, no component library. Meets the workshop bar with a clean base for the Project 2 fork.
- **URL carries the dataset id.** After upload the app routes to `/d/{id}`. Reloading or sharing that URL re-hydrates the dataset header and full chat history from the backend. The URL is the only persisted client state.
- **Charts + prose primary; stats collapsible; errors always visible.** Each assistant turn renders the interpretation text and chart images prominently, tucks raw `stats[]` behind a `<details>` toggle, and always shows `errors[]` as inline warning banners — even when some charts rendered successfully.
- **CSS Modules over a global stylesheet.**
- **Hand-mirrored `types.ts` over OpenAPI codegen.** The contract is four small models; generation is overkill for a demo.

## Backend HTTP contract (consumed, not changed)

The frontend targets these existing endpoints (see `backend/app/schemas.py`, `backend/app/routes/`):

| Method & path | Request | Response |
|---|---|---|
| `POST /datasets` | multipart `file` (CSV) | `DatasetOut` |
| `GET /datasets/{id}` | — | `DatasetOut` |
| `POST /datasets/{id}/chat` | `{ question: string }` | `ChatMessageOut` (assistant turn) |
| `GET /datasets/{id}/chat` | — | `{ messages: ChatMessageOut[] }` |

Response shapes:

```ts
// DatasetOut
{ id: string; name: string; n_rows: number; n_cols: number }

// ChatMessageOut
{
  id: string;
  role: string;            // "user" | "assistant"
  content: string;         // prose interpretation (assistant) or the question (user)
  charts: string[];        // base64-encoded PNG payloads
  stats: Record<string, unknown>[];
  errors: string[];
}
```

Charts are base64 PNG payloads rendered as `<img src={`data:image/png;base64,${c}`}>`. On an unknown dataset id, both `GET /datasets/{id}` and the chat endpoints return `404`.

## Architecture

A new `frontend/` directory sibling to `backend/`, built with Vite + React + TypeScript. Routing via `react-router-dom`. State via React hooks (`useState`/`useEffect`) — no data library. Styling via CSS Modules.

```
frontend/
  package.json
  vite.config.ts          # dev server + /api → backend proxy
  tsconfig.json
  tsconfig.node.json      # for vite.config.ts type-checking
  index.html
  .env.example            # documents VITE_API_BASE
  src/
    main.tsx              # ReactDOM root + <BrowserRouter>
    App.tsx               # <Routes>: "/" → UploadPage, "/d/:id" → DatasetPage
    api.ts                # typed fetch client; one function per endpoint
    types.ts              # DatasetOut, ChatMessageOut hand-mirrored from schemas.py
    pages/
      UploadPage.tsx      # file picker → POST /datasets → navigate("/d/:id")
      DatasetPage.tsx     # loads dataset + history; owns chat state
    components/
      ChatTurn.tsx        # one message: role, prose, charts, stats, errors
      ChartList.tsx       # base64 PNGs → <img>
      StatsDetails.tsx    # <details> collapsible raw stats (JSON pretty-print)
      QuestionBox.tsx     # textarea + submit; disabled while a POST is pending
      ErrorBanner.tsx     # inline warning for errors[] entries and fetch failures
    *.module.css
    setupTests.ts         # RTL + jest-dom matchers (referenced by vite.config.ts test block)
```

Test configuration lives in `vite.config.ts` (a `test:` block, jsdom environment) rather than a separate `vitest.config.ts`, keeping one config file.

### Component responsibilities

| Unit | Responsibility | Depends on |
|---|---|---|
| `api.ts` | One typed async function per endpoint (`uploadDataset`, `getDataset`, `getChatHistory`, `postChat`). Prefixes `VITE_API_BASE` (default `/api`). Maps non-2xx to a thrown `ApiError { status, message }`. | `types.ts` |
| `types.ts` | `DatasetOut`, `ChatMessageOut`, `ChatHistoryOut` interfaces mirroring `schemas.py`. | — |
| `UploadPage` | File `<input accept=".csv">`, submit → `uploadDataset` → `navigate("/d/{id}")`. Shows `ErrorBanner` on failure; disables submit while pending. | `api.ts`, router |
| `DatasetPage` | On mount, parallel `getDataset` + `getChatHistory`. Owns `messages` state. Renders header (name, n_rows × n_cols), the turn list, and `QuestionBox`. On submit, calls `postChat`, appends the user turn then the returned assistant turn. | `api.ts`, components |
| `ChatTurn` | Renders one `ChatMessageOut`: role label, `content` prose, `ChartList`, `StatsDetails`, `ErrorBanner` per `errors[]`. | `ChartList`, `StatsDetails`, `ErrorBanner` |
| `ChartList` | Maps `charts[]` to `<img>` data-URIs with alt text. | — |
| `StatsDetails` | `<details>` wrapping pretty-printed `stats[]`; nothing rendered when empty. | — |
| `QuestionBox` | Controlled textarea + submit button; `disabled` + spinner text while pending; clears on success. | — |
| `ErrorBanner` | Presentational warning styling for a message string. | — |

## Data flow (one question)

1. **Upload** (`/`): user picks a CSV → `uploadDataset(file)` → `DatasetOut` → `navigate("/d/{id}")`.
2. **Dataset page mount** (`/d/:id`): `Promise.all([getDataset(id), getChatHistory(id)])`. While pending, show "Loading…". On `404`, show a not-found message. On success, render header + history. Empty history shows a "Ask your first question" prompt.
3. **Ask**: `QuestionBox` submit → optimistic disable → `postChat(id, question)`. On success, append a synthetic user turn (`{ role: "user", content: question, charts: [], stats: [], errors: [] }`) followed by the returned assistant `ChatMessageOut`; clear and re-enable the box. On failure, re-enable and show an `ErrorBanner`; do not append turns.
4. **Reload/share** of `/d/:id` repeats step 2 — all state re-hydrates from the two GETs.

Rationale for append-only (no refetch after POST): the backend chat is append-only and `postChat` returns the authoritative assistant turn, so a full `getChatHistory` refetch would be redundant. History is only fetched on mount.

## Backend connection (CORS)

- **Dev:** `vite.config.ts` proxies `/api` → `http://localhost:8000` (`changeOrigin: true`, rewrite strips the `/api` prefix). The client calls same-origin `/api/...`, so no CORS in dev.
- **Prod:** add `fastapi.middleware.cors.CORSMiddleware` inside `create_app()`, with origins from a new `Settings.cors_allow_origins: list[str]` (env-overridable, documented in `.env.example`; default `["http://localhost:5173"]` for local Vite). This is the one required backend change; it is a small standalone task in the plan and does not alter any route or schema.
- `api.ts` reads `import.meta.env.VITE_API_BASE` (default `/api`) so the same client works behind the dev proxy and against an absolute prod URL.

## Error & loading handling

- **Fetch failures** (network, non-2xx) throw `ApiError`; each page catches and renders an `ErrorBanner` rather than crashing.
- **Per-chart errors** from a successful chat response render as inline warnings alongside whatever charts did render — never suppressed.
- **Pending states:** `QuestionBox` disables and shows progress text during a POST; `DatasetPage` shows "Loading…" during initial GETs; `UploadPage` disables submit during upload.
- **404 dataset:** friendly "Dataset not found" with a link back to `/`.

## Testing

Vitest + React Testing Library with `fetch` mocked (no live backend; excluded from the backend `make test` gate).

- `api.ts` — asserts request URL/method/body per function and that a non-2xx maps to a thrown `ApiError`.
- `UploadPage` — happy path calls `uploadDataset` and navigates to `/d/{id}`; upload error renders a banner and does not navigate.
- `DatasetPage` — renders fetched history; submitting a question appends the user turn and the returned assistant turn; a failed POST shows a banner and appends nothing.
- `ChatTurn` — renders `content`, renders one `<img>` per chart, keeps `stats` collapsed by default, and renders a warning per `errors[]` entry.

## Tooling & scripts

- `package.json` scripts: `dev` (vite), `build` (`tsc && vite build`), `preview`, `test` (`vitest run`), `test:watch`, `lint` (optional ESLint), `type-check` (`tsc --noEmit`).
- Node/npm managed at the `frontend/` level; the repo `Makefile` may gain optional `frontend-install` / `frontend-test` targets (nice-to-have, not required by this milestone).
- TypeScript `strict: true`.

## Out of scope (this milestone)

- Auth / users (Project 2 fork).
- Multi-dataset listing or navigation; chart download/zoom; message editing/deletion.
- Streaming responses; optimistic assistant rendering before the POST resolves.
- Design system, theming, dark mode.
- Client state libraries (Redux/Zustand) and data-fetching libraries (React Query).
- OpenAPI type generation.
