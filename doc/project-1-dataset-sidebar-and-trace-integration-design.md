# Dataset Sidebar + Loop-Trace Integration — Design

**Status:** Approved (2026-08-02)
**Branch:** `feat/issue-11-ui-ux-enhancements` (after merging `origin/main`)

## Summary

Two threads come together on the UI/UX branch:

1. **Dataset sidebar** — a collapsible left navigation listing previously
   uploaded datasets (Claude-sidebar style). Clicking a dataset starts a chat
   over it; a hover-revealed multi-select lets the user start a chat over
   several datasets at once.
2. **Loop-trace integration** — the multi-pass judge-gated loop and its
   per-pass trace already exist on `main` (merged from `feat/LLM-loop`). The
   trace's `PassTrace` component predates this branch's tokenized design system,
   so it is re-skinned and its content refined to fit the polished UI. The
   backend already excludes the system prompt from the trace; that is unchanged.

This is an **integration**, not a rebuild. The loop backend, the trace schema
(`MessageTraceOut` / `PassTraceOut`), and the trace route are consumed as-is.

## Non-goals

- No change to the loop orchestrator, the judge, or the trace payload shape.
- No change to the system-prompt exclusion — `MessageTraceOut` already omits it
  by construction, and that guarantee is preserved.
- No auth / user scoping (design D4 still holds): the dataset list is global.
- No new dataset detail page or route; the sidebar acts directly on datasets.
- No "recent chats" section in the sidebar (datasets only, per the request).

## A. Integration: merge `origin/main`

`main` now carries the loop. Merge it into `feat/issue-11-ui-ux-enhancements`
before any new work.

- **Expected conflicts:** `backend/app/routes/chats.py`, `backend/app/schemas.py`,
  `frontend/src/types.ts`, and `frontend/src/components/ChatTurn.tsx` (main
  renders the trace inside `ChatTurn`; this branch restyled that file).
  `README.md` / `CLAUDE.md` may also conflict.
- **Resolution principle:** keep the loop/trace behavior from `main` and the
  tokenized presentation from this branch. When a component conflicts, the
  new-design version wins for markup/styling and the loop version wins for
  data flow.
- **Green baseline:** after the merge, run the full backend suite
  (`make test`) and the full frontend suite (`npm test`, `npm run build`) and
  confirm both pass **before** adding the sidebar or touching the trace. A
  merge that leaves either suite red is a blocker, not a starting point.

## B. Backend: dataset-list endpoint

Add a single read endpoint so the sidebar has data to show.

- **Route:** `GET /datasets` in `backend/app/routes/datasets.py`.
- **Response:** `list[DatasetOut]` — the existing schema (`id`, `name`,
  `n_rows`, `n_cols`). `content_hash` stays internal (not in `DatasetOut`).
- **Ordering:** `Dataset.created_at DESC` (newest first). The column already
  exists on the model.
- **Scope:** no user scoping (D4) — returns every dataset. Correct for this
  project; a dataset id is its own shareable link.
- **No new migration** — read-only over existing columns.

**Test** (`backend/tests/test_datasets.py` or a new file):
- empty DB → `[]`
- two uploads → both returned, newest first
- response items expose `id/name/n_rows/n_cols` and **not** `content_hash`.

## C. Frontend: the sidebar

### Layout
Promote `AppShell` from a topbar-only shell to a **two-column layout**: a
collapsible left sidebar plus the existing content region. The sidebar is
persistent across `/` (UploadPage) and `/c/:chatId` (ChatPage), so it wraps the
routed content — it lives in `AppShell`, and both pages already render through
`AppShell`.

### Sidebar component (`frontend/src/components/DatasetSidebar.tsx`)
- Fetches datasets via a new `listDatasets()` wrapper in `api.ts`
  (`GET /datasets` → `DatasetOut[]`).
- Renders each dataset as a row: **name** + a muted `n_rows × n_cols` meta line.
- Loading → `Skeleton` rows; empty → a short "No datasets yet — upload one"
  hint linking to `/`.
