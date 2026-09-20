# Project 1 Week 2 Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the React/Vite/TypeScript single-page UI for the CSV Analysis Assistant core flow (upload → dataset page → ask → charts + prose + collapsible stats + error warnings), plus the one backend change it requires (CORS).

**Architecture:** A new `frontend/` directory sibling to `backend/`, built with Vite + React + TypeScript, routed with `react-router-dom` (`/` upload, `/d/:id` dataset). A thin typed `fetch` client (`api.ts`) maps the four existing backend endpoints; React hooks hold state (no data/state library). The backend gains `CORSMiddleware`; dev traffic uses a Vite `/api` proxy so there is no CORS in development.

**Tech Stack:** React 18, react-router-dom 6, Vite 5, TypeScript 5 (strict), Vitest 2 + React Testing Library + jsdom. Backend: FastAPI (existing), one middleware addition.

## Global Constraints

- All frontend code lives under `frontend/`; run frontend commands from that directory (`cd frontend && ...`).
- TypeScript `strict: true`. No design system, no component library, no state library (Redux/Zustand), no data-fetching library (React Query), no OpenAPI codegen.
- API base URL comes from `import.meta.env.VITE_API_BASE`, defaulting to `/api`.
- Charts are base64 PNG payloads rendered as `<img src={`data:image/png;base64,${c}`} />`.
- The per-message React component is named **`ChatTurn`** (not `ChatMessage`, to avoid confusion with the backend model).
- Tests use Vitest + React Testing Library with `fetch`/api mocked — never a live backend. Frontend tests are separate from the backend `make test` gate.
- Consumed backend contract (unchanged): `POST /datasets` (multipart `file`) → `DatasetOut {id,name,n_rows,n_cols}`; `GET /datasets/{id}` → `DatasetOut`; `POST /datasets/{id}/chat {question}` → `ChatMessageOut`; `GET /datasets/{id}/chat` → `{messages: ChatMessageOut[]}`. `ChatMessageOut = {id, role, content, charts: string[], stats: Record<string,unknown>[], errors: string[]}`. Unknown id → `404`.
- Do not change the backend `anthropic_model` default (`claude-sonnet-5`) or any existing route/schema.

---

### Task 1: Scaffold the Vite + React + TypeScript + Vitest project

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/index.html`
- Create: `frontend/.gitignore`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/index.css`
- Create: `frontend/src/vite-env.d.ts`
- Create: `frontend/src/setupTests.ts`
- Test: `frontend/src/App.test.tsx`

**Interfaces:**
- Produces: `App` default-exported React component rendering `<Routes>` with `/` and `/d/:id`. In this task both routes render placeholder text; Task 8 swaps in the real pages.

- [ ] **Step 1: Create `frontend/package.json`**

```json
{
  "name": "csv-analysis-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest",
    "type-check": "tsc --noEmit"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.2"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.5.0",
    "@testing-library/react": "^16.0.1",
    "@testing-library/user-event": "^14.5.2",
    "@types/react": "^18.3.11",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.2",
    "jsdom": "^25.0.1",
    "typescript": "^5.6.3",
    "vite": "^5.4.9",
    "vitest": "^2.1.3"
  }
}
```

- [ ] **Step 2: Create `frontend/vite.config.ts`** (dev proxy + Vitest config in one file)

```ts
/// <reference types="vitest" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/setupTests.ts",
    css: false,
  },
});
```

- [ ] **Step 3: Create `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 4: Create `frontend/tsconfig.node.json`**

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 5: Create `frontend/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>CSV Analysis Assistant</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 6: Create `frontend/.gitignore`**

```gitignore
node_modules
dist
*.local
```

- [ ] **Step 7: Create `frontend/src/vite-env.d.ts`** (typed env var)

```ts
/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
```

- [ ] **Step 8: Create `frontend/src/index.css`** (minimal base layout — a global reset alongside per-component CSS Modules)

```css
:root {
  font-family: system-ui, -apple-system, sans-serif;
  line-height: 1.5;
  color: #1a1a1a;
  background: #fafafa;
}

body {
  margin: 0;
}

main {
  max-width: 900px;
  margin: 0 auto;
  padding: 1.5rem;
}

img {
  max-width: 100%;
  height: auto;
}
```

