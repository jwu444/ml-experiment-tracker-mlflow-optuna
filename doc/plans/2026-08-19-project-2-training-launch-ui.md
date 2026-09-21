# Project 2 — Training Launch UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **AMENDED 2026-08-23 by D40 (issue #54) — read this before Task 3.** This plan
> was written against the flat model, where an `app.experiments` row *was* one
> training run and you launched one by POSTing a dataset and a target column.
> The hierarchy landed since: an **experiment** is now an investigation that owns
> the dataset, the target column and the task type, and a **run** is one attempt
> inside it. Tasks 1 and 2 are unaffected — `GET /datasets/{id}` and `GET /models`
> are about datasets and the registry, which the rename did not touch, and the
> `persistence` / `prior_column` special case stands exactly as written. Task 3
> changes as follows:
>
> - **The dataset picker becomes an experiment picker.** A run cannot exist
>   outside an experiment (`runs.experiment_id` is `NOT NULL`), so the form's
>   first field selects one from `listExperiments()`. There is no "pick a dataset"
>   step any more, and no default experiment to fall back to.
> - **The column dropdowns resolve through the experiment.** Fetch the chosen
>   experiment, read its `dataset_id`, then `getDataset(dataset_id)` for the
>   `columns` Task 1 adds. The **target column is not a field** — it belongs to
>   the experiment. Only `feature_columns` and `time_column` remain choosable,
>   and both must exclude the parent's `target_column`.
> - **The endpoints are nested.** `POST /experiments/{id}/train` and
>   `POST /experiments/{id}/tune`, with `dataset_id` and `target_column` gone
>   from both bodies. Task 3 Step 1's `trainExperiment` / `tuneExperiment`
>   wrappers should be written as `trainRun(experimentId, body)` /
>   `tuneRun(experimentId, body)` — `api.ts` already has `createExperiment`,
>   `getExperiment` and `listExperiments` from #54, so only these two are new.
> - **Add a "New experiment" form.** With training nested, an empty install has
>   nowhere to put a first run. A small form over `POST /experiments`
>   (`name`, `objective`, `dataset_id`, `target_column`, `task_type`) belongs on
>   the `/experiments` list page, beside the "New run" action.
> - **"New run" moves to the detail page.** Task 3 Step 4 mounts the dialog on
>   `ExperimentsPage`, which is now the *list* of investigations; the run-launch
>   action belongs on `ExperimentDetailPage` (`/experiments/:id`), where the
>   experiment is already in hand and the leaderboard it lands on is on screen.
> - **The response shapes changed.** Train returns `run_id` (not
>   `experiment_id`); tune returns `best_run_id`. A `422` now also covers
>   "this model's metric disagrees with the experiment's `primary_metric`" —
>   surface the backend's message as-is, per this plan's existing rule.
>
> Everything below this block is the original text and still says `dataset_id`
> in places the amendment overrides. Where the two disagree, this block governs.

