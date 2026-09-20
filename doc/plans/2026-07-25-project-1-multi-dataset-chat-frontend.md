# Multi-Dataset Chat — Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user upload multiple CSVs at once, start one chat over all of them,
and see which datasets are attached via name chips. Mirrors the backend's new
`/chats` resource (see `doc/plans/2026-07-25-project-1-multi-dataset-chat-backend.md`,
which must land first — this plan calls the routes it introduces).

**Architecture:** `UploadPage` accepts multiple files, uploads each via the
existing `POST /datasets`, then calls the new `POST /chats {dataset_ids}` and
navigates to `/c/:chatId`. `DatasetPage` is renamed `ChatPage` — it no longer
fetches a single `Dataset`; it fetches only `GET /chats/{chatId}`, which now
returns both `datasets` (id+name per attached dataset) and `messages`. A new
`DatasetChips` component renders the attached-dataset names in the header.

**Tech Stack:** React + Vite + TypeScript, React Router, Vitest + React Testing
Library (mocked `fetch`, no backend).

**Related design doc:** `doc/project-1-multi-dataset-chat-design.md` (approved),
Section "Frontend". Backend plan (must be implemented first, or at minimum this
plan's code must target its final shapes):
`doc/plans/2026-07-25-project-1-multi-dataset-chat-backend.md`.

## Global Constraints

- Frontend code and tests live in `frontend/src/` (co-located `*.test.tsx`).
- Run `npm test` after every code step; run `npm run build` (tsc type-check +
  production build) before the final commit of each task.
- Keep the existing per-component style: small, single-purpose presentational
  components (`ChartList`, `StatsDetails`, `ErrorBanner`) with a co-located test file.
- `ChatDatasetOut` from the backend is `{id: string, name: string}` only — no
  row/column counts. Do not call `getDataset` per attached dataset just to
  backfill counts; the chip header shows names only, matching what `GET /chats/{id}`
  already returns in one round trip.

---

### Task 1: Types for the new `/chats` response shapes

**Files:**
- Modify: `frontend/src/types.ts`

**Interfaces:**
- Produces: `ChatDatasetOut { id: string; name: string }`, `ChatOut { id: string; datasets: ChatDatasetOut[] }`.
  `ChatHistoryOut` gains `datasets: ChatDatasetOut[]` alongside its existing `messages`.
  `DatasetOut` and `ChatMessageOut` are unchanged.

- [ ] **Step 1: Edit `frontend/src/types.ts`**

Replace the file in full:

```typescript
export interface DatasetOut {
  id: string;
  name: string;
  n_rows: number;
  n_cols: number;
}

export interface ChatDatasetOut {
  id: string;
  name: string;
}

export interface ChatOut {
  id: string;
  datasets: ChatDatasetOut[];
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
  datasets: ChatDatasetOut[];
  messages: ChatMessageOut[];
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npm run type-check`
Expected: errors in `api.ts`/`DatasetPage.tsx`/their tests (they still reference
the old `ChatHistoryOut` shape and old endpoints) — these are fixed in Tasks 2–4.
This step is just confirming `types.ts` itself introduces no new syntax errors;
the pre-existing consumers breaking is expected at this point in the plan.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types.ts
git commit -m "feat(frontend): add ChatDatasetOut/ChatOut types for multi-dataset chats"
```

---

### Task 2: `api.ts` — `createChat`, repoint chat endpoints to `/chats`

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/api.test.ts`

**Interfaces:**
- Consumes: `ChatOut`, `ChatHistoryOut`, `ChatMessageOut` from Task 1.
- Produces: `createChat(datasetIds: string[]): Promise<ChatOut>`. `getChatHistory(chatId: string)`
  now `GET /chats/{chatId}` (was `/datasets/{id}/chat`). `postChat(chatId: string, question: string)`
  now `POST /chats/{chatId}/messages` (was `/datasets/{id}/chat`). `uploadDataset`/`getDataset`
  unchanged — `GET /datasets/{id}` still exists on the backend and is left in
  place even though no page currently calls it, since it's a thin 1:1 wrapper
  around a live endpoint, not dead application logic.

- [ ] **Step 1: Write the failing tests**

Replace `frontend/src/api.test.ts` in full:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { uploadDataset, getDataset, createChat, getChatHistory, postChat, ApiError } from "./api";

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

  it("createChat posts dataset_ids to /api/chats", async () => {
    const fetchMock = mockFetch(200, {
      id: "chat1",
      datasets: [{ id: "ds1", name: "a.csv" }, { id: "ds2", name: "b.csv" }],
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await createChat(["ds1", "ds2"]);

    expect(result.id).toBe("chat1");
    expect(result.datasets).toHaveLength(2);
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/chats");
    expect((opts as RequestInit).method).toBe("POST");
    expect(JSON.parse((opts as RequestInit).body as string)).toEqual({
      dataset_ids: ["ds1", "ds2"],
    });
  });

  it("getChatHistory GETs /api/chats/{chatId}", async () => {
    const fetchMock = mockFetch(200, { datasets: [{ id: "ds1", name: "a.csv" }], messages: [] });
    vi.stubGlobal("fetch", fetchMock);

    const result = await getChatHistory("chat1");

    expect(result.messages).toEqual([]);
    expect(result.datasets).toEqual([{ id: "ds1", name: "a.csv" }]);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/chats/chat1");
  });

  it("postChat posts a JSON question to /api/chats/{chatId}/messages", async () => {
    const fetchMock = mockFetch(200, {
      id: "m1", role: "assistant", content: "hi", charts: [], stats: [], errors: [],
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await postChat("chat1", "why?");

    expect(result.role).toBe("assistant");
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/chats/chat1/messages");
    expect((opts as RequestInit).method).toBe("POST");
    expect(JSON.parse((opts as RequestInit).body as string)).toEqual({ question: "why?" });
  });

  it("maps a non-2xx response to a thrown ApiError with detail", async () => {
    const fetchMock = mockFetch(404, { detail: "Chat not found" });
    vi.stubGlobal("fetch", fetchMock);

    await expect(getChatHistory("nope")).rejects.toBeInstanceOf(ApiError);
    vi.stubGlobal("fetch", mockFetch(404, { detail: "Chat not found" }));
    await expect(getChatHistory("nope")).rejects.toMatchObject({
      status: 404,
      message: "Chat not found",
    });
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- api.test.ts`
Expected: FAIL — `createChat` doesn't exist yet (`ImportError`-equivalent from
Vitest), and the URL assertions for `getChatHistory`/`postChat` fail against the
current `/datasets/{id}/chat` implementation.

- [ ] **Step 3: Edit `frontend/src/api.ts`**

Replace lines 1 and 40–54 (the type import and the two chat functions), and add
`createChat` between `getDataset` and `getChatHistory`:

```typescript
import type { ChatHistoryOut, ChatMessageOut, ChatOut, DatasetOut } from "./types";
```

```typescript
export async function createChat(datasetIds: string[]): Promise<ChatOut> {
  const res = await fetch(`${API_BASE}/chats`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dataset_ids: datasetIds }),
  });
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<ChatOut>;
}

export async function getChatHistory(chatId: string): Promise<ChatHistoryOut> {
  const res = await fetch(`${API_BASE}/chats/${chatId}`);
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<ChatHistoryOut>;
}

export async function postChat(chatId: string, question: string): Promise<ChatMessageOut> {
  const res = await fetch(`${API_BASE}/chats/${chatId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<ChatMessageOut>;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- api.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.ts frontend/src/api.test.ts
git commit -m "feat(frontend): add createChat, repoint chat endpoints to /chats"
```

---

### Task 3: `DatasetChips` component

**Files:**
- Create: `frontend/src/components/DatasetChips.tsx`
- Create: `frontend/src/components/DatasetChips.test.tsx`

**Interfaces:**
- Consumes: `ChatDatasetOut` from Task 1.
- Produces: `DatasetChips({ datasets: ChatDatasetOut[] }): JSX.Element | null` — renders
  nothing for an empty list (matching the null-on-empty convention already used by
  `ChartList`/`StatsDetails`), otherwise one chip per dataset showing its name.
  Task 4 (`ChatPage`) renders this in place of the old single dataset header line.

- [ ] **Step 1: Write the failing tests**

```typescript
import { render, screen } from "@testing-library/react";
import DatasetChips from "./DatasetChips";

test("renders nothing when there are no datasets", () => {
  const { container } = render(<DatasetChips datasets={[]} />);
  expect(container).toBeEmptyDOMElement();
});

test("renders one chip per dataset with its name", () => {
  render(
    <DatasetChips
      datasets={[
        { id: "ds1", name: "sales.csv" },
        { id: "ds2", name: "regions.csv" },
      ]}
    />,
  );
  expect(screen.getByText("sales.csv")).toBeInTheDocument();
  expect(screen.getByText("regions.csv")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- DatasetChips.test.tsx`
Expected: FAIL — `Cannot find module './DatasetChips'`

- [ ] **Step 3: Create `frontend/src/components/DatasetChips.tsx`**

```typescript
import type { ChatDatasetOut } from "../types";

interface Props {
  datasets: ChatDatasetOut[];
}

export default function DatasetChips({ datasets }: Props) {
  if (datasets.length === 0) return null;
  return (
    <ul aria-label="Attached datasets">
      {datasets.map((d) => (
        <li key={d.id}>{d.name}</li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- DatasetChips.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/DatasetChips.tsx frontend/src/components/DatasetChips.test.tsx
git commit -m "feat(frontend): add DatasetChips component"
```

---

### Task 4: `DatasetPage` → `ChatPage` (route `/d/:id` → `/c/:chatId`)

**Files:**
- Create: `frontend/src/pages/ChatPage.tsx` (content of current `DatasetPage.tsx`, rewritten)
- Create: `frontend/src/pages/ChatPage.test.tsx` (content of current `DatasetPage.test.tsx`, rewritten)
- Delete: `frontend/src/pages/DatasetPage.tsx`
- Delete: `frontend/src/pages/DatasetPage.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `getChatHistory`, `postChat` from Task 2; `DatasetChips` from Task 3;
  `ChatHistoryOut`, `ChatMessageOut` from Task 1.
- Produces: `ChatPage` component mounted at `/c/:chatId`. No longer calls `getDataset`
  — the page no longer shows row/column counts (see Global Constraints).

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/pages/ChatPage.test.tsx`:

```typescript
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ChatPage from "./ChatPage";
import * as api from "../api";

function renderAt(chatId: string) {
  render(
    <MemoryRouter initialEntries={[`/c/${chatId}`]}>
      <Routes>
        <Route path="/c/:chatId" element={<ChatPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

test("renders attached dataset chips and history", async () => {
  vi.spyOn(api, "getChatHistory").mockResolvedValue({
    datasets: [{ id: "ds1", name: "sales.csv" }, { id: "ds2", name: "regions.csv" }],
    messages: [
      { id: "m1", role: "user", content: "why?", charts: [], stats: [], errors: [] },
      { id: "m2", role: "assistant", content: "because", charts: [], stats: [], errors: [] },
    ],
  });

  renderAt("chat1");

  expect(await screen.findByText("sales.csv")).toBeInTheDocument();
  expect(screen.getByText("regions.csv")).toBeInTheDocument();
  expect(screen.getByText("because")).toBeInTheDocument();
});

test("appends the user turn and the returned assistant turn on ask", async () => {
  vi.spyOn(api, "getChatHistory").mockResolvedValue({
    datasets: [{ id: "ds1", name: "sales.csv" }],
    messages: [],
  });
  vi.spyOn(api, "postChat").mockResolvedValue({
    id: "m9", role: "assistant", content: "The answer.", charts: [], stats: [], errors: [],
  });

  renderAt("chat1");
  await screen.findByText("sales.csv");

  await userEvent.type(screen.getByLabelText("Question"), "why is revenue high?");
  await userEvent.click(screen.getByRole("button", { name: "Ask" }));

  expect(await screen.findByText("The answer.")).toBeInTheDocument();
  expect(screen.getByText("why is revenue high?")).toBeInTheDocument();
  expect(api.postChat).toHaveBeenCalledWith("chat1", "why is revenue high?");
});

test("shows a banner when the initial load fails", async () => {
  vi.spyOn(api, "getChatHistory").mockRejectedValue(new api.ApiError(404, "Chat not found"));

  renderAt("nope");

  expect(await screen.findByRole("alert")).toHaveTextContent("Chat not found");
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- ChatPage.test.tsx`
Expected: FAIL — `Cannot find module './ChatPage'`

- [ ] **Step 3: Create `frontend/src/pages/ChatPage.tsx`**

```typescript
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { getChatHistory, postChat } from "../api";
import type { ChatDatasetOut, ChatMessageOut } from "../types";
import ChatTurn from "../components/ChatTurn";
import QuestionBox from "../components/QuestionBox";
import ErrorBanner from "../components/ErrorBanner";
import DatasetChips from "../components/DatasetChips";

export default function ChatPage() {
  const { chatId } = useParams<{ chatId: string }>();
  const [datasets, setDatasets] = useState<ChatDatasetOut[]>([]);
  const [messages, setMessages] = useState<ChatMessageOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);

  useEffect(() => {
    if (!chatId) return;
    let active = true;
    setLoading(true);
    setLoadError(null);
    getChatHistory(chatId)
      .then((history) => {
        if (!active) return;
        setDatasets(history.datasets);
        setMessages(history.messages);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setLoadError(err instanceof Error ? err.message : "Failed to load chat");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [chatId]);

  async function handleAsk(question: string) {
    if (!chatId) return;
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
      const assistant = await postChat(chatId, question);
      setMessages((prev) => [...prev, userTurn, assistant]);
    } catch (err: unknown) {
      setAskError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setPending(false);
    }
  }

  if (loading) return <p>Loading…</p>;
  if (loadError) return <ErrorBanner message={loadError} />;

  return (
    <main>
      <header>
        <h1>Chat</h1>
        <DatasetChips datasets={datasets} />
      </header>
      {messages.length === 0 && <p>Ask your first question about these datasets.</p>}
      {messages.map((m) => (
        <ChatTurn key={m.id} message={m} />
      ))}
      {askError && <ErrorBanner message={askError} />}
      <QuestionBox onSubmit={handleAsk} pending={pending} />
    </main>
  );
}
```

- [ ] **Step 4: Delete the old page and its test**

```bash
git rm frontend/src/pages/DatasetPage.tsx frontend/src/pages/DatasetPage.test.tsx
```

- [ ] **Step 5: Update `frontend/src/App.tsx`**

```typescript
import { Routes, Route } from "react-router-dom";
import UploadPage from "./pages/UploadPage";
import ChatPage from "./pages/ChatPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<UploadPage />} />
      <Route path="/c/:chatId" element={<ChatPage />} />
    </Routes>
  );
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd frontend && npm test`
Expected: PASS across the whole suite (note: `App.test.tsx` only renders `/` and
asserts the upload heading, so it's unaffected by the route rename; `UploadPage.test.tsx`
still targets the pre-Task-6 `UploadPage`, so it should still pass unchanged at
this point)

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/ChatPage.tsx frontend/src/pages/ChatPage.test.tsx frontend/src/App.tsx
git commit -m "feat(frontend): rename DatasetPage to ChatPage, route /d/:id -> /c/:chatId"
```

---

### Task 5: Multi-file `UploadPage`

**Files:**
- Modify: `frontend/src/pages/UploadPage.tsx`
- Modify: `frontend/src/pages/UploadPage.test.tsx`

**Interfaces:**
- Consumes: `uploadDataset` (unchanged), `createChat` from Task 2.
- Produces: `UploadPage` accepts multiple files, uploads each in turn, then
  creates one chat over all resulting dataset ids and navigates to `/c/{chatId}`.

- [ ] **Step 1: Write the failing tests**

Replace `frontend/src/pages/UploadPage.test.tsx` in full:

```typescript
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

test("uploads a single chosen file and navigates to its chat", async () => {
  vi.spyOn(api, "uploadDataset").mockResolvedValue({
    id: "abc", name: "s.csv", n_rows: 3, n_cols: 2,
  });
  vi.spyOn(api, "createChat").mockResolvedValue({
    id: "chat1", datasets: [{ id: "abc", name: "s.csv" }],
  });
  renderPage();
  const file = new File(["a,b\n1,2\n"], "s.csv", { type: "text/csv" });

  await userEvent.upload(screen.getByLabelText("CSV files"), file);
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));

  expect(api.uploadDataset).toHaveBeenCalledWith(file);
  expect(api.createChat).toHaveBeenCalledWith(["abc"]);
  expect(navigateMock).toHaveBeenCalledWith("/c/chat1");
});

test("uploads multiple chosen files, then creates one chat over all of them", async () => {
  vi.spyOn(api, "uploadDataset")
    .mockResolvedValueOnce({ id: "ds1", name: "a.csv", n_rows: 1, n_cols: 1 })
    .mockResolvedValueOnce({ id: "ds2", name: "b.csv", n_rows: 1, n_cols: 1 });
  vi.spyOn(api, "createChat").mockResolvedValue({
    id: "chat1",
    datasets: [{ id: "ds1", name: "a.csv" }, { id: "ds2", name: "b.csv" }],
  });
  renderPage();
  const fileA = new File(["a\n1\n"], "a.csv", { type: "text/csv" });
  const fileB = new File(["b\n2\n"], "b.csv", { type: "text/csv" });

  await userEvent.upload(screen.getByLabelText("CSV files"), [fileA, fileB]);
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));

  expect(api.uploadDataset).toHaveBeenNthCalledWith(1, fileA);
  expect(api.uploadDataset).toHaveBeenNthCalledWith(2, fileB);
  expect(api.createChat).toHaveBeenCalledWith(["ds1", "ds2"]);
  expect(navigateMock).toHaveBeenCalledWith("/c/chat1");
});

test("shows a banner and does not navigate when upload fails", async () => {
  vi.spyOn(api, "uploadDataset").mockRejectedValue(
    new api.ApiError(400, "Only .csv files are accepted"),
  );
  renderPage();
  const file = new File(["x"], "s.csv", { type: "text/csv" });

  await userEvent.upload(screen.getByLabelText("CSV files"), file);
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Only .csv files are accepted");
  expect(navigateMock).not.toHaveBeenCalled();
});

test("shows a banner and does not navigate when chat creation fails", async () => {
  vi.spyOn(api, "uploadDataset").mockResolvedValue({
    id: "abc", name: "s.csv", n_rows: 3, n_cols: 2,
  });
  vi.spyOn(api, "createChat").mockRejectedValue(new api.ApiError(500, "Server error"));
  renderPage();
  const file = new File(["a,b\n1,2\n"], "s.csv", { type: "text/csv" });

  await userEvent.upload(screen.getByLabelText("CSV files"), file);
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Server error");
  expect(navigateMock).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- UploadPage.test.tsx`
Expected: FAIL — the current single-file input has `aria-label="CSV file"` (singular,
no `multiple` attribute) so `getByLabelText("CSV files")` doesn't match, and
`createChat` isn't called at all yet.

- [ ] **Step 3: Rewrite `frontend/src/pages/UploadPage.tsx`**

```typescript
import { useState, type ChangeEvent, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { createChat, uploadDataset } from "../api";
import ErrorBanner from "../components/ErrorBanner";

export default function UploadPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    setFiles(Array.from(e.target.files ?? []));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (files.length === 0 || pending) return;
    setPending(true);
    setError(null);
    try {
      const datasetIds: string[] = [];
      for (const file of files) {
        const dataset = await uploadDataset(file);
        datasetIds.push(dataset.id);
      }
      const chat = await createChat(datasetIds);
      navigate(`/c/${chat.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
      setPending(false);
    }
  }

  return (
    <main>
      <h1>CSV Analysis Assistant</h1>
      <p>Upload one or more CSVs to start asking questions about them.</p>
      <form onSubmit={handleSubmit}>
        <input
          type="file"
          accept=".csv"
          multiple
          aria-label="CSV files"
          onChange={handleFileChange}
        />
        <button type="submit" disabled={files.length === 0 || pending}>
          {pending ? "Uploading…" : "Upload"}
        </button>
      </form>
      {error && <ErrorBanner message={error} />}
    </main>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- UploadPage.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/UploadPage.tsx frontend/src/pages/UploadPage.test.tsx
git commit -m "feat(frontend): multi-file upload, one chat created over all datasets"
```

---

### Task 6: Full suite check + docs sync

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md` (only if it references the frontend route/page names — verify first)

**Interfaces:** None — verification and documentation only.

- [ ] **Step 1: Run the full frontend suite and build**

Run: `cd frontend && npm test`
Expected: PASS (all files: `api.test.ts`, `App.test.tsx`, `ChatPage.test.tsx`,
`UploadPage.test.tsx`, `DatasetChips.test.tsx`, `ChatTurn.test.tsx`,
`QuestionBox.test.tsx` — the latter two are untouched by this plan and should be
unaffected)

Run: `cd frontend && npm run build`
Expected: PASS (tsc type-check + production build, confirms no stale imports of
the deleted `DatasetPage` or old `ChatHistoryOut` shape remain anywhere)

- [ ] **Step 2: Update `CLAUDE.md`'s frontend code-layout section**

Find (around line 89–90):

```
    App.tsx          # routes: / (UploadPage), /d/:id (DatasetPage)
    pages/           # UploadPage, DatasetPage
```

Replace with:

```
    App.tsx          # routes: / (UploadPage), /c/:chatId (ChatPage)
    pages/           # UploadPage (multi-file), ChatPage
```

Also add `DatasetChips` to the `components/` line in that same tree listing.

- [ ] **Step 3: Check `README.md` for the same stale references**

Run: `grep -n "DatasetPage\|/d/:id" README.md`
If any matches are found, update them to `ChatPage` / `/c/:chatId` following the
surrounding sentence's existing phrasing. If no matches, no change needed.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: sync CLAUDE.md/README for ChatPage route rename"
```