- [ ] **Step 9: Create `frontend/src/setupTests.ts`**

```ts
import "@testing-library/jest-dom";
```

- [ ] **Step 10: Create `frontend/src/main.tsx`**

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
```

- [ ] **Step 11: Create `frontend/src/App.tsx`** (placeholder routes for now)

```tsx
import { Routes, Route } from "react-router-dom";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<p>Upload placeholder</p>} />
      <Route path="/d/:id" element={<p>Dataset placeholder</p>} />
    </Routes>
  );
}
```

- [ ] **Step 12: Write the smoke test `frontend/src/App.test.tsx`**

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";

test("renders the upload route at /", () => {
  render(
    <MemoryRouter initialEntries={["/"]}>
      <App />
    </MemoryRouter>,
  );
  expect(screen.getByText("Upload placeholder")).toBeInTheDocument();
});
```

- [ ] **Step 13: Install dependencies**

Run: `cd frontend && npm install`
Expected: `node_modules/` created, `package-lock.json` written, no error exit.

- [ ] **Step 14: Run the test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS — 1 test passing.

- [ ] **Step 15: Verify the production build compiles**

Run: `cd frontend && npm run build`
Expected: `tsc` reports no errors and Vite writes `dist/`.

- [ ] **Step 16: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts \
  frontend/tsconfig.json frontend/tsconfig.node.json frontend/index.html \
  frontend/.gitignore frontend/src/main.tsx frontend/src/App.tsx \
  frontend/src/index.css frontend/src/vite-env.d.ts frontend/src/setupTests.ts \
  frontend/src/App.test.tsx
git commit -m "feat(frontend): scaffold Vite + React + TS + Vitest project"
```

---

### Task 2: Add backend CORS middleware

**Files:**
- Modify: `backend/app/config.py` (add `cors_allow_origins`)
- Modify: `backend/app/main.py` (add `CORSMiddleware`)
- Test: `backend/tests/test_cors.py`

**Interfaces:**
- Consumes: existing `create_app()` factory and the `client` pytest fixture from `backend/tests/conftest.py`.
- Produces: `Settings.cors_allow_origins: list[str]` (default `["http://localhost:5173"]`); `create_app()` echoes `Access-Control-Allow-Origin` for allowed origins.

- [ ] **Step 1: Write the failing test `backend/tests/test_cors.py`**

```python
def test_cors_allows_configured_origin(client):
    resp = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_omits_header_for_unknown_origin(client):
    resp = client.get("/health", headers={"Origin": "http://evil.example"})
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && poetry run pytest tests/test_cors.py -v`
Expected: FAIL — `test_cors_allows_configured_origin` KeyErrors on the missing `access-control-allow-origin` header.

- [ ] **Step 3: Add the setting in `backend/app/config.py`**

Add this field to the `Settings` class, immediately after the `max_rows` field (line 9):

```python
    # Frontend CORS (prod only; dev uses the Vite /api proxy). Override via .env as a
    # JSON list, e.g. CORS_ALLOW_ORIGINS='["https://app.example.com"]'.
    cors_allow_origins: list[str] = ["http://localhost:5173"]