- Header: a "New upload" link/button routing to `/`.

### Interaction
- **Primary click on a row → instant chat.** Calls `createChat([datasetId])`
  and navigates to `/c/:chatId`. This is the fast path.
- **Multi-select (hover-revealed).** Hovering a row reveals a checkbox
  (always focusable for keyboard/a11y even when visually revealed on hover).
  Toggling one or more checkboxes puts the sidebar in "selection" state and
  shows a footer action **"Start chat with N datasets"**, which calls
  `createChat(selectedIds)` and navigates. Clearing all selections dismisses
  the footer. While a selection is active, a bare row click toggles that row's
  checkbox rather than starting a single chat, so the two paths don't fight.

### Collapse
- A toggle in the sidebar header collapses it (Claude-style). Collapsed state
  is persisted to `localStorage` under `wp-sidebar`, mirroring the existing
  `wp-theme` pattern in `theme.tsx`.
- Default: expanded on wide viewports. At narrow widths the sidebar collapses
  by default and expands as an overlay, so it never crowds the content column.

### Accessibility
- The sidebar is a `<nav aria-label="Datasets">`.
- Rows are buttons/links with accessible names = the dataset name.
- Checkboxes have accessible names like `Select <dataset name>`.
- The collapse toggle exposes `aria-expanded`.

## D. Trace: restyle + refine

Re-skin `frontend/src/components/PassTrace.tsx` from raw HTML + global CSS
classes to CSS-module tokens plus the `Card` / `Badge` primitives, and refine
what it shows.

- **Outer disclosure** "Loop trace (N passes)" is kept (a `<details>`-style
  or tokenized disclosure).
- **Per-pass collapse.** Each pass becomes its own collapsible row with a
  header: `Pass 1 · judge 82/100`. The score renders as a **color-coded
  `Badge`** — an "accepted" tone when the pass was accepted / high score, a
  "needs-revision" tone otherwise. A failed judge (`score === null`) shows a
  neutral/danger "judge failed" badge.
- **Body** (when a pass is expanded): analyst interpretation, the pass's charts
  (`ChartList`), judge feedback, and judge gaps as a clean list; the revision
  instruction fed to the next pass when present.
- **Demoted meta.** The token / cost / latency line (`model · in/out · ms · $`)
  moves to a **small muted footer** inside each pass — retained, de-emphasized,
  not removed.
- **System prompt stays excluded** — no field for it exists in the trace
  payload, and none is added.

**Tests** (`PassTrace.test.tsx`): assert on roles / accessible names / visible
text (pass headers, judge score text, feedback, the demoted meta text), never
on CSS-module class names (Vitest runs with `css: false`).

## E. Testing & documentation

- **Backend:** the `GET /datasets` test above; existing suites stay green.
- **Frontend:** sidebar tests (renders list from mocked fetch, single click
  creates a chat and navigates, multi-select shows the footer and creates a
  multi-dataset chat, collapse toggles and persists) and the restyled
  `PassTrace` tests. Mock `fetch` and router navigation as the existing tests do.
- **Doc sync** (required before merge, per `CLAUDE.md`):
  - `README.md` — add `GET /datasets` to the endpoints table; mention the
    dataset sidebar and the refined trace in the feature list.
  - `CLAUDE.md` — note the new endpoint, the sidebar in the code-layout section,
    and the trace restyle.
  - This design doc — the record of the decision.

## Interfaces (for the implementation plan)

- `GET /datasets` → `DatasetOut[]` (ordered newest-first).
- `listDatasets(): Promise<DatasetOut[]>` — new `api.ts` wrapper.
- `createChat(datasetIds: string[])` — **existing**, reused unchanged.
- `DatasetSidebar` — new component, rendered inside `AppShell`.
- `AppShell` — gains the two-column collapsible layout; existing
  `topbarRight` / `width` props preserved.
- `PassTrace` — same `{ trace?: MessageTraceOut | null }` prop; internals
  restyled and refined.
