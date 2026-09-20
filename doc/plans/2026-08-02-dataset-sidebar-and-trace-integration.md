# Dataset Sidebar + Loop-Trace Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a collapsible left sidebar of previously uploaded datasets and fold the already-merged multi-pass loop trace into the tokenized UI.

**Architecture:** Merge `origin/main` (which now carries the loop + trace) into the UI branch, add one read-only `GET /datasets` endpoint, build a `DatasetSidebar` rendered inside a two-column `AppShell`, and restyle the existing `PassTrace` component with CSS-module tokens + `Card`/`Badge` primitives. No changes to the loop orchestrator or the system-prompt exclusion.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (backend), React 18 + Vite + TypeScript + CSS-module design tokens (frontend), pytest + Vitest/RTL.

## Global Constraints

- Design spec: `doc/project-1-dataset-sidebar-and-trace-integration-design.md`.
- No auth / no user scoping (design D4): `GET /datasets` returns **all** datasets.
- `content_hash` is internal — never add it to `DatasetOut` or any response.
- The system prompt is **never** exposed in the trace; the trace payload shape is not changed. Add no field for it.
- Frontend absolute-import style is not used; components import siblings by relative path (matches existing files).
- Line length 100 (ruff + black); mypy strict on `backend/app`.
- Vitest runs with `css: false` → tests assert on **roles / accessible names / `data-*` / visible text**, never CSS-module class names.
- Frontend tests mock `fetch`/api wrappers and mock router navigation via the existing `vi.mock("react-router-dom", …useNavigate)` pattern.
- Sidebar collapse state persists to `localStorage` key `wp-sidebar` (mirrors the `wp-theme` pattern).
- Every task ends green: backend `make test`, frontend `npm test` + `npm run build`.
- Doc-sync rule (`CLAUDE.md`): update `README.md` + `CLAUDE.md` in the same task that changes user-facing behavior.

---

### Task 1: Merge `origin/main` and establish a green baseline

This task has no new feature code — its deliverable is a merged, fully green tree that contains both the tokenized UI (this branch) and the loop + trace (main).

**Files (resolve conflicts, do not rewrite):**
- Likely conflicts: `frontend/src/components/ChatTurn.tsx`, `backend/app/db.py`, and possibly `README.md` / `CLAUDE.md`. The exact set is discovered at merge time.

**Resolution rule:** keep the **loop/trace behavior from `main`** and the **tokenized presentation from this branch**. When a component conflicts, the new-design version wins for markup/styling; the loop version wins for data flow.

- [ ] **Step 1: Confirm branch and clean tree**

Run: `git status` and `git branch --show-current`
Expected: on `feat/issue-11-ui-ux-enhancements`, working tree clean.

- [ ] **Step 2: Fetch and start the merge**

```bash
git fetch origin
git merge origin/main
```

- [ ] **Step 3: Resolve `frontend/src/components/ChatTurn.tsx`**

Keep this branch's tokenized markup, and ensure the assistant turn renders the trace exactly as main wired it. The styled `ChatTurn` must include, after the interpretation/charts/stats and before the closing wrapper:

```tsx
import PassTrace from "./PassTrace";
// …inside the assistant turn body:
<PassTrace trace={message.trace} />
```

`PassTrace` no-ops when `trace` is null/empty, so it is safe for user rows and pre-trace rows.

- [ ] **Step 4: Resolve `backend/app/db.py` if conflicted**

Keep **both** changes: main's loop-related edits AND this branch's SQLite `schema_translate_map` block:

```python
engine = create_engine(settings.database_url, future=True)
if engine.dialect.name == "sqlite":
    engine = engine.execution_options(schema_translate_map={"app": None})
```

- [ ] **Step 5: Resolve any `README.md` / `CLAUDE.md` conflicts**

Keep both feature sets' prose (loop + UI). Do not delete either side's additions.

- [ ] **Step 6: Complete the merge**

```bash
git add -A
git commit --no-edit
```

- [ ] **Step 7: Backend suite green**

Run: `make test`
Expected: all pass. If red, fix the merge resolution — do not proceed.

- [ ] **Step 8: Frontend suite + build green**

Run: `cd frontend && npm test && npm run build`
Expected: all tests pass, `tsc` clean, build succeeds. If red, fix before proceeding.

