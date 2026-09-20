# UI/UX design foundation (issue #11, Slice A)

**Status:** Approved (2026-08-01)
**Branch:** `feat/issue-11-ui-ux-enhancements`
**Scope:** The first of several slices decomposed from issue #11 (UX/UI
improvements). This slice builds the **design foundation** — a tokenized,
accessible component layer — and restyles the two existing pages onto it. Later
slices build on it.

## Issue #11 decomposition

Issue #11 is too large for one spec. It is split into shippable slices; this doc
covers **Slice A** only.

| Slice | Contents | Depends on |
|-------|----------|-----------|
| **A — Design foundation** (this doc) | Component library + design tokens (color, type, spacing), app shell, dark mode, loading skeletons; restyle the existing Upload + Chat pages | none |
| B — Upload experience | Drag-drop, upload progress, human-readable errors, post-upload summary card, dataset preview (first 10 rows) + column type badges | A |
| C — Chat & message polish | Message timestamps, copy button, scroll-to-bottom, chart captions, chart zoom/expand (modal), chart download | A |
| D — Navigation & layout | Persistent sidebar (datasets + recent chats), session header/breadcrumb, empty states, keyboard shortcuts (`Cmd+K` dataset picker) | A; needs a backend "list chats/datasets" endpoint |
| E — Streaming responses | SSE token streaming + typing indicator | backend loop changes — tracked as its own issue |