**Origin:** [issue #52](https://github.com/jwu444/ml-experiment-tracker-mlflow-optuna/issues/52) — `POST /experiments/train` and `POST /experiments/tune` exist and work, but nothing in the frontend calls them. `/experiments` only filters and reads existing runs; every actual training call has to be a hand-written `curl`. This was found while running the Phase 2a/2b acceptance checklist (issue #48) and is the single highest-value UI gap in the app right now. There is no separate design doc — the design was worked out directly on #52 and is reproduced below.

**Goal:** A "New run" action on `/experiments` that launches a real training or Optuna-tuning run, with the same validation guarantees the API already has (unknown column/model → the backend's real error, not a guess).

**Architecture:** Two small backend additions expose data the app already has but never returns, so the form can be built from dropdowns instead of free-text guessing:

1. **Dataset columns.** `DatasetOut` today is `{id, name, n_rows, n_cols}` — no column names. `DatasetColumn` (name, `inferred_type`, `null_count`) is already populated at upload time; it's just never serialized out. `GET /datasets/{id}` grows a `DatasetDetailOut` response (mirroring the existing `ExperimentOut`/`ExperimentDetailOut` split) that adds `columns`.
2. **The model registry.** `ExperimentsPage.tsx` already hardcodes one drifting copy of the model list (`MODEL_TYPES`), and it's already missing an entry (`persistence` — see #51). Building a training form's model picker by hardcoding a *second* copy makes that worse, not better. A new `GET /models` reflects `training.MODEL_REGISTRY` directly — `task_type`, whether it's tunable, and its `search_space` shape — so the frontend can never drift from the backend registry again, on either page.

With both in place, `NewRunDialog` is a self-contained form component: pick a dataset → its columns populate the target/time/feature dropdowns; pick a model → its `search_space` populates the hyperparameter inputs. Submits go through the existing, unmodified `POST /experiments/train` / `POST /experiments/tune`.

**One deliberate special case:** `persistence`'s `search_space` is `{}` (correctly — nothing about it is tunable), but training it still requires a `hyperparams.prior_column` value that isn't a search-space entry at all; `PriorValueRegressor.fit` raises if it's missing. `GET /models` reflects the registry faithfully (empty `hyperparams` for `persistence`), and the frontend special-cases `model_type === "persistence"` to show a `prior_column` picker instead of "no hyperparameters." Extending `ModelSpec` to generically declare required-but-not-tunable params was considered and rejected as scope creep for a form with exactly one such model.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy 2.0, pytest (backend); React + Vite + TypeScript, the existing `Dialog`/`Button`/`Input`/`Textarea` primitives in `frontend/src/ui/`, Vitest + React Testing Library (frontend).

## Global Constraints

- Line length **100** (ruff + black). mypy is **strict** on `backend/app`.
- Imports are absolute from `app` (e.g. `from app.training import MODEL_REGISTRY`).
- Backend app code in `backend/app/` only; backend tests in `backend/tests/` only.
- Tests run on **SQLite** via the `client`/`session` fixtures in `backend/tests/conftest.py`. No API key, no network, no Postgres.
- No schema/migration changes in this plan — `DatasetColumn` and `MODEL_REGISTRY` both already exist; every task here only exposes data that's already there.
- Frontend tests run with `css: false`: assert on roles / accessible names / `data-*` / visible text, **never** CSS-module class names.
- Match existing patterns exactly rather than inventing new ones: `ExperimentOut`/`ExperimentDetailOut` for the list/detail schema split (Task 1), `Dialog` for the modal (already used in `ExperimentsPage.tsx`'s notes-review flow), the `pending`/`loading` button-state convention (`QuestionBox`, `DatasetSidebar`).
- The CI gate is `make check` (lint + format-check + type-check + test) plus the frontend job (`npm run type-check`, `npm test`, `npm run build`).

> **AS BUILT 2026-08-24 (`b2d93ca`).** Every task is done; four things landed
> differently from the text below, and the code is what shipped:
>
> 1. **`persistence` is not special-cased in the frontend.** The plan said the
>    form shows a `prior_column` field for that model. It reads
>    `ModelSpec.column_hyperparams` instead — a new registry field, serialized
>    by `GET /models`, naming the hyperparameters whose value is a column name.
>    Matching on `model_type === "persistence"` in the dialog would have been
>    #51 again in a new file.
> 2. **`feature_columns` is not on the form.** The backend infers the feature
>    set from the dataset minus the target; the endpoints still accept an
>    explicit list for API callers. A column multi-select is its own issue.
> 3. **The dialogs own their `open` state** and render their own trigger, as
>    `ReviewDialog` in `ExperimentDetailPage.tsx` already does — so the props
>    are `{experiment, onCreated}` / `{onCreated}`, not `{open, onClose,
>    onCreated}`.
> 4. **Task 3 Step 4's `MODEL_TYPES` fix was moot**, as the D40 amendment
>    predicted: #51 removed that constant in `2fd2318`.

---

## File Structure

**Created:**

| File | Responsibility |
|---|---|
| `backend/app/routes/models.py` | `GET /models` — serializes `MODEL_REGISTRY`. |
| `backend/tests/test_models_route.py` | Route tests for `GET /models`. |
| `frontend/src/components/NewRunDialog.tsx` (+ `.module.css`, `.test.tsx`) | The train/tune form, opened from `ExperimentsPage`. |

**Modified:**

| File | Change |
|---|---|
| `backend/app/schemas.py` | Add `DatasetColumnOut`, `DatasetDetailOut`, `HyperparamSpecOut`, `ModelSpecOut`. |
| `backend/app/routes/datasets.py` | `GET /datasets/{id}` returns `DatasetDetailOut` (adds `columns`). |
| `backend/app/main.py` | Register the `models` router. |
| `backend/tests/test_datasets.py` | Add coverage for `columns` on the detail route. |
| `frontend/src/api.ts` | Add `Model`, `listModels`, `trainExperiment`, `tuneExperiment`; extend the `Dataset`/`DatasetOut` type with optional `columns`. |
| `frontend/src/pages/ExperimentsPage.tsx` | Add a "New run" button opening `NewRunDialog`; reload the list on success. |
| `frontend/src/pages/ExperimentsPage.tsx` `MODEL_TYPES` | Fix the #51 gap (`persistence` missing) while this file is already being touched. |
| `README.md`, `CLAUDE.md`, `doc/user-manual.md` | Doc sync (Task 4) — the manual currently overclaims this UI exists (§5); correct it to describe the real thing. |

---

## Task 1: Expose a dataset's columns (`GET /datasets/{id}`)

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routes/datasets.py`
- Modify: `backend/tests/test_datasets.py`

**Interfaces:**
- Consumes: `DatasetColumn` rows already written at upload time (`app/routes/datasets.py`'s existing `POST /datasets` handler — unchanged).
- Produces:
  - `schemas.DatasetColumnOut {name: str, inferred_type: str, null_count: int}`
  - `schemas.DatasetDetailOut(DatasetOut) {columns: list[DatasetColumnOut]}`
  - `GET /datasets/{id}` now responds `DatasetDetailOut` instead of `DatasetOut` (list endpoint `GET /datasets` is untouched — no reason to pay for every dataset's full column list on every list load).

- [x] **Step 1: Write the failing test**

Add to `backend/tests/test_datasets.py`:

```python
def test_get_dataset_returns_columns(client) -> None:
    csv = b"ticker,revenue\nNVDA,1000\nAMD,500\n"
    upload = client.post("/datasets", files={"file": ("d.csv", csv, "text/csv")})
    dataset_id = upload.json()["id"]

    resp = client.get(f"/datasets/{dataset_id}")

    assert resp.status_code == 200
    body = resp.json()
    names = {c["name"] for c in body["columns"]}
    assert names == {"ticker", "revenue"}
    # every column reports a type and a null count, not just a name
    assert all("inferred_type" in c and "null_count" in c for c in body["columns"])
```

Run: `poetry run pytest backend/tests/test_datasets.py -k columns -q`
Expected: FAILS — `KeyError: 'columns'` (the current `DatasetOut` has no such field).

- [x] **Step 2: Add the schemas**

In `backend/app/schemas.py`, after `DatasetOut`:

```python
class DatasetColumnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    inferred_type: str
    null_count: int


class DatasetDetailOut(DatasetOut):
    columns: list[DatasetColumnOut]
```

- [x] **Step 3: Return it from the route**

In `backend/app/routes/datasets.py`, change the detail route:

```python
@router.get("/{dataset_id}", response_model=DatasetDetailOut)
def get_dataset(dataset_id: str, session: Session = Depends(get_session)) -> DatasetDetailOut:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    columns = session.execute(
        select(DatasetColumn)
        .where(DatasetColumn.dataset_id == dataset_id)
        .order_by(DatasetColumn.ordinal_position)
    ).scalars()
    return DatasetDetailOut(
        id=dataset.id,
        name=dataset.name,
        n_rows=dataset.n_rows,
        n_cols=dataset.n_cols,
        columns=[DatasetColumnOut.model_validate(c) for c in columns],
    )
```

Add the needed imports (`select`, `DatasetColumn`) at the top of the file — both already exist elsewhere in the codebase (`app/models.py`), this route just hasn't needed them until now.

- [x] **Step 4: Run the test to verify it passes**

Run: `poetry run pytest backend/tests/test_datasets.py -q`
Expected: all pass, including the new one. `columns` is ordered by `ordinal_position`, i.e. the order columns appeared in the uploaded CSV.

- [x] **Step 5: Run the full check and commit**

```bash
make check
git add backend/app/schemas.py backend/app/routes/datasets.py backend/tests/test_datasets.py
git commit -m "feat: expose a dataset's columns on GET /datasets/{id}"
```

---

## Task 2: `GET /models` — serialize the training registry

**Files:**
- Create: `backend/app/routes/models.py`
- Create: `backend/tests/test_models_route.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: `training.MODEL_REGISTRY` (`backend/app/training.py`) — read-only, no changes to it in this task.
- Produces:
  - `schemas.HyperparamSpecOut {name: str, type: str, min: float, max: float, log_scale: bool}`
  - `schemas.ModelSpecOut {model_type: str, task_type: str, tunable: bool, hyperparams: list[HyperparamSpecOut]}`
  - `GET /models -> list[ModelSpecOut]`

- [x] **Step 1: Write the failing test**

Create `backend/tests/test_models_route.py`:

```python
from app.training import MODEL_REGISTRY


def test_get_models_lists_every_registry_entry(client) -> None:
    resp = client.get("/models")
    assert resp.status_code == 200
    body = {m["model_type"]: m for m in resp.json()}
    assert set(body) == set(MODEL_REGISTRY)


def test_persistence_is_reported_as_not_tunable(client) -> None:
    body = {m["model_type"]: m for m in client.get("/models").json()}
    assert body["persistence"]["tunable"] is False
    assert body["persistence"]["hyperparams"] == []


def test_ridge_reports_its_search_space(client) -> None:
    body = {m["model_type"]: m for m in client.get("/models").json()}
    ridge = body["ridge"]
    assert ridge["tunable"] is True
    assert ridge["hyperparams"] == [
        {"name": "alpha", "type": "float", "min": 1e-3, "max": 1e3, "log_scale": True}
    ]
```

Run: `poetry run pytest backend/tests/test_models_route.py -q`
Expected: FAILS — `404` (no `/models` route exists yet).

- [x] **Step 2: Add the schemas**

In `backend/app/schemas.py`:

```python
class HyperparamSpecOut(BaseModel):
    name: str
    type: str
    min: float
    max: float
    log_scale: bool


class ModelSpecOut(BaseModel):
    model_type: str
    task_type: str
    tunable: bool
    hyperparams: list[HyperparamSpecOut]
```

- [x] **Step 3: Write the route**

Create `backend/app/routes/models.py`:

```python
"""GET /models — the training registry, for the frontend's form to read (issue #52).

The single source of truth stays `training.MODEL_REGISTRY`; this module only
serializes it. Never hand-maintain a second copy of this list anywhere in the
frontend — that mismatch is exactly how #51 happened.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas import HyperparamSpecOut, ModelSpecOut
from app.training import MODEL_REGISTRY

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=list[ModelSpecOut])
def list_models() -> list[ModelSpecOut]:
    out = []
    for model_type, spec in MODEL_REGISTRY.items():
        hyperparams = [
            HyperparamSpecOut(name=name, type=kind, min=lo, max=hi, log_scale=log)
            for name, (kind, lo, hi, log) in spec.search_space.items()
        ]
        out.append(
            ModelSpecOut(
                model_type=model_type,
                task_type=spec.task_type,
                tunable=bool(spec.search_space),
                hyperparams=hyperparams,
            )
        )
    return out
```

- [x] **Step 4: Register the router**

In `backend/app/main.py`:

```python
from app.routes import chats, datasets, experiments, findings, models

...
app.include_router(models.router)
```

- [x] **Step 5: Run the tests to verify they pass**

Run: `poetry run pytest backend/tests/test_models_route.py -q`
Expected: all pass.

- [x] **Step 6: Run the full check and commit**

```bash
make check
git add backend/app/routes/models.py backend/tests/test_models_route.py \
        backend/app/schemas.py backend/app/main.py
git commit -m "feat: add GET /models — serializes MODEL_REGISTRY for the frontend"
```

---

## Task 3: `NewRunDialog` — the train/tune form

**Files:**
- Create: `frontend/src/components/NewRunDialog.tsx`
- Create: `frontend/src/components/NewRunDialog.module.css`
- Create: `frontend/src/components/NewRunDialog.test.tsx`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/pages/ExperimentsPage.tsx`

**Interfaces:**
- Consumes: `GET /datasets`, `GET /datasets/{id}` (now with `columns`), `GET /models` (Task 2), `POST /experiments/train`, `POST /experiments/tune`.
- Produces: `NewRunDialog({ open, onClose, onCreated }: Props)`, mounted from `ExperimentsPage`.

- [x] **Step 1: Add the API functions**

In `frontend/src/api.ts`:

```ts
export type DatasetColumn = { name: string; inferred_type: string; null_count: number };

export type DatasetDetail = {
  id: string; name: string; n_rows: number; n_cols: number; columns: DatasetColumn[];
};

export type HyperparamSpec = {
  name: string; type: "int" | "float"; min: number; max: number; log_scale: boolean;
};

export type Model = {
  model_type: string; task_type: string; tunable: boolean; hyperparams: HyperparamSpec[];
};

export async function listModels(): Promise<Model[]> {
  const res = await fetch(`${API_BASE}/models`);
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<Model[]>;
}

// getDataset() already exists and returns DatasetOut — its response now also
// carries `columns` (Task 1), so cast the result to DatasetDetail at the call
// site rather than duplicating the fetch wrapper.

export async function trainExperiment(body: {
  model_type: string; dataset_id: string; target_column: string;
  hyperparams: Record<string, unknown>; feature_columns?: string[];
  time_column?: string; notes?: string;
}): Promise<{ experiment_id: string; status: string; task_type: string; metrics: Record<string, number> }> {
  const res = await fetch(`${API_BASE}/experiments/train`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) return failFrom(res);
  return res.json();
}

export async function tuneExperiment(body: {
  model_type: string; dataset_id: string; target_column: string;
  n_trials: number; feature_columns?: string[]; time_column?: string; notes?: string;
}): Promise<{ n_trials: number; best_experiment_id: string | null; best_metrics: Record<string, number> }> {
  const res = await fetch(`${API_BASE}/experiments/tune`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) return failFrom(res);
  return res.json();
}
```

- [x] **Step 2: Write `NewRunDialog`'s failing test first**

Create `frontend/src/components/NewRunDialog.test.tsx`, covering (adapt to this project's existing RTL patterns in `ExperimentsPage.test.tsx`/`ReviewPage.test.tsx` — mock `api.ts`, never assert on CSS classes per the Global Constraints):

- Renders closed by default; opens when `open` is true.
- Loads datasets and models on open; populates the model `<select>` from the mocked `listModels()` response, including `persistence`.
- Selecting `persistence` shows a `prior_column` field instead of the generic hyperparameter inputs.
- Selecting a non-`persistence` model renders one number input per `hyperparams` entry, labelled with its `name`.
- Selecting a dataset populates target/time/feature options from that dataset's `columns` (mocked `getDataset` response).
- Switching to Tune mode replaces the hyperparameter inputs with a single `n_trials` input, and disables Tune mode entirely when `persistence` is selected (`tunable: false`).
- Submitting calls `trainExperiment`/`tuneExperiment` with the assembled body and calls `onCreated()` on success.
- A `422` response from either call is displayed verbatim in the dialog, not swallowed into a generic message.

Run: `cd frontend && npm test -- NewRunDialog` — expect failures (the component doesn't exist yet).

- [x] **Step 3: Build the component**

Create `frontend/src/components/NewRunDialog.tsx`. Structure (fill in against the tests from Step 2):

```tsx
import { useEffect, useState } from "react";
import {
  type DatasetOut, type Model, listDatasets, getDataset, listModels,
  trainExperiment, tuneExperiment,
} from "../api";
import { Dialog, Button, Input } from "../ui";
import styles from "./NewRunDialog.module.css";

type Mode = "train" | "tune";

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

export default function NewRunDialog({ open, onClose, onCreated }: Props) {
  const [mode, setMode] = useState<Mode>("train");
  const [datasets, setDatasets] = useState<DatasetOut[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [columns, setColumns] = useState<string[]>([]);
  const [modelType, setModelType] = useState("");
  const [targetColumn, setTargetColumn] = useState("");
  const [timeColumn, setTimeColumn] = useState("");
  const [hyperparams, setHyperparams] = useState<Record<string, string>>({});
  const [nTrials, setNTrials] = useState(20);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    void listDatasets().then(setDatasets);
    void listModels().then(setModels);
  }, [open]);

  useEffect(() => {
    if (!datasetId) return;
    // getDataset's response now carries `columns` (Task 1); cast here rather
    // than changing DatasetOut's declared shape everywhere it's used.
    void getDataset(datasetId).then((d) =>
      setColumns(((d as unknown as { columns: { name: string }[] }).columns ?? []).map((c) => c.name)),
    );
  }, [datasetId]);

  const selectedModel = models.find((m) => m.model_type === modelType);
  const isPersistence = modelType === "persistence";

  async function handleSubmit() {
    setSubmitting(true);
    setError(null);
    try {
      if (mode === "train") {
        await trainExperiment({
          model_type: modelType,
          dataset_id: datasetId,
          target_column: targetColumn,
          time_column: timeColumn || undefined,
          hyperparams: isPersistence
            ? { prior_column: hyperparams.prior_column }
            : Object.fromEntries(Object.entries(hyperparams).map(([k, v]) => [k, Number(v)])),
        });
      } else {
        await tuneExperiment({
          model_type: modelType,
          dataset_id: datasetId,
          target_column: targetColumn,
          time_column: timeColumn || undefined,
          n_trials: nTrials,
        });
      }
      onCreated();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setSubmitting(false);
    }
  }

  // ... render: mode toggle, dataset select, model select, target/time
  // selects populated from `columns`, hyperparameter inputs from
  // `selectedModel.hyperparams` (or the prior_column field when
  // isPersistence), n_trials input when mode === "tune", error banner,
  // submit button disabled while `submitting` or a required field is empty.
}
```

- [x] **Step 4: Wire it into `ExperimentsPage`**

In `frontend/src/pages/ExperimentsPage.tsx`:
- Add `const [dialogOpen, setDialogOpen] = useState(false)`.
- Add a "New run" `<Button>` in the header, `onClick={() => setDialogOpen(true)}`.
- Render `<NewRunDialog open={dialogOpen} onClose={() => setDialogOpen(false)} onCreated={reload} />`, where `reload` re-runs the existing `listExperiments({ modelType, taskType })` effect (extract it to a named function if it's currently only inline in `useEffect`).
- While touching this file's `MODEL_TYPES` constant, fix #51: add `["persistence", "Persistence (baseline)"]`.

- [x] **Step 5: Run the tests to verify they pass**

```bash
cd frontend
npm test -- NewRunDialog ExperimentsPage
npm run type-check
```

Expected: all pass.

- [x] **Step 6: Manual verification**

```bash
make dev            # terminal 1
cd frontend && npm run dev   # terminal 2
```

Open `/experiments`, click "New run":
- Train `ridge` on the revenue-nowcast dataset with `time_column` set → new row appears on the leaderboard.
- Train `persistence` → confirm the `prior_column` field appears instead of generic hyperparameters, and that the run succeeds when `prior_column` is also implicitly included as a feature (per `training.py`'s existing requirement — the dialog should pass it as both, or surface the backend's error clearly if it doesn't yet).
- Switch to Tune mode with `persistence` selected → confirm Tune is disabled/unavailable, not just rejected after submit.
- Submit with an invalid target column (type one that doesn't exist, bypassing the dropdown if needed) → confirm the backend's real 422 message shows in the dialog.

- [x] **Step 7: Run the full check and commit**

```bash
make check
cd frontend && npm run type-check && npm test && npm run build && cd ..
git add frontend/src/api.ts frontend/src/components/NewRunDialog.tsx \
        frontend/src/components/NewRunDialog.module.css \
        frontend/src/components/NewRunDialog.test.tsx \
        frontend/src/pages/ExperimentsPage.tsx
git commit -m "feat: NewRunDialog — launch training/tuning runs from the UI (closes #52)"
```

---

## Task 4: Doc sync

**Files:**
- Modify: `CLAUDE.md`, `README.md`, `doc/user-manual.md`

- [x] **Step 1: Fix the user manual's overclaim**

In `doc/user-manual.md` §5, replace the "From the UI" paragraph (which currently claims controls exist that didn't, until this plan) with an accurate description of `NewRunDialog`: where the "New run" button lives, what Train vs. Tune mode do, and that `persistence` shows a `prior_column` field instead of tunable hyperparameters and can't be tuned.

- [x] **Step 2: Update `CLAUDE.md`**

Add `GET /models` to the `routes/` bullet list in Code layout, and note `DatasetDetailOut`/`columns` next to the existing `datasets.py` entry. Add a short decision note (matching the existing style) explaining why `GET /models` exists: it's the single source of truth the frontend reads instead of hardcoding a second copy of `MODEL_REGISTRY` — reference #51 as the failure mode this avoids.

- [x] **Step 3: Update `README.md`**

Add `GET /models` to the API reference table.

- [x] **Step 4: Verify and commit**

```bash
make check
git add CLAUDE.md README.md doc/user-manual.md
git commit -m "docs: sync docs with the training launch UI"
```

---

## Open questions for whoever picks this up

- `feature_columns`: this plan defaults to omitting it (server infers via `_resolve_features`) and only exposes an "advanced: customize" override if time allows in Task 3. If cut for scope, note that explicitly rather than silently dropping it.
- Optuna tuning can run long (`OPTUNA_STUDY_TIMEOUT_S`, default 600s) inside a single synchronous request. The dialog's submit button should show a pending state for the whole duration (same pattern as `QuestionBox`/`DatasetSidebar`), but a 600-second spinner is a rough UX edge this plan doesn't solve — worth its own follow-up issue if it turns out to matter in practice.