- [ ] **Step 9: Confirm the merge commit is recorded**

Run: `git log --oneline -3`
Expected: a merge commit joining `origin/main`.

---

### Task 2: `GET /datasets` list endpoint

**Files:**
- Modify: `backend/app/routes/datasets.py`
- Test: `backend/tests/test_datasets.py`
- Docs: `README.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: existing `DatasetOut` (`id`, `name`, `n_rows`, `n_cols`); `Dataset` model with `created_at`.
- Produces: `GET /datasets` → `list[DatasetOut]`, ordered `created_at DESC`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_datasets.py`. The ordering test inserts rows with **explicit** `created_at` (SQLite `func.now()` is second-precision, so upload timing can tie):

```python
def test_list_datasets_empty(client):
    assert client.get("/datasets").json() == []


def test_list_datasets_newest_first_and_shape(client):
    import datetime as dt

    from app.db import get_session
    from app.models import Dataset

    session = next(client.app.dependency_overrides[get_session]())
    older = Dataset(
        name="older.csv", n_rows=1, n_cols=1, profile_json={"columns": []},
        data_csv="a\n1\n", content_hash="hash-older",
        created_at=dt.datetime(2020, 1, 1, 0, 0, 0),
    )
    newer = Dataset(
        name="newer.csv", n_rows=2, n_cols=2, profile_json={"columns": []},
        data_csv="a,b\n1,2\n", content_hash="hash-newer",
        created_at=dt.datetime(2021, 1, 1, 0, 0, 0),
    )
    session.add_all([older, newer])
    session.commit()

    listed = client.get("/datasets").json()
    assert [d["name"] for d in listed] == ["newer.csv", "older.csv"]
    assert set(listed[0]) == {"id", "name", "n_rows", "n_cols"}
    assert "content_hash" not in listed[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest backend/tests/test_datasets.py::test_list_datasets_newest_first_and_shape -v`
Expected: FAIL — the route returns 404/405 (no collection GET yet).

- [ ] **Step 3: Add the endpoint**

In `backend/app/routes/datasets.py`, add above the existing `@router.get("/{dataset_id}", …)` route (so the collection route is not shadowed by the path param):

```python
@router.get("", response_model=list[DatasetOut])
def list_datasets(session: Session = Depends(get_session)) -> list[Dataset]:
    return list(
        session.execute(select(Dataset).order_by(Dataset.created_at.desc())).scalars()
    )
```

`select` and `Session`/`Depends` are already imported in this file.

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest backend/tests/test_datasets.py -v`
Expected: all pass, including the two new tests.

- [ ] **Step 5: Full backend gate**

Run: `make check`
Expected: ruff + black + mypy + pytest all clean.

- [ ] **Step 6: Doc sync**

In `README.md` endpoints table, add a row under the `POST /datasets` row:

```
| GET    | `/datasets`                   | List all uploaded datasets (newest first)                      |
```

In `CLAUDE.md`, in the `routes/datasets.py` code-layout line, extend it to mention the list route, e.g. append: `, GET /datasets (list all, newest first)`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/datasets.py backend/tests/test_datasets.py README.md CLAUDE.md
git commit -m "feat(datasets): add GET /datasets list endpoint (newest first)"
```

---

### Task 3: `listDatasets` API wrapper + `DatasetSidebar` component

**Files:**
- Modify: `frontend/src/api.ts`
- Create: `frontend/src/components/DatasetSidebar.tsx`
- Create: `frontend/src/components/DatasetSidebar.module.css`
- Test: `frontend/src/components/DatasetSidebar.test.tsx`

**Interfaces:**
- Consumes: `GET /datasets` (Task 2); existing `createChat(datasetIds: string[]): Promise<ChatOut>`; `DatasetOut` type; `Button`, `Skeleton` from `../ui`.
- Produces: `listDatasets(): Promise<DatasetOut[]>`; default-exported `DatasetSidebar` component (no props).

- [ ] **Step 1: Add the API wrapper**

In `frontend/src/api.ts`, after `getDataset`:

```ts
export async function listDatasets(): Promise<DatasetOut[]> {
  const res = await fetch(`${API_BASE}/datasets`);
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<DatasetOut[]>;
}
```

- [ ] **Step 2: Write the failing component test**