```

- [ ] **Step 4: Register the middleware in `backend/app/main.py`**

Add the import at the top (after `from fastapi import FastAPI`):

```python
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
```

Then, inside `create_app()`, immediately after `app = FastAPI(title="CSV Analysis Assistant", lifespan=lifespan)`:

```python
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && poetry run pytest tests/test_cors.py -v`
Expected: PASS — 2 tests passing.

- [ ] **Step 6: Run the full backend suite and lint to confirm no regression**

Run: `make test && make lint`
Expected: all tests pass; ruff reports no errors.

- [ ] **Step 7: Commit**

```bash
git add backend/app/config.py backend/app/main.py backend/tests/test_cors.py
git commit -m "feat(backend): add configurable CORS middleware for the frontend"
```

---

### Task 3: Types and typed API client

**Files:**
- Create: `frontend/src/types.ts`
- Create: `frontend/src/api.ts`
- Test: `frontend/src/api.test.ts`

**Interfaces:**
- Produces:
  - `types.ts`: `DatasetOut {id:string; name:string; n_rows:number; n_cols:number}`, `ChatMessageOut {id:string; role:string; content:string; charts:string[]; stats:Record<string,unknown>[]; errors:string[]}`, `ChatHistoryOut {messages: ChatMessageOut[]}`.
  - `api.ts`: `class ApiError extends Error { status: number }`; `uploadDataset(file: File): Promise<DatasetOut>`; `getDataset(id: string): Promise<DatasetOut>`; `getChatHistory(id: string): Promise<ChatHistoryOut>`; `postChat(id: string, question: string): Promise<ChatMessageOut>`.

- [ ] **Step 1: Create `frontend/src/types.ts`**

```ts
export interface DatasetOut {
  id: string;
  name: string;
  n_rows: number;
  n_cols: number;
}

export interface ChatMessageOut {
  id: string;
  role: string;
  content: string;
  charts: string[];
  stats: Record<string, unknown>[];
  errors: string[];
}

export interface ChatHistoryOut {
  messages: ChatMessageOut[];
}
```

- [ ] **Step 2: Write the failing test `frontend/src/api.test.ts`**

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { uploadDataset, getDataset, getChatHistory, postChat, ApiError } from "./api";

function mockFetch(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    json: async () => body,
  } as Response);
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("api client", () => {
  it("uploadDataset posts multipart FormData to /api/datasets", async () => {
    const fetchMock = mockFetch(200, { id: "abc", name: "s.csv", n_rows: 3, n_cols: 2 });
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["a,b\n1,2\n"], "s.csv", { type: "text/csv" });

    const result = await uploadDataset(file);

    expect(result.id).toBe("abc");
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/datasets");
    expect((opts as RequestInit).method).toBe("POST");
    expect((opts as RequestInit).body).toBeInstanceOf(FormData);
  });

  it("getDataset GETs /api/datasets/{id}", async () => {
    const fetchMock = mockFetch(200, { id: "abc", name: "s.csv", n_rows: 3, n_cols: 2 });
    vi.stubGlobal("fetch", fetchMock);

    const result = await getDataset("abc");

    expect(result.name).toBe("s.csv");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/datasets/abc");
  });

  it("getChatHistory returns the messages array", async () => {
    const fetchMock = mockFetch(200, { messages: [] });
    vi.stubGlobal("fetch", fetchMock);

    const result = await getChatHistory("abc");

    expect(result.messages).toEqual([]);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/datasets/abc/chat");
  });

  it("postChat sends a JSON question body", async () => {
    const fetchMock = mockFetch(200, {
      id: "m1", role: "assistant", content: "hi", charts: [], stats: [], errors: [],
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await postChat("abc", "why?");

    expect(result.role).toBe("assistant");
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/datasets/abc/chat");
    expect((opts as RequestInit).method).toBe("POST");
    expect(JSON.parse((opts as RequestInit).body as string)).toEqual({ question: "why?" });
  });

  it("maps a non-2xx response to a thrown ApiError with detail", async () => {
    const fetchMock = mockFetch(404, { detail: "Dataset not found" });
    vi.stubGlobal("fetch", fetchMock);

    await expect(getDataset("nope")).rejects.toBeInstanceOf(ApiError);
    vi.stubGlobal("fetch", mockFetch(404, { detail: "Dataset not found" }));
    await expect(getDataset("nope")).rejects.toMatchObject({ status: 404, message: "Dataset not found" });
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/api.test.ts`
Expected: FAIL — cannot resolve `./api`.

- [ ] **Step 4: Create `frontend/src/api.ts`**

```ts
import type { ChatHistoryOut, ChatMessageOut, DatasetOut } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function failFrom(res: Response): Promise<never> {
  let detail = res.statusText || `HTTP ${res.status}`;
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") detail = body.detail;
  } catch {
    // Non-JSON error body — keep the status-based message.
  }
  throw new ApiError(res.status, detail);
}

export async function uploadDataset(file: File): Promise<DatasetOut> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/datasets`, { method: "POST", body: form });
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<DatasetOut>;
}