Accessibility (focus management, ARIA, contrast) is woven through A–D, not a
standalone slice. **Markdown rendering (issue #5) is already implemented on
`main`** (`ChatTurn` renders assistant prose via `react-markdown` + `remark-gfm`)
and is therefore out of scope here.

## Goals (Slice A)

- A single, consistent set of **design tokens** (color, typography, spacing,
  radius) driving the whole UI, with a light and a dark value set.
- A small **component library** (`ui/`) of tokenized, accessible primitives that
  every later slice reuses.
- **Dark mode** with a persisted toggle, defaulting to the OS preference.
- **Loading skeletons** replacing bare spinner/"Loading…" text.
- The two existing pages (**Upload**, **Chat**) visibly improved — restyled onto
  the new system — so the slice is not invisible infrastructure.

## Non-goals (Slice A)

- **No new features.** Drag-drop, upload progress, dataset preview/type badges
  (Slice B); timestamps, copy button, scroll-to-bottom, chart
  captions/zoom/download (Slice C); sidebar, recent chats, breadcrumb, `Cmd+K`
  (Slice D); streaming (own issue). These are explicitly deferred.
- **No backend changes.** This slice is frontend-only.
- **No new chat/data behavior.** Markdown rendering, chart re-rendering, and the
  API contract are untouched.

## Decisions (from brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Styling / component approach | **Radix primitives + CSS-variable tokens + CSS modules.** Radix supplies accessibility for the hard interactive parts (modal, menu, dropdown); tokens + CSS modules keep the existing idiom. Rejected: Tailwind + shadcn/ui (large toolchain shift for a 2-page app); hand-built-everything (re-implementing accessible modals/menus by hand). |
| 2 | Visual direction | **"Warm friendly"** — teal accent (`#0d9488`), warm off-white surfaces, soft rounding. |
| 3 | Dark mode | **In scope.** Same CSS variables, `[data-theme="dark"]` overrides; persisted toggle defaulting to `prefers-color-scheme`. |
| 4 | Shell scope | **Restyle the two existing pages** onto tokens + components + an app shell + skeletons. No new features. |

## Architecture

Frontend-only. A token layer + a `ui/` component library sit under the existing
pages; a `ThemeProvider` and `AppShell` wrap the routes.

```
frontend/src/
  styles/
    tokens.css       # :root light vars + [data-theme="dark"] overrides; type + spacing + radius scales
    global.css       # base element styles (body, headings, links, focus-visible)
  theme.tsx          # ThemeProvider: light|dark, persisted to localStorage,
                     #   defaults to prefers-color-scheme; sets data-theme on <html>
  ui/                # component library (each: Component.tsx + Component.module.css)
    Button.tsx  Input.tsx  Textarea.tsx  Card.tsx
    Dialog.tsx       # wraps @radix-ui/react-dialog (accessible modal primitive)
    Skeleton.tsx  Badge.tsx  IconButton.tsx  ThemeToggle.tsx
    index.ts         # barrel export
  components/
    AppShell.tsx     # sticky topbar (brand + ThemeToggle) + max-width content region
```

**New dependency:** `@radix-ui/react-dialog` only. Slice C's chart-zoom and
Slice D's `Cmd+K` will add more Radix packages when they land. Tokens, type, and
spacing are hand-authored CSS variables with no runtime cost.

### Design tokens

CSS custom properties on `:root`, overridden under `[data-theme="dark"]`.

**Color (light → dark):**

| Token | Light | Dark |
|-------|-------|------|
| `--bg` | `#faf7f4` | `#1a1715` |
| `--surface` | `#fffdfb` | `#221e1b` |
| `--ink` | `#232022` | `#f2ede8` |
| `--muted` | `#736e6a` | `#a89f97` |
| `--line` | `#ece7e2` | `#322c28` |
| `--accent` (fills) | `#0d9488` | `#2dd4bf` |
| `--accent-text` (text on bg) | `#0f766e` | `#5eead4` |
| `--accent-ink` (text on accent) | `#ffffff` | `#0b1a18` |

Semantic tokens: `--danger`, `--success`, `--warn` (used by `ErrorBanner`,
badges).

**Type scale:** `--text-xs` 12 / `--text-sm` 13 / `--text-base` 14 / `--text-lg`
16 / `--text-xl` 20 / `--text-2xl` 26; weights 400/500/600/700; system font
stack (no web-font dependency). **Spacing scale:** 4 / 8 / 12 / 16 / 24 / 32.
**Radii:** `--radius-sm` 8 / `--radius-md` 10 / `--radius-lg` 14.

### Component inventory

Each is a thin, tokenized, accessible wrapper (`Component.tsx` +
`Component.module.css`):

- **Button** — `primary` / `ghost` variants, `sm` / `md` sizes, `disabled` and a
  `loading` state (inline spinner).
- **Input**, **Textarea** — Textarea autosizes; used by `QuestionBox`.
- **Card** — surface container (border, radius, padding tokens).
- **Dialog** — wraps `@radix-ui/react-dialog`; focus trap, Esc-to-close, ARIA
  handled by Radix. Shipped now; Slice C uses it for chart zoom.
- **Skeleton** — `line` / `block` variants; shimmer respects
  `prefers-reduced-motion`.
- **Badge** — chip; `DatasetChips` adopts it.
- **IconButton** — requires an accessible label; establishes the pattern Slice
  C's copy/download buttons follow.
- **ThemeToggle** — switches light/dark via the ThemeProvider.

### Shell + page restyle

- **AppShell** wraps both routes: a sticky topbar (brand left, `ThemeToggle`
  right) + a centered content container (~520px on Upload, ~820px on Chat),
  responsive padding. Usable ≥768px; degrades gracefully narrower. (The topbar
  is where Slice D later adds the breadcrumb/session header.)
- **UploadPage** → a centered `Card` with a friendly empty-state hero, the file
  input + `Button`. No drag-drop (Slice B).
- **ChatPage** → `AppShell` + `DatasetChips` in the topbar, the message list, a
  `QuestionBox` (`Textarea` + `Button`), a `Skeleton` message placeholder
  replacing the bare "Loading…", and a proper "no messages yet" empty state.
- **ChatTurn / QuestionBox / DatasetChips / StatsDetails / ErrorBanner** →
  restyled onto tokens + `ui/` components. Markdown rendering preserved as-is.

## Accessibility

- Every `ui/` component carries a `focus-visible` ring (`--accent`).
- Accent shades are chosen and **verified to meet WCAG AA**: `--accent` is used
  for fills, and a darker `--accent-text` is used for accent-colored text on the
  light background so normal text clears 4.5:1. Contrast is re-checked for the
  dark set.
- Radix `Dialog` provides modal focus trapping, Esc handling, and ARIA.
- Keyboard flow through the upload → chat path is preserved; icon buttons require
  labels; the file input keeps its existing `aria-label`.

## Testing

- **Vitest / React Testing Library:**
  - Button — renders each variant, `disabled`, and `loading` (spinner shown,
    click suppressed).
  - Dialog — opens on trigger, closes on Esc, returns focus to the trigger.
  - ThemeToggle — flips `data-theme` on `<html>` and persists to localStorage;
    ThemeProvider reads the persisted value / OS default on mount.
  - Skeleton — renders line/block variants.
- **Existing page tests stay green.** They query by role / label / text; the
  restyle preserves roles and `aria-label`s, so no test rewrites are expected
  beyond incidental selector updates.
- **Manual:** dark-mode toggle round-trip; responsive layout at 768px.

## Rollout

- One PR on `feat/issue-11-ui-ux-enhancements`, off `main`.
- Additive: no data migration, no API change, no behavior change to chat/upload
  beyond appearance.
- Follow-up slices (B, C, D) each get their own spec → plan → PR, building on
  this foundation. Streaming (E) is tracked as a separate issue.

## Doc sync (required before merge, per CLAUDE.md)

- `README.md` — note dark mode + the refreshed UI in the feature list if
  warranted; no command changes.
- `CLAUDE.md` — add the `frontend/src/ui/`, `styles/`, `theme.tsx`, and
  `AppShell` to the code-layout section; note the Radix + CSS-token foundation
  decision.
- `doc/plans/` — tick off the Slice A implementation-plan tasks as they complete.

## Deferred / future slices

- **Slice B** — upload experience (drag-drop, progress, preview, type badges).
- **Slice C** — chat polish (timestamps, copy, scroll-to-bottom, chart
  captions/zoom/download); reuses `Dialog`.
- **Slice D** — navigation (sidebar, recent chats, breadcrumb, `Cmd+K`); needs a
  backend list endpoint.
- **Slice E** — streaming responses; separate issue (backend loop changes).