Create `frontend/src/components/DatasetSidebar.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import DatasetSidebar from "./DatasetSidebar";
import * as api from "../api";

const navigateMock = vi.fn();
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => navigateMock };
});

beforeEach(() => {
  vi.restoreAllMocks();
  navigateMock.mockReset();
});

function renderSidebar() {
  render(
    <MemoryRouter>
      <DatasetSidebar />
    </MemoryRouter>,
  );
}

test("lists datasets returned by the API", async () => {
  vi.spyOn(api, "listDatasets").mockResolvedValue([
    { id: "d1", name: "sales.csv", n_rows: 10, n_cols: 3 },
    { id: "d2", name: "people.csv", n_rows: 5, n_cols: 2 },
  ]);
  renderSidebar();
  expect(await screen.findByText("sales.csv")).toBeInTheDocument();
  expect(screen.getByText("people.csv")).toBeInTheDocument();
});

test("clicking a dataset starts a chat over just that dataset and navigates", async () => {
  vi.spyOn(api, "listDatasets").mockResolvedValue([
    { id: "d1", name: "sales.csv", n_rows: 10, n_cols: 3 },
  ]);
  vi.spyOn(api, "createChat").mockResolvedValue({
    id: "chatA", datasets: [{ id: "d1", name: "sales.csv" }],
  });
  renderSidebar();
  await userEvent.click(await screen.findByRole("button", { name: /sales\.csv/ }));
  expect(api.createChat).toHaveBeenCalledWith(["d1"]);
  expect(navigateMock).toHaveBeenCalledWith("/c/chatA");
});

test("multi-select shows a footer action and starts one chat over all picked datasets", async () => {
  vi.spyOn(api, "listDatasets").mockResolvedValue([
    { id: "d1", name: "sales.csv", n_rows: 10, n_cols: 3 },
    { id: "d2", name: "people.csv", n_rows: 5, n_cols: 2 },
  ]);
  vi.spyOn(api, "createChat").mockResolvedValue({
    id: "chatB",
    datasets: [{ id: "d1", name: "sales.csv" }, { id: "d2", name: "people.csv" }],
  });
  renderSidebar();
  await userEvent.click(await screen.findByRole("checkbox", { name: "Select sales.csv" }));
  await userEvent.click(screen.getByRole("checkbox", { name: "Select people.csv" }));
  // With a selection active, a bare row click must NOT start a single chat.
  await userEvent.click(screen.getByRole("button", { name: /Start chat with 2 datasets/ }));
  expect(api.createChat).toHaveBeenCalledWith(["d1", "d2"]);
  expect(navigateMock).toHaveBeenCalledWith("/c/chatB");
});

test("shows an empty state when there are no datasets", async () => {
  vi.spyOn(api, "listDatasets").mockResolvedValue([]);
  renderSidebar();
  expect(await screen.findByText(/No datasets yet/)).toBeInTheDocument();
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && npm test -- DatasetSidebar`
Expected: FAIL — `DatasetSidebar` does not exist yet.

- [ ] **Step 4: Implement the component**

Create `frontend/src/components/DatasetSidebar.tsx`:

```tsx
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { createChat, listDatasets } from "../api";
import type { DatasetOut } from "../types";
import { Button, Skeleton } from "../ui";
import styles from "./DatasetSidebar.module.css";

export default function DatasetSidebar() {
  const [datasets, setDatasets] = useState<DatasetOut[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    let active = true;
    listDatasets()
      .then((ds) => {
        if (active) setDatasets(ds);
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : "Failed to load datasets");
      });
    return () => {
      active = false;
    };
  }, []);

  async function startChat(ids: string[]) {
    if (ids.length === 0 || starting) return;
    setStarting(true);
    try {
      const chat = await createChat(ids);
      navigate(`/c/${chat.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start chat");
      setStarting(false);
    }
  }

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function onRowClick(id: string) {
    // While a selection is active, a bare row click toggles that row rather
    // than starting a single-dataset chat, so the two paths don't fight.
    if (selected.size > 0) toggle(id);
    else void startChat([id]);
  }

  return (
    <nav aria-label="Datasets" className={styles.nav}>
      <div className={styles.header}>
        <Link to="/" className={styles.newUpload}>
          + New upload
        </Link>
      </div>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      {datasets === null && !error && (
        <div className={styles.list}>
          <Skeleton count={4} />
        </div>
      )}
      {datasets !== null && datasets.length === 0 && (
        <p className={styles.empty}>
          No datasets yet — <Link to="/">upload one</Link>.
        </p>
      )}
      {datasets !== null && datasets.length > 0 && (
        <ul className={styles.list}>
          {datasets.map((d) => (
            <li key={d.id} className={styles.row} data-selected={selected.has(d.id)}>
              <input
                type="checkbox"
                className={styles.check}
                checked={selected.has(d.id)}
                onChange={() => toggle(d.id)}
                aria-label={`Select ${d.name}`}
              />
              <button
                type="button"
                className={styles.rowButton}
                onClick={() => onRowClick(d.id)}
              >
                <span className={styles.name}>{d.name}</span>
                <span className={styles.meta}>
                  {d.n_rows} × {d.n_cols}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {selected.size > 0 && (
        <div className={styles.footer}>
          <Button size="sm" loading={starting} onClick={() => startChat([...selected])}>
            Start chat with {selected.size} dataset{selected.size === 1 ? "" : "s"}
          </Button>
        </div>
      )}
    </nav>
  );
}
```

- [ ] **Step 5: Add the styles**

Create `frontend/src/components/DatasetSidebar.module.css`. The checkbox stays in the DOM (keyboard-focusable) but is visually revealed on row hover, focus, or when selected:

```css
.nav {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: var(--space-2);
}
.header {
  padding: var(--space-2) var(--space-3);
}
.newUpload {
  color: var(--accent-text);
  font-size: var(--text-sm);
  font-weight: var(--weight-bold);
  text-decoration: none;
}
.list {
  list-style: none;
  margin: 0;
  padding: 0 var(--space-2);
  overflow-y: auto;
  flex: 1;
}
.row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  border-radius: var(--radius-md);
  padding: 0 var(--space-2);
}
.row:hover {
  background: color-mix(in srgb, var(--muted) 12%, transparent);
}
.row[data-selected="true"] {
  background: color-mix(in srgb, var(--accent) 14%, transparent);
}
.check {
  opacity: 0;
  flex: none;
}
.row:hover .check,
.check:focus-visible,
.row[data-selected="true"] .check {
  opacity: 1;
}
.rowButton {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  flex: 1;
  min-width: 0;
  background: none;
  border: none;
  padding: var(--space-2) 0;
  cursor: pointer;
  text-align: left;
  color: var(--ink);
}
.name {
  font-size: var(--text-sm);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}
.meta {
  font-size: var(--text-xs);
  color: var(--muted);
}
.empty,
.error {
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-sm);
  color: var(--muted);
}
.footer {
  padding: var(--space-3);
  border-top: 1px solid var(--line);
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd frontend && npm test -- DatasetSidebar`
Expected: all four tests pass.

- [ ] **Step 7: Type-check**

Run: `cd frontend && npm run type-check`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api.ts frontend/src/components/DatasetSidebar.tsx \
  frontend/src/components/DatasetSidebar.module.css \
  frontend/src/components/DatasetSidebar.test.tsx
git commit -m "feat(sidebar): DatasetSidebar with click-to-chat and multi-select"
```

---

### Task 4: Two-column collapsible `AppShell` rendering the sidebar

**Files:**
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/components/AppShell.module.css`
- Modify: `frontend/src/components/AppShell.test.tsx`
- Modify: `frontend/src/pages/UploadPage.test.tsx`, `frontend/src/pages/ChatPage.test.tsx` (mock `listDatasets`)
- Docs: `README.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: `DatasetSidebar` (Task 3); `IconButton` (prop is `label: string`), `ThemeToggle` from `../ui`.
- Produces: `AppShell` unchanged public props (`children`, `topbarRight?`, `width?`) plus an internal collapsible sidebar persisted to `localStorage["wp-sidebar"]`.

- [ ] **Step 1: Update the existing AppShell test first (it will fail)**

`AppShell` will now render `DatasetSidebar`, which uses the router and fetches. Update `frontend/src/components/AppShell.test.tsx` to provide a router and mock the fetch, and add a collapse assertion:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "../theme";
import AppShell from "./AppShell";
import * as api from "../api";

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  vi.spyOn(api, "listDatasets").mockResolvedValue([]);
});

function renderShell(ui: React.ReactNode, right?: React.ReactNode) {
  render(
    <ThemeProvider>
      <MemoryRouter>
        <AppShell topbarRight={right}>{ui}</AppShell>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

test("renders the brand, the theme toggle, a right slot, and its children", () => {
  renderShell(<p>page body</p>, <span>chips</span>);
  expect(screen.getByText("CSV Analysis")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /theme/i })).toBeInTheDocument();
  expect(screen.getByText("chips")).toBeInTheDocument();
  expect(screen.getByText("page body")).toBeInTheDocument();
});

test("exposes the width variant on its main region", () => {
  render(
    <ThemeProvider>
      <MemoryRouter>
        <AppShell width="upload">x</AppShell>
      </MemoryRouter>
    </ThemeProvider>,
  );
  expect(screen.getByRole("main")).toHaveAttribute("data-width", "upload");
});

test("collapsing hides the datasets nav and persists to localStorage", async () => {
  renderShell(<p>body</p>);
  expect(screen.getByRole("navigation", { name: "Datasets" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /collapse sidebar/i }));
  expect(screen.queryByRole("navigation", { name: "Datasets" })).not.toBeInTheDocument();
  expect(localStorage.getItem("wp-sidebar")).toBe("collapsed");
});
```

- [ ] **Step 2: Run to verify the collapse test fails**

Run: `cd frontend && npm test -- AppShell`
Expected: FAIL — no collapse button / sidebar wiring yet.

- [ ] **Step 3: Implement the two-column collapsible shell**

Replace `frontend/src/components/AppShell.tsx`:

```tsx
import { useState, type ReactNode } from "react";
import { IconButton, ThemeToggle } from "../ui";
import DatasetSidebar from "./DatasetSidebar";
import styles from "./AppShell.module.css";

const SIDEBAR_KEY = "wp-sidebar";

interface AppShellProps {
  children: ReactNode;
  topbarRight?: ReactNode;
  width?: "chat" | "upload";
}

function initialCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_KEY) === "collapsed";
  } catch {
    return false;
  }
}