export async function getDataset(id: string): Promise<DatasetOut> {
  const res = await fetch(`${API_BASE}/datasets/${id}`);
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<DatasetOut>;
}

export async function getChatHistory(id: string): Promise<ChatHistoryOut> {
  const res = await fetch(`${API_BASE}/datasets/${id}/chat`);
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<ChatHistoryOut>;
}

export async function postChat(id: string, question: string): Promise<ChatMessageOut> {
  const res = await fetch(`${API_BASE}/datasets/${id}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<ChatMessageOut>;
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/api.test.ts`
Expected: PASS — 5 tests passing.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types.ts frontend/src/api.ts frontend/src/api.test.ts
git commit -m "feat(frontend): add typed API client and response types"
```

---

### Task 4: Message-display components (ChartList, StatsDetails, ErrorBanner, ChatTurn)

**Files:**
- Create: `frontend/src/components/ChartList.tsx`
- Create: `frontend/src/components/StatsDetails.tsx`
- Create: `frontend/src/components/ErrorBanner.tsx`
- Create: `frontend/src/components/ErrorBanner.module.css`
- Create: `frontend/src/components/ChatTurn.tsx`
- Test: `frontend/src/components/ChatTurn.test.tsx`

**Interfaces:**
- Consumes: `ChatMessageOut` from `../types`.
- Produces:
  - `ChartList({ charts: string[] })` — one `<img>` per chart, `null` when empty.
  - `StatsDetails({ stats: Record<string, unknown>[] })` — collapsed `<details>` with summary "Raw statistics", `null` when empty.
  - `ErrorBanner({ message: string })` — a `<p role="alert">`.
  - `ChatTurn({ message: ChatMessageOut })` — composes the above plus role label and prose.

- [ ] **Step 1: Create `frontend/src/components/ChartList.tsx`**

```tsx
interface Props {
  charts: string[];
}

export default function ChartList({ charts }: Props) {
  if (charts.length === 0) return null;
  return (
    <div>
      {charts.map((c, i) => (
        <img key={i} src={`data:image/png;base64,${c}`} alt={`chart ${i + 1}`} />
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Create `frontend/src/components/StatsDetails.tsx`**

```tsx
interface Props {
  stats: Record<string, unknown>[];
}

export default function StatsDetails({ stats }: Props) {
  if (stats.length === 0) return null;
  return (
    <details>
      <summary>Raw statistics</summary>
      <pre>{JSON.stringify(stats, null, 2)}</pre>
    </details>
  );
}
```

- [ ] **Step 3: Create `frontend/src/components/ErrorBanner.module.css`**

```css
.banner {
  margin: 0.5rem 0;
  padding: 0.5rem 0.75rem;
  border: 1px solid #d9a300;
  border-radius: 4px;
  background: #fff8e1;
  color: #7a5b00;
}
```

- [ ] **Step 4: Create `frontend/src/components/ErrorBanner.tsx`**

```tsx
import styles from "./ErrorBanner.module.css";

interface Props {
  message: string;
}

export default function ErrorBanner({ message }: Props) {
  return (
    <p role="alert" className={styles.banner}>
      {message}
    </p>
  );
}
```

- [ ] **Step 5: Create `frontend/src/components/ChatTurn.tsx`**

```tsx
import type { ChatMessageOut } from "../types";
import ChartList from "./ChartList";
import StatsDetails from "./StatsDetails";
import ErrorBanner from "./ErrorBanner";

interface Props {
  message: ChatMessageOut;
}

export default function ChatTurn({ message }: Props) {
  return (
    <div>
      <span>{message.role}</span>
      {message.content && <p>{message.content}</p>}
      <ChartList charts={message.charts} />
      {message.errors.map((e, i) => (
        <ErrorBanner key={i} message={e} />
      ))}
      <StatsDetails stats={message.stats} />
    </div>
  );
}
```

- [ ] **Step 6: Write the failing test `frontend/src/components/ChatTurn.test.tsx`**

```tsx
import { render, screen } from "@testing-library/react";
import ChatTurn from "./ChatTurn";
import type { ChatMessageOut } from "../types";

const base: ChatMessageOut = {
  id: "m1",
  role: "assistant",
  content: "Here is the analysis.",
  charts: [],
  stats: [],
  errors: [],
};

test("renders prose and one img per chart", () => {
  render(<ChatTurn message={{ ...base, charts: ["AAAA", "BBBB"] }} />);
  expect(screen.getByText("Here is the analysis.")).toBeInTheDocument();
  const imgs = screen.getAllByRole("img");
  expect(imgs).toHaveLength(2);
  expect(imgs[0]).toHaveAttribute("src", "data:image/png;base64,AAAA");
});

test("keeps stats collapsed but present", () => {
  render(<ChatTurn message={{ ...base, stats: [{ mean: 1 }] }} />);
  const details = screen.getByText("Raw statistics").closest("details");
  expect(details).not.toBeNull();
  expect((details as HTMLDetailsElement).open).toBe(false);
});

test("renders a warning per error even when a chart rendered", () => {
  render(<ChatTurn message={{ ...base, charts: ["AAAA"], errors: ["bad column x"] }} />);
  expect(screen.getByRole("img")).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("bad column x");
});
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/components/ChatTurn.test.tsx`
Expected: PASS — 3 tests passing.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/ChartList.tsx frontend/src/components/StatsDetails.tsx \
  frontend/src/components/ErrorBanner.tsx frontend/src/components/ErrorBanner.module.css \
  frontend/src/components/ChatTurn.tsx frontend/src/components/ChatTurn.test.tsx
git commit -m "feat(frontend): add message-display components (ChatTurn + children)"
```

---

### Task 5: QuestionBox component

**Files:**
- Create: `frontend/src/components/QuestionBox.tsx`
- Test: `frontend/src/components/QuestionBox.test.tsx`

**Interfaces:**
- Produces: `QuestionBox({ onSubmit: (question: string) => void; pending: boolean })` — controlled textarea (`aria-label="Question"`) + submit button ("Ask" / "Asking…"). Trims input, ignores empty/whitespace, ignores submits while `pending`, clears on submit.

- [ ] **Step 1: Create `frontend/src/components/QuestionBox.tsx`**

```tsx
import { useState, type FormEvent } from "react";

interface Props {
  onSubmit: (question: string) => void;
  pending: boolean;
}

export default function QuestionBox({ onSubmit, pending }: Props) {
  const [value, setValue] = useState("");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || pending) return;
    onSubmit(trimmed);
    setValue("");
  }

  return (
    <form onSubmit={handleSubmit}>
      <textarea
        aria-label="Question"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        disabled={pending}
      />
      <button type="submit" disabled={pending || value.trim() === ""}>
        {pending ? "Asking…" : "Ask"}
      </button>
    </form>
  );
}
```

- [ ] **Step 2: Write the failing test `frontend/src/components/QuestionBox.test.tsx`**

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import QuestionBox from "./QuestionBox";

test("submits the trimmed question and clears the box", async () => {
  const onSubmit = vi.fn();
  render(<QuestionBox onSubmit={onSubmit} pending={false} />);

  const box = screen.getByLabelText("Question");
  await userEvent.type(box, "  why is x high?  ");
  await userEvent.click(screen.getByRole("button", { name: "Ask" }));

  expect(onSubmit).toHaveBeenCalledWith("why is x high?");
  expect(box).toHaveValue("");
});

test("disables the input and button while pending", () => {
  render(<QuestionBox onSubmit={vi.fn()} pending={true} />);
  expect(screen.getByLabelText("Question")).toBeDisabled();
  const button = screen.getByRole("button");
  expect(button).toBeDisabled();
  expect(button).toHaveTextContent("Asking…");
});
```

- [ ] **Step 3: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/components/QuestionBox.test.tsx`
Expected: PASS — 2 tests passing.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/QuestionBox.tsx frontend/src/components/QuestionBox.test.tsx
git commit -m "feat(frontend): add QuestionBox input component"
```

---

### Task 6: UploadPage

**Files:**
- Create: `frontend/src/pages/UploadPage.tsx`
- Test: `frontend/src/pages/UploadPage.test.tsx`

**Interfaces:**
- Consumes: `uploadDataset` from `../api`; `ErrorBanner` from `../components/ErrorBanner`; `useNavigate` from `react-router-dom`.
- Produces: `UploadPage` default export — file `<input aria-label="CSV file" accept=".csv">`, submit button ("Upload" / "Uploading…"), navigates to `/d/{id}` on success, shows an `ErrorBanner` on failure.

- [ ] **Step 1: Create `frontend/src/pages/UploadPage.tsx`**

```tsx
import { useState, type ChangeEvent, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { uploadDataset } from "../api";
import ErrorBanner from "../components/ErrorBanner";

export default function UploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    setFile(e.target.files?.[0] ?? null);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!file || pending) return;
    setPending(true);
    setError(null);
    try {
      const dataset = await uploadDataset(file);
      navigate(`/d/${dataset.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
      setPending(false);
    }
  }

  return (
    <main>
      <h1>CSV Analysis Assistant</h1>
      <p>Upload a CSV to start asking questions about it.</p>
      <form onSubmit={handleSubmit}>
        <input type="file" accept=".csv" aria-label="CSV file" onChange={handleFileChange} />
        <button type="submit" disabled={!file || pending}>
          {pending ? "Uploading…" : "Upload"}
        </button>
      </form>
      {error && <ErrorBanner message={error} />}
    </main>
  );
}
```

- [ ] **Step 2: Write the failing test `frontend/src/pages/UploadPage.test.tsx`**

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import UploadPage from "./UploadPage";
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

function renderPage() {
  render(
    <MemoryRouter>
      <UploadPage />
    </MemoryRouter>,
  );
}

test("uploads the chosen file and navigates to its dataset page", async () => {
  vi.spyOn(api, "uploadDataset").mockResolvedValue({
    id: "abc", name: "s.csv", n_rows: 3, n_cols: 2,
  });
  renderPage();
  const file = new File(["a,b\n1,2\n"], "s.csv", { type: "text/csv" });

  await userEvent.upload(screen.getByLabelText("CSV file"), file);
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));

  expect(api.uploadDataset).toHaveBeenCalledWith(file);
  expect(navigateMock).toHaveBeenCalledWith("/d/abc");
});

test("shows a banner and does not navigate when upload fails", async () => {
  vi.spyOn(api, "uploadDataset").mockRejectedValue(
    new api.ApiError(400, "Only .csv files are accepted"),
  );
  renderPage();
  const file = new File(["x"], "s.csv", { type: "text/csv" });

  await userEvent.upload(screen.getByLabelText("CSV file"), file);
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Only .csv files are accepted");
  expect(navigateMock).not.toHaveBeenCalled();
});
```

- [ ] **Step 3: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/UploadPage.test.tsx`
Expected: PASS — 2 tests passing.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/UploadPage.tsx frontend/src/pages/UploadPage.test.tsx
git commit -m "feat(frontend): add UploadPage"
```

---

### Task 7: DatasetPage

**Files:**
- Create: `frontend/src/pages/DatasetPage.tsx`
- Test: `frontend/src/pages/DatasetPage.test.tsx`

**Interfaces:**
- Consumes: `getDataset`, `getChatHistory`, `postChat` from `../api`; `ChatTurn`, `QuestionBox`, `ErrorBanner` from `../components/*`; `useParams` from `react-router-dom`.
- Produces: `DatasetPage` default export — loads dataset + history on mount (parallel), renders header (`name`, `n_rows` × `n_cols`), the turn list, an empty-state prompt, and `QuestionBox`. On ask, appends a synthetic user turn then the returned assistant turn; on ask failure, shows a banner and appends nothing; on load failure, shows a banner.

- [ ] **Step 1: Create `frontend/src/pages/DatasetPage.tsx`**

```tsx
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { getChatHistory, getDataset, postChat } from "../api";
import type { ChatMessageOut, DatasetOut } from "../types";
import ChatTurn from "../components/ChatTurn";
import QuestionBox from "../components/QuestionBox";
import ErrorBanner from "../components/ErrorBanner";

export default function DatasetPage() {
  const { id } = useParams<{ id: string }>();
  const [dataset, setDataset] = useState<DatasetOut | null>(null);
  const [messages, setMessages] = useState<ChatMessageOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let active = true;
    setLoading(true);
    setLoadError(null);
    Promise.all([getDataset(id), getChatHistory(id)])
      .then(([ds, history]) => {
        if (!active) return;
        setDataset(ds);
        setMessages(history.messages);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setLoadError(err instanceof Error ? err.message : "Failed to load dataset");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [id]);

  async function handleAsk(question: string) {
    if (!id) return;
    setPending(true);
    setAskError(null);
    const userTurn: ChatMessageOut = {
      id: `local-${Date.now()}`,
      role: "user",
      content: question,
      charts: [],
      stats: [],
      errors: [],
    };
    try {
      const assistant = await postChat(id, question);
      setMessages((prev) => [...prev, userTurn, assistant]);
    } catch (err: unknown) {
      setAskError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setPending(false);
    }
  }

  if (loading) return <p>Loading…</p>;
  if (loadError) return <ErrorBanner message={loadError} />;
  if (!dataset) return <ErrorBanner message="Dataset not found" />;

  return (
    <main>
      <header>
        <h1>{dataset.name}</h1>
        <p>
          {dataset.n_rows} rows × {dataset.n_cols} columns
        </p>
      </header>
      {messages.length === 0 && <p>Ask your first question about this dataset.</p>}
      {messages.map((m) => (
        <ChatTurn key={m.id} message={m} />
      ))}
      {askError && <ErrorBanner message={askError} />}
      <QuestionBox onSubmit={handleAsk} pending={pending} />
    </main>
  );
}
```

- [ ] **Step 2: Write the failing test `frontend/src/pages/DatasetPage.test.tsx`**

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import DatasetPage from "./DatasetPage";
import * as api from "../api";

function renderAt(id: string) {
  render(
    <MemoryRouter initialEntries={[`/d/${id}`]}>
      <Routes>
        <Route path="/d/:id" element={<DatasetPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

test("renders the fetched dataset header and history", async () => {
  vi.spyOn(api, "getDataset").mockResolvedValue({
    id: "abc", name: "sales.csv", n_rows: 10, n_cols: 4,
  });
  vi.spyOn(api, "getChatHistory").mockResolvedValue({
    messages: [
      { id: "m1", role: "user", content: "why?", charts: [], stats: [], errors: [] },
      { id: "m2", role: "assistant", content: "because", charts: [], stats: [], errors: [] },
    ],
  });

  renderAt("abc");

  expect(await screen.findByText("sales.csv")).toBeInTheDocument();
  expect(screen.getByText("10 rows × 4 columns")).toBeInTheDocument();
  expect(screen.getByText("because")).toBeInTheDocument();
});

test("appends the user turn and the returned assistant turn on ask", async () => {
  vi.spyOn(api, "getDataset").mockResolvedValue({
    id: "abc", name: "sales.csv", n_rows: 10, n_cols: 4,
  });
  vi.spyOn(api, "getChatHistory").mockResolvedValue({ messages: [] });
  vi.spyOn(api, "postChat").mockResolvedValue({
    id: "m9", role: "assistant", content: "The answer.", charts: [], stats: [], errors: [],
  });

  renderAt("abc");
  await screen.findByText("sales.csv");

  await userEvent.type(screen.getByLabelText("Question"), "why is revenue high?");
  await userEvent.click(screen.getByRole("button", { name: "Ask" }));

  expect(await screen.findByText("The answer.")).toBeInTheDocument();
  expect(screen.getByText("why is revenue high?")).toBeInTheDocument();
  expect(api.postChat).toHaveBeenCalledWith("abc", "why is revenue high?");
});

test("shows a banner when the initial load fails", async () => {
  vi.spyOn(api, "getDataset").mockRejectedValue(new api.ApiError(404, "Dataset not found"));
  vi.spyOn(api, "getChatHistory").mockRejectedValue(new api.ApiError(404, "Dataset not found"));

  renderAt("nope");

  expect(await screen.findByRole("alert")).toHaveTextContent("Dataset not found");
});
```

- [ ] **Step 3: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/DatasetPage.test.tsx`
Expected: PASS — 3 tests passing.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/DatasetPage.tsx frontend/src/pages/DatasetPage.test.tsx
git commit -m "feat(frontend): add DatasetPage with chat flow"
```

---

### Task 8: Wire real routes, env docs, README, full-suite gate

**Files:**
- Modify: `frontend/src/App.tsx` (swap placeholders for real pages)
- Modify: `frontend/src/App.test.tsx` (assert real routing)
- Create: `frontend/.env.example`
- Create: `frontend/README.md`

**Interfaces:**
- Consumes: `UploadPage` from `./pages/UploadPage`, `DatasetPage` from `./pages/DatasetPage`.
- Produces: fully wired `App`; `/` renders `UploadPage`, `/d/:id` renders `DatasetPage`.

- [ ] **Step 1: Replace `frontend/src/App.tsx` with the wired version**

```tsx
import { Routes, Route } from "react-router-dom";
import UploadPage from "./pages/UploadPage";
import DatasetPage from "./pages/DatasetPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<UploadPage />} />
      <Route path="/d/:id" element={<DatasetPage />} />
    </Routes>
  );
}
```

- [ ] **Step 2: Replace `frontend/src/App.test.tsx` to assert real routing**

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";

test("renders the upload page at /", () => {
  render(
    <MemoryRouter initialEntries={["/"]}>
      <App />
    </MemoryRouter>,
  );
  expect(screen.getByRole("heading", { name: "CSV Analysis Assistant" })).toBeInTheDocument();
});
```

- [ ] **Step 3: Run the updated App test to verify it passes**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: PASS — 1 test passing.

- [ ] **Step 4: Create `frontend/.env.example`**

```dotenv
# Base URL the frontend uses to reach the backend API.
# Default (/api) is served by the Vite dev proxy → http://localhost:8000.
# For a deployed frontend, set the absolute backend URL, e.g. https://api.example.com
VITE_API_BASE=/api
```

- [ ] **Step 5: Create `frontend/README.md`**

```markdown
# CSV Analysis Assistant — Frontend

React + Vite + TypeScript single-page UI for Project 1.

## Develop

```bash
npm install
npm run dev        # http://localhost:5173, proxies /api → http://localhost:8000
```

Run the backend separately (`make dev` from the repo root) so `/api` resolves.

## Scripts

- `npm run dev` — Vite dev server with the `/api` proxy
- `npm test` — Vitest + React Testing Library (mocked fetch; no backend needed)
- `npm run build` — type-check (`tsc`) then production build
- `npm run type-check` — `tsc --noEmit`

## Configuration

`VITE_API_BASE` (see `.env.example`) sets the API base URL; defaults to `/api`.
In production, point it at the deployed backend and configure that backend's
`CORS_ALLOW_ORIGINS` to include the frontend origin.
```

- [ ] **Step 6: Run the full frontend suite**

Run: `cd frontend && npm test`
Expected: PASS — all tests across every file green (App, api, ChatTurn, QuestionBox, UploadPage, DatasetPage).

- [ ] **Step 7: Verify the production build compiles**

Run: `cd frontend && npm run build`
Expected: `tsc` clean, Vite writes `dist/`.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx frontend/.env.example frontend/README.md
git commit -m "feat(frontend): wire routes to real pages; add env docs and README"
```

---

## Notes for the executor

- Tasks 1 and 2 are independent (frontend scaffold vs. backend CORS) but both must land before the app is usable end-to-end; keep the given order for a clean history.
- `npx vitest run <path>` runs a single test file during a task; `npm test` runs the whole suite (use it in Task 8 and any time you want the full gate).
- Do not add libraries beyond those in Task 1's `package.json` without updating this plan — the Global Constraints forbid extra state/data/UI dependencies.