export default function AppShell({ children, topbarRight, width = "chat" }: AppShellProps) {
  const [collapsed, setCollapsed] = useState(initialCollapsed);

  function toggle() {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(SIDEBAR_KEY, next ? "collapsed" : "expanded");
      } catch {
        // ignore persistence failures (private mode, etc.)
      }
      return next;
    });
  }

  return (
    <div className={styles.shell} data-collapsed={collapsed}>
      <header className={styles.topbar}>
        <div className={styles.left}>
          <IconButton
            label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-expanded={!collapsed}
            onClick={toggle}
          >
            ☰
          </IconButton>
          <span className={styles.brand}>CSV Analysis</span>
        </div>
        <div className={styles.right}>
          {topbarRight}
          <ThemeToggle />
        </div>
      </header>
      <div className={styles.body}>
        {!collapsed && (
          <aside className={styles.sidebar}>
            <DatasetSidebar />
          </aside>
        )}
        <main data-width={width} className={styles.main}>
          {children}
        </main>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Update the shell styles**

Replace `frontend/src/components/AppShell.module.css`:

```css
.shell { min-height: 100vh; background: var(--bg); }
.topbar {
  position: sticky; top: 0; z-index: 10;
  display: flex; align-items: center; justify-content: space-between; gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--surface); border-bottom: 1px solid var(--line);
}
.left { display: flex; align-items: center; gap: var(--space-3); }
.brand { font-size: var(--text-lg); font-weight: var(--weight-bold); color: var(--ink); letter-spacing: -0.01em; }
.right { display: flex; align-items: center; gap: var(--space-3); }
.body { display: flex; align-items: stretch; }
.sidebar {
  flex: none;
  width: 260px;
  border-right: 1px solid var(--line);
  background: var(--surface);
  position: sticky;
  top: 57px; /* below the sticky topbar */
  align-self: flex-start;
  height: calc(100vh - 57px);
}
.main { flex: 1; min-width: 0; margin: 0 auto; padding: var(--space-6) var(--space-4); }
.main[data-width="chat"] { max-width: 820px; }
.main[data-width="upload"] { max-width: 520px; }

@media (max-width: 768px) {
  .sidebar {
    position: fixed;
    left: 0;
    top: 57px;
    z-index: 20;
    box-shadow: var(--shadow-md, 0 8px 24px rgba(0, 0, 0, 0.2));
  }
}
```

- [ ] **Step 5: Run AppShell tests**

Run: `cd frontend && npm test -- AppShell`
Expected: all three tests pass.

- [ ] **Step 6: Mock `listDatasets` in the page tests**

`UploadPage` and `ChatPage` render through `AppShell`, which now fetches datasets. In both `frontend/src/pages/UploadPage.test.tsx` and `frontend/src/pages/ChatPage.test.tsx`, add to the existing `beforeEach` (after `vi.restoreAllMocks()`):

```tsx
vi.spyOn(api, "listDatasets").mockResolvedValue([]);
```

(`UploadPage.test.tsx` already imports `* as api`; if `ChatPage.test.tsx` does not, add `import * as api from "../api";`.)

- [ ] **Step 7: Full frontend gate**

Run: `cd frontend && npm test && npm run build`
Expected: entire suite green, `tsc` clean, build succeeds.

- [ ] **Step 8: Doc sync**

In `README.md` feature list (the tokenized-component bullet), append a sentence: `A collapsible left sidebar lists previously uploaded datasets — click one to start a chat, or multi-select several.` In `CLAUDE.md` code-layout `components/` line, add `AppShell (two-column collapsible shell) and DatasetSidebar (dataset nav)`.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/AppShell.tsx frontend/src/components/AppShell.module.css \
  frontend/src/components/AppShell.test.tsx frontend/src/pages/UploadPage.test.tsx \
  frontend/src/pages/ChatPage.test.tsx README.md CLAUDE.md
git commit -m "feat(sidebar): two-column collapsible AppShell rendering DatasetSidebar"
```

---

### Task 5: Restyle + refine `PassTrace`

**Files:**
- Modify: `frontend/src/components/PassTrace.tsx`
- Create: `frontend/src/components/PassTrace.module.css`
- Modify: `frontend/src/components/PassTrace.test.tsx`
- Modify: `frontend/src/styles/global.css` (remove now-dead `.pass-trace`/`.trace-*` rules if present)
- Docs: `README.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: `MessageTraceOut`, `PassTraceOut`, `AnalystPassOut`, `JudgePassOut` from `../types` (already present post-merge — do **not** redefine them); `ChartList` from `./ChartList`; `Badge` from `../ui`.
- Produces: `PassTrace` with the same prop `{ trace?: MessageTraceOut | null }`.

**Type reference (already in `frontend/src/types.ts` from main — for the implementer's context only):**
- `PassTraceOut { pass_no: number; analyst: AnalystPassOut; charts: string[]; stats: Record<string,unknown>[]; errors: string[]; judge: JudgePassOut; revision_instruction: string }`
- `AnalystPassOut { model; tokens_in; tokens_out; latency_ms; cost_usd; interpretation: string }`
- `JudgePassOut { model; tokens_in; tokens_out; latency_ms; cost_usd; score: number | null; feedback: string; gaps: string[] }`

- [ ] **Step 1: Rewrite the test for the refined structure**

Replace `frontend/src/components/PassTrace.test.tsx`. Assert on visible text / roles / accessible names only:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PassTrace from "./PassTrace";
import type { MessageTraceOut } from "../types";

function trace(): MessageTraceOut {
  return {
    passes: [
      {
        pass_no: 1,
        analyst: {
          model: "claude-sonnet-5", tokens_in: 100, tokens_out: 50,
          latency_ms: 1200, cost_usd: 0.0021, interpretation: "Ages skew young.",
        },
        charts: [],
        stats: [],
        errors: [],
        judge: {
          model: "claude-sonnet-5", tokens_in: 80, tokens_out: 20,
          latency_ms: 600, cost_usd: 0.0009, score: 62,
          feedback: "Add the median.", gaps: ["median missing"],
        },
        revision_instruction: "Include the median.",
      },
      {
        pass_no: 2,
        analyst: {
          model: "claude-sonnet-5", tokens_in: 120, tokens_out: 60,
          latency_ms: 1300, cost_usd: 0.0024, interpretation: "Median age is 28.",
        },
        charts: [],
        stats: [],
        errors: [],
        judge: {
          model: "claude-sonnet-5", tokens_in: 70, tokens_out: 10,
          latency_ms: 500, cost_usd: 0.0007, score: 88,
          feedback: "Good.", gaps: [],
        },
        revision_instruction: "",
      },
    ],
  };
}

test("renders nothing when there is no trace", () => {
  const { container } = render(<PassTrace trace={null} />);
  expect(container).toBeEmptyDOMElement();
});

test("summarizes the number of passes and shows each pass's judge score", async () => {
  render(<PassTrace trace={trace()} />);
  await userEvent.click(screen.getByText(/Loop trace \(2 passes\)/));
  expect(screen.getByText(/Pass 1/)).toBeInTheDocument();
  expect(screen.getByText(/62/)).toBeInTheDocument();
  expect(screen.getByText(/Pass 2/)).toBeInTheDocument();
  expect(screen.getByText(/88/)).toBeInTheDocument();
});

test("reveals analyst interpretation, judge feedback, and the demoted cost meta when a pass is expanded", async () => {
  render(<PassTrace trace={trace()} />);
  await userEvent.click(screen.getByText(/Loop trace \(2 passes\)/));
  await userEvent.click(screen.getByRole("button", { name: /Pass 1/ }));
  expect(screen.getByText("Ages skew young.")).toBeInTheDocument();
  expect(screen.getByText(/Add the median\./)).toBeInTheDocument();
  // Demoted meta line still present (tokens / latency / cost).
  expect(screen.getByText(/1200 ms/)).toBeInTheDocument();
});

test("shows a failed-judge badge when the score is null", async () => {
  const t = trace();
  t.passes[0].judge.score = null;
  render(<PassTrace trace={t} />);
  await userEvent.click(screen.getByText(/Loop trace/));
  expect(screen.getByText(/judge failed/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npm test -- PassTrace`
Expected: FAIL — old component has no per-pass expand button / badge text layout.

- [ ] **Step 3: Rewrite the component**

Replace `frontend/src/components/PassTrace.tsx`. Each pass is its own `<details>` with a `<summary>` acting as a button (RTL matches `<summary>` with `role="button"` for the pass header). The token/cost/latency line is demoted to a muted footer:

```tsx
import type { AnalystPassOut, JudgePassOut, MessageTraceOut, PassTraceOut } from "../types";
import { Badge } from "../ui";
import ChartList from "./ChartList";
import styles from "./PassTrace.module.css";

function costLabel(usd: number): string {
  return `$${usd.toFixed(4)}`;
}

function metaLine(role: string, p: AnalystPassOut | JudgePassOut): string {
  return `${role}: ${p.model} · ${p.tokens_in} in / ${p.tokens_out} out · ${p.latency_ms} ms · ${costLabel(p.cost_usd)}`;
}

function scoreBadge(score: number | null) {
  if (score === null) return <Badge tone="danger">judge failed</Badge>;
  // Display heuristic only — not the loop's acceptance decision.
  const tone = score >= 80 ? "accent" : "neutral";
  return <Badge tone={tone}>judge {score}/100</Badge>;
}

function PassBlock({ pass }: { pass: PassTraceOut }) {
  const { analyst, judge } = pass;
  return (
    <details className={styles.pass}>
      <summary className={styles.passHeader}>
        <span className={styles.passTitle}>Pass {pass.pass_no}</span>
        {scoreBadge(judge.score)}
      </summary>
      <div className={styles.passBody}>
        {analyst.interpretation && <p className={styles.interp}>{analyst.interpretation}</p>}
        <ChartList charts={pass.charts} />
        {pass.errors.length > 0 && (
          <ul className={styles.errors}>
            {pass.errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        )}
        {judge.feedback && <p className={styles.feedback}>Feedback: {judge.feedback}</p>}
        {judge.gaps.length > 0 && (
          <ul className={styles.gaps}>
            {judge.gaps.map((g, i) => (
              <li key={i}>{g}</li>
            ))}
          </ul>
        )}
        {pass.revision_instruction && (
          <p className={styles.revision}>Revision fed to next pass: {pass.revision_instruction}</p>
        )}
        <p className={styles.meta}>{metaLine("Analyst", analyst)}</p>
        <p className={styles.meta}>{metaLine("Judge", judge)}</p>
      </div>
    </details>
  );
}

interface Props {
  trace?: MessageTraceOut | null;
}

export default function PassTrace({ trace }: Props) {
  if (!trace || trace.passes.length === 0) return null;
  const n = trace.passes.length;
  return (
    <details className={styles.trace}>
      <summary className={styles.traceHeader}>
        Loop trace ({n} pass{n === 1 ? "" : "es"})
      </summary>
      <div className={styles.passes}>
        {trace.passes.map((p) => (
          <PassBlock key={p.pass_no} pass={p} />
        ))}
      </div>
    </details>
  );
}
```

- [ ] **Step 4: Add the styles**

Create `frontend/src/components/PassTrace.module.css`:

```css
.trace { margin-top: var(--space-3); }
.traceHeader {
  cursor: pointer;
  color: var(--accent-text);
  font-size: var(--text-sm);
  font-weight: var(--weight-bold);
}
.passes { display: flex; flex-direction: column; gap: var(--space-2); margin-top: var(--space-2); }
.pass {
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--surface);
}
.passHeader {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  cursor: pointer;
  padding: var(--space-2) var(--space-3);
}
.passTitle { font-size: var(--text-sm); font-weight: var(--weight-bold); color: var(--ink); }
.passBody { padding: 0 var(--space-3) var(--space-3); display: flex; flex-direction: column; gap: var(--space-2); }
.interp { color: var(--ink); }
.feedback { color: var(--ink); }
.errors, .gaps { margin: 0; padding-left: var(--space-4); color: var(--muted); font-size: var(--text-sm); }
.revision { color: var(--muted); font-size: var(--text-sm); font-style: italic; }
.meta { color: var(--muted); font-size: var(--text-xs); margin: 0; }
```

- [ ] **Step 5: Remove dead global trace rules**

Search `frontend/src/styles/global.css` for `.pass-trace`, `.trace-meta`, `.trace-interp`, `.trace-errors`, `.trace-feedback`, `.trace-gaps`, `.trace-revision`. Delete any such rules (the styling now lives in the CSS module). If none exist, no change.

Run: `grep -n "pass-trace\|trace-" frontend/src/styles/global.css` — expect no matches after this step.

- [ ] **Step 6: Run to verify it passes**

Run: `cd frontend && npm test -- PassTrace`
Expected: all tests pass.

- [ ] **Step 7: Full frontend gate**

Run: `cd frontend && npm test && npm run build`
Expected: entire suite green, `tsc` clean, build succeeds.

- [ ] **Step 8: Doc sync**

In `README.md`, adjust the trace mention (added by main) to note it now uses the tokenized UI with per-pass collapse and a color-coded judge-score badge. In `CLAUDE.md`, note in the `components/` line that `PassTrace` renders the loop trace with tokenized styling (system prompt still excluded).

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/PassTrace.tsx frontend/src/components/PassTrace.module.css \
  frontend/src/components/PassTrace.test.tsx frontend/src/styles/global.css README.md CLAUDE.md
git commit -m "feat(trace): restyle + refine PassTrace with tokenized per-pass UI"
```

---

## Self-Review

**Spec coverage:**
- Design A (merge, green baseline) → Task 1.
- Design B (`GET /datasets`, newest first, `content_hash` hidden) → Task 2.
- Design C (sidebar: list, click-to-chat, hover multi-select, collapse+persist, a11y) → Tasks 3 (component) + 4 (shell/collapse/persist).
- Design D (trace restyle + per-pass collapse + Badge score + demoted meta + system prompt excluded) → Task 5.
- Design E (tests + doc sync) → tests in every task; doc sync in Tasks 2, 4, 5.

**Placeholder scan:** No TBD/TODO; every code step has real code and real paths; tests carry real assertions.

**Type consistency:** `listDatasets(): Promise<DatasetOut[]>` produced in Task 3, consumed in Task 4's mocks. `DatasetOut` = `{id,name,n_rows,n_cols}` used consistently. `createChat(string[])` reused unchanged. `IconButton` uses `label` prop (verified). `Badge` tones limited to `neutral|accent|danger` (verified) — Task 5 uses only those. Trace types imported from `types.ts`, not redefined. `Skeleton` uses `count`; `Button` uses `size`/`loading` (verified).

**Known integration risk captured:** Task 4 explicitly updates `AppShell.test.tsx` and mocks `listDatasets` in `UploadPage.test.tsx` / `ChatPage.test.tsx`, since `AppShell` now fetches.
