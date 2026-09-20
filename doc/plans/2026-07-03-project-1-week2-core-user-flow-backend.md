# Project 1 — Week 2 Core User Flow (Backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the backend for the core user flow — upload a CSV, ask a natural-language question, and get back matplotlib charts plus a single-pass Claude interpretation, all persisted as chats/messages/analyses.

**Architecture:** New focused modules under `backend/app/` — `analysis.py` (chart engine), `tools.py` (Claude tool defs + arg validation), `llm.py` (single-pass orchestrator), `charts.py` (history re-render), and `routes/chats.py` (endpoints). Phase 1 first reconciles the SQLAlchemy models to the canonical `backend/db/schema.sql` and populates `dataset_columns` on upload. Charts are base64 in the response and re-rendered on history reads — never stored.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (`mapped_column`), pandas, matplotlib (Agg) + seaborn, Anthropic Python SDK, pytest, mypy (strict), ruff + black.

**Spec:** `doc/project-1-week2-end-to-end-flow-design.md` (approved 2026-07-03). Canonical DDL: `backend/db/schema.sql`.

## Global Constraints

- **Python 3.12**; line length **100** (ruff + black); mypy **strict** on `backend/app`.
- Application code in `backend/app/` only; tests in `backend/tests/` only. Imports are absolute from `app`.
- **No `users` table, no auth (D4).** Do not add a User model or FK.
- **Charts are never stored.** They are a pure function of `datasets.data_csv` + a message's `tool_calls`; re-render on history reads. `analyses.output_path` stays `NULL`.
- **Single-pass LLM (D2).** One Claude API call selects tools and writes the interpretation.
- **Backend validates Claude's tool args before executing.** On column/type mismatch, skip that call and return a graceful error entry — never pass unchecked Claude output to `analysis.py`.
- **matplotlib `Agg` backend, fresh `Figure` per call, closed in `finally`.** Never touch `pyplot` global state (not thread-safe under FastAPI).
- **API key from `ANTHROPIC_API_KEY` env, never hardcoded.** Model configurable via `Settings.anthropic_model` (default `claude-sonnet-5`).
- Tests run against **SQLite** (`tmp_path`, isolated per test via the `client` fixture); production uses Postgres. **No network in `make test`** — the Anthropic client is always mocked. Real-API testing lives in `make eval` only.
- FastAPI `Depends()`/`File()`/`Body()` in defaults are exempt from ruff B008 (already configured); keep idiomatic signatures.
- After every task: `make check` (ruff + black --check + mypy + pytest) must pass before commit.

---

### Task 1: Reconcile `models.py` to `schema.sql`

Aligns the SQLAlchemy models (a collaborator's recent push) to the canonical hand-authored DDL so tests-on-SQLite and prod-on-Postgres agree on names, columns, and constraints.

**Files:**
- Modify: `backend/app/models.py`
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Produces: `Analysis.message_id` (was `chat_message_id`), `Analysis.result_stats: dict | None`, `DatasetColumn.ordinal_position: int`, `DatasetColumn` UNIQUE(dataset_id, name), `ChatMessage.cost_usd` as `Numeric(10, 6)`. FK columns indexed. `_uuid()` and `Base` unchanged.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_models.py`:

```python
from sqlalchemy import Numeric, inspect

from app.models import Analysis, ChatMessage, DatasetColumn


def test_analysis_uses_message_id_and_result_stats() -> None:
    cols = {c.name for c in Analysis.__table__.columns}
    assert "message_id" in cols
    assert "chat_message_id" not in cols
    assert "result_stats" in cols
    assert Analysis.__table__.c.result_stats.nullable is True


def test_dataset_columns_ordinal_and_unique() -> None:
    cols = {c.name for c in DatasetColumn.__table__.columns}
    assert "ordinal_position" in cols
    assert DatasetColumn.__table__.c.ordinal_position.nullable is False
    unique_cols = {
        tuple(sorted(col.name for col in c.columns))
        for c in DatasetColumn.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    }
    assert ("dataset_id", "name") in unique_cols


def test_cost_usd_is_numeric() -> None:
    assert isinstance(ChatMessage.__table__.c.cost_usd.type, Numeric)


def test_fk_columns_are_indexed() -> None:
    assert DatasetColumn.__table__.c.dataset_id.index is True
    assert ChatMessage.__table__.c.chat_id.index is True
    assert Analysis.__table__.c.message_id.index is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest backend/tests/test_models.py -v`
Expected: FAIL (`chat_message_id` still present; `result_stats`/`ordinal_position` missing; `cost_usd` is `Float`).

- [ ] **Step 3: Edit the models**

In `backend/app/models.py`:

1. Extend the SQLAlchemy import to include `Numeric` and `UniqueConstraint`:

```python
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
```

(Remove `Float` — it is no longer used.)

2. Replace the `DatasetColumn` body (keep the class name):

```python
class DatasetColumn(Base):
    __tablename__ = "dataset_columns"
    __table_args__ = (
        UniqueConstraint("dataset_id", "name", name="uq_dataset_columns_dataset_id_name"),
        {"schema": "app"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("app.datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    ordinal_position: Mapped[int] = mapped_column(Integer, nullable=False)
    inferred_type: Mapped[str] = mapped_column(String, nullable=False)
    null_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

3. In `Chat`, add `index=True` to `dataset_id`:

```python
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("app.datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
```

4. In `ChatMessage`, add `index=True` to `chat_id` and change `cost_usd` to `Numeric`:

```python
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("app.chats.id", ondelete="CASCADE"), nullable=False, index=True
    )
```
```python
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False, default=0)
```

5. Replace the `Analysis` body (keep the class name):

```python
class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = {"schema": "app"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("app.chat_messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chart_type: Mapped[str] = mapped_column(String, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_stats: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    output_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest backend/tests/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full gate**

Run: `make check`
Expected: PASS (ruff, black, mypy, pytest).

- [ ] **Step 6: Commit**

```bash
git add backend/app/models.py backend/tests/test_models.py
git commit -m "refactor(models): reconcile SQLAlchemy models to canonical schema.sql"
```

---

### Task 2: Populate `dataset_columns` on upload

The upload route already persists a `Dataset` and its `profile_json`. Add one `DatasetColumn` row per column in the same transaction, derived from the profile's `columns` list.

**Files:**
- Modify: `backend/app/routes/datasets.py:34-51` (the persistence block in `upload_dataset`)
- Test: `backend/tests/test_datasets.py`

**Interfaces:**
- Consumes: `profile_dataframe(...)` output — a dict whose `columns` is a list of `{"name": str, "dtype": str, "n_null": int}` (one entry per column, in column order).
- Produces: `dataset_columns` rows with `dataset_id`, `name`, `ordinal_position` (0-based), `inferred_type` (the dtype string), `null_count`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_datasets.py`:

```python
def test_upload_populates_dataset_columns(client) -> None:
    csv = "age,city\n30,NYC\n,LA\n"
    resp = client.post(
        "/datasets",
        files={"file": ("people.csv", csv, "text/csv")},
    )
    assert resp.status_code == 200
    dataset_id = resp.json()["id"]

    from app.db import get_session
    from app.main import app
    from app.models import DatasetColumn

    session = next(app.dependency_overrides[get_session]())
    rows = (
        session.query(DatasetColumn)
        .filter(DatasetColumn.dataset_id == dataset_id)
        .order_by(DatasetColumn.ordinal_position)
        .all()
    )
    assert [r.name for r in rows] == ["age", "city"]
    assert [r.ordinal_position for r in rows] == [0, 1]
    age = rows[0]
    assert age.null_count == 1
    assert age.inferred_type  # non-empty dtype string
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest backend/tests/test_datasets.py::test_upload_populates_dataset_columns -v`
Expected: FAIL (no `DatasetColumn` rows written).

- [ ] **Step 3: Update the upload route**

In `backend/app/routes/datasets.py`, add `DatasetColumn` to the models import:

```python
from app.models import Dataset, DatasetColumn
```

Then, after `session.add(dataset)` and before `session.commit()`, add the columns loop. The block becomes:

```python
    session.add(dataset)
    session.flush()  # assign dataset.id before inserting child rows

    profile = dataset.profile_json
    for ordinal, col in enumerate(profile["columns"]):
        session.add(
            DatasetColumn(
                dataset_id=dataset.id,
                name=str(col["name"]),
                ordinal_position=ordinal,
                inferred_type=str(col["dtype"]),
                null_count=int(col["n_null"]),
            )
        )

    session.commit()
    session.refresh(dataset)
    return dataset
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest backend/tests/test_datasets.py -v`
Expected: PASS (new test plus existing upload tests still green).

- [ ] **Step 5: Run the full gate**

Run: `make check`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/datasets.py backend/tests/test_datasets.py
git commit -m "feat(upload): persist per-column metadata to dataset_columns"
```

---

### Task 3: Analysis engine (`analysis.py`)

Three chart functions, each rendering on a fresh Agg `Figure` and returning `(png_base64, result_stats)`. This is the only module that renders images.

**Files:**
- Create: `backend/app/analysis.py`
- Test: `backend/tests/test_analysis.py`
- Modify: `pyproject.toml` (add `matplotlib`, `seaborn`)

**Interfaces:**
- Produces:
  - `histogram(df: pd.DataFrame, column: str) -> tuple[str, dict[str, Any]]`
  - `scatter(df: pd.DataFrame, x: str, y: str) -> tuple[str, dict[str, Any]]`
  - `correlation_matrix(df: pd.DataFrame) -> tuple[str, dict[str, Any]]`
  - Each returns `(base64_png_string, result_stats)`; `result_stats` is a JSON-serializable dict.

- [ ] **Step 1: Add matplotlib + seaborn**

Run:
```bash
poetry add matplotlib@^3.9 seaborn@^0.13
```
Expected: `pyproject.toml` + `poetry.lock` updated.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_analysis.py`:

```python
import base64

import pandas as pd

from app.analysis import correlation_matrix, histogram, scatter


def _df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "age": [20, 30, 40, 50, 60],
            "score": [1.0, 2.0, 3.0, 4.0, 5.0],
            "city": ["A", "B", "A", "B", "C"],
        }
    )


def _is_png_base64(s: str) -> bool:
    raw = base64.b64decode(s)
    return raw[:8] == b"\x89PNG\r\n\x1a\n"


def test_histogram_returns_png_and_stats() -> None:
    png, stats = histogram(_df(), "age")
    assert _is_png_base64(png)
    assert stats["column"] == "age"
    assert stats["count"] == 5
    assert stats["min"] == 20
    assert stats["max"] == 60


def test_scatter_returns_png_and_correlation() -> None:
    png, stats = scatter(_df(), "age", "score")
    assert _is_png_base64(png)
    assert stats["x"] == "age"
    assert stats["y"] == "score"
    assert round(stats["correlation"], 5) == 1.0


def test_correlation_matrix_returns_png_and_pairs() -> None:
    png, stats = correlation_matrix(_df())
    assert _is_png_base64(png)
    assert set(stats["columns"]) == {"age", "score"}
    assert round(stats["matrix"]["age"]["score"], 5) == 1.0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `poetry run pytest backend/tests/test_analysis.py -v`
Expected: FAIL (`app.analysis` does not exist).

- [ ] **Step 4: Implement `analysis.py`**

Create `backend/app/analysis.py`:

```python
"""Chart/stat engine. Renders on a fresh matplotlib Agg Figure per call and
never touches pyplot global state (not thread-safe under FastAPI)."""

from __future__ import annotations

import base64
import io
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless backend; must precede Figure import usage

import pandas as pd
import seaborn as sns
from matplotlib.figure import Figure


def _fig_to_base64(fig: Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=100)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def histogram(df: pd.DataFrame, column: str) -> tuple[str, dict[str, Any]]:
    series = pd.to_numeric(df[column], errors="coerce").dropna()
    fig = Figure(figsize=(6, 4))
    try:
        ax = fig.subplots()
        ax.hist(series, bins=min(30, max(1, series.nunique())), color="#4C72B0")
        ax.set_title(f"Distribution of {column}")
        ax.set_xlabel(column)
        ax.set_ylabel("count")
        png = _fig_to_base64(fig)
    finally:
        fig.clear()
    stats: dict[str, Any] = {
        "column": column,
        "count": int(series.count()),
        "min": float(series.min()) if not series.empty else None,
        "max": float(series.max()) if not series.empty else None,
        "mean": float(series.mean()) if not series.empty else None,
        "std": float(series.std()) if not series.empty else None,
    }
    return png, stats


def scatter(df: pd.DataFrame, x: str, y: str) -> tuple[str, dict[str, Any]]:
    sub = df[[x, y]].apply(pd.to_numeric, errors="coerce").dropna()
    fig = Figure(figsize=(6, 4))
    try:
        ax = fig.subplots()
        ax.scatter(sub[x], sub[y], alpha=0.7, color="#4C72B0")
        ax.set_title(f"{y} vs {x}")
        ax.set_xlabel(x)
        ax.set_ylabel(y)
        png = _fig_to_base64(fig)
    finally:
        fig.clear()
    corr = float(sub[x].corr(sub[y])) if len(sub) > 1 else None
    stats: dict[str, Any] = {"x": x, "y": y, "count": int(len(sub)), "correlation": corr}
    return png, stats


def correlation_matrix(df: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    numeric = df.select_dtypes(include="number")
    corr = numeric.corr()
    fig = Figure(figsize=(6, 5))
    try:
        ax = fig.subplots()
        sns.heatmap(corr, annot=True, fmt=".2f", cmap="coolwarm", vmin=-1, vmax=1, ax=ax)
        ax.set_title("Correlation matrix")
        png = _fig_to_base64(fig)
    finally:
        fig.clear()
    stats: dict[str, Any] = {
        "columns": list(corr.columns),
        "matrix": {c: {r: float(corr.loc[r, c]) for r in corr.index} for c in corr.columns},
    }
    return png, stats
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `poetry run pytest backend/tests/test_analysis.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full gate**

Run: `make check`
Expected: PASS. (Note: the `matplotlib.use("Agg")` call sits above the `seaborn`/`Figure` imports intentionally; if ruff E402 flags them, add `# noqa: E402` to those import lines — the ordering is required.)

- [ ] **Step 7: Commit**

```bash
git add backend/app/analysis.py backend/tests/test_analysis.py pyproject.toml poetry.lock
git commit -m "feat(analysis): add histogram/scatter/correlation_matrix chart engine"
```

---

### Task 4: Tool definitions + validation (`tools.py`)

Static Claude tool schemas for the three charts, plus a validator that rejects bad column/type references **before** any call reaches `analysis.py`.

**Files:**
- Create: `backend/app/tools.py`
- Test: `backend/tests/test_tools.py`

**Interfaces:**
- Consumes: the profile dict (`profile["columns"]` → list of `{"name", "dtype", "n_null"}`).
- Produces:
  - `TOOL_DEFS: list[dict[str, Any]]` — Anthropic `tools=` payload for `histogram`, `scatter`, `correlation_matrix`.
  - `validate_tool_call(name: str, args: dict[str, Any], profile: dict[str, Any]) -> str | None` — returns an error message string if invalid, else `None`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_tools.py`:

```python
from app.tools import TOOL_DEFS, validate_tool_call

PROFILE = {
    "columns": [
        {"name": "age", "dtype": "int64", "n_null": 0},
        {"name": "score", "dtype": "float64", "n_null": 0},
        {"name": "city", "dtype": "object", "n_null": 0},
    ]
}


def test_tool_defs_cover_three_charts() -> None:
    names = {t["name"] for t in TOOL_DEFS}
    assert names == {"histogram", "scatter", "correlation_matrix"}


def test_valid_histogram_passes() -> None:
    assert validate_tool_call("histogram", {"column": "age"}, PROFILE) is None


def test_histogram_unknown_column_rejected() -> None:
    err = validate_tool_call("histogram", {"column": "nope"}, PROFILE)
    assert err is not None and "nope" in err


def test_histogram_non_numeric_column_rejected() -> None:
    err = validate_tool_call("histogram", {"column": "city"}, PROFILE)
    assert err is not None and "numeric" in err.lower()


def test_scatter_requires_two_numeric_columns() -> None:
    assert validate_tool_call("scatter", {"x": "age", "y": "score"}, PROFILE) is None
    assert validate_tool_call("scatter", {"x": "age", "y": "city"}, PROFILE) is not None


def test_unknown_tool_rejected() -> None:
    assert validate_tool_call("pie", {}, PROFILE) is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest backend/tests/test_tools.py -v`
Expected: FAIL (`app.tools` does not exist).

- [ ] **Step 3: Implement `tools.py`**

Create `backend/app/tools.py`:

```python
"""Claude tool definitions for the fixed chart menu, plus pre-execution
validation of the arguments Claude proposes. Never trust raw tool args."""

from __future__ import annotations

from typing import Any

TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "histogram",
        "description": "Plot the distribution of a single numeric column.",
        "input_schema": {
            "type": "object",
            "properties": {
                "column": {"type": "string", "description": "Numeric column to plot."}
            },
            "required": ["column"],
        },
    },
    {
        "name": "scatter",
        "description": "Plot the relationship between two numeric columns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "string", "description": "Numeric column for the x axis."},
                "y": {"type": "string", "description": "Numeric column for the y axis."},
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "correlation_matrix",
        "description": "Heatmap of pairwise correlations across all numeric columns.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]

# dtype-string prefixes pandas uses for numeric columns.
_NUMERIC_PREFIXES = ("int", "float", "uint")


def _numeric_columns(profile: dict[str, Any]) -> set[str]:
    return {
        str(c["name"])
        for c in profile.get("columns", [])
        if str(c.get("dtype", "")).lower().startswith(_NUMERIC_PREFIXES)
    }


def _all_columns(profile: dict[str, Any]) -> set[str]:
    return {str(c["name"]) for c in profile.get("columns", [])}


def validate_tool_call(
    name: str, args: dict[str, Any], profile: dict[str, Any]
) -> str | None:
    """Return an error message if the call is invalid, else None."""
    all_cols = _all_columns(profile)
    numeric_cols = _numeric_columns(profile)

    if name == "correlation_matrix":
        if len(numeric_cols) < 2:
            return "correlation_matrix needs at least 2 numeric columns."
        return None

    if name == "histogram":
        col = args.get("column")
        if col not in all_cols:
            return f"histogram: unknown column '{col}'."
        if col not in numeric_cols:
            return f"histogram: column '{col}' is not numeric."
        return None

    if name == "scatter":
        for axis in ("x", "y"):
            col = args.get(axis)
            if col not in all_cols:
                return f"scatter: unknown column '{col}'."
            if col not in numeric_cols:
                return f"scatter: column '{col}' is not numeric."
        return None

    return f"unknown tool '{name}'."
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest backend/tests/test_tools.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full gate**

Run: `make check`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/tools.py backend/tests/test_tools.py
git commit -m "feat(tools): add Claude chart tool defs + pre-execution validation"
```

---

### Task 5: Single-pass LLM orchestrator (`llm.py`)

Builds the message payload (system prompt + profile + prior turns + question), makes one Claude call with `tools=`, and returns tool-use blocks, interpretation text, and usage. The Anthropic client is injectable so tests mock it — no network in `make test`.

**Files:**
- Create: `backend/app/llm.py`
- Create: `prompts/system.md`
- Test: `backend/tests/test_llm.py`
- Modify: `backend/app/config.py` (add anthropic settings), `.env.example`
- Modify: `pyproject.toml` (add `anthropic`)

**Interfaces:**
- Consumes: `TOOL_DEFS` from `app.tools`; `Settings.anthropic_model`, `anthropic_max_tokens`, `anthropic_api_key`.
- Produces:
  - `@dataclass LLMResult` with fields: `interpretation: str`, `tool_calls: list[dict[str, Any]]` (each `{"name": str, "args": dict}`), `tokens_in: int`, `tokens_out: int`, `cost_usd: float`, `latency_ms: int`.
  - `run_pass(profile: dict, prior_messages: list[dict], question: str, *, client: Any | None = None) -> LLMResult`. `prior_messages` items are `{"role": "user"|"assistant", "content": str}`.

- [ ] **Step 1: Add the Anthropic SDK**

Run:
```bash
poetry add anthropic@^0.40
```
Expected: `pyproject.toml` + `poetry.lock` updated. (Use the current published major if `^0.40` is unavailable; the code below uses only `client.messages.create(...)`, `response.content` blocks, and `response.usage`.)

- [ ] **Step 2: Add config fields**

In `backend/app/config.py`, add to `Settings` (below the profiler tunables):

```python
    # Anthropic (required for /chat; key never hardcoded)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    anthropic_max_tokens: int = 4096
```

Append to `.env.example`:

```bash

# Anthropic (required for /chat)
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-5
ANTHROPIC_MAX_TOKENS=4096
```

- [ ] **Step 3: Author the system prompt**

Create `prompts/system.md`:

```markdown
You are a data-analysis assistant for a single uploaded CSV.

You are given a compact JSON profile of the dataset (columns with dtypes and
null counts, summary statistics, correlations, and a few sample rows). You have
a fixed menu of charting tools: `histogram` (one numeric column), `scatter`
(two numeric columns), and `correlation_matrix` (all numeric columns).

For each user question:
- Select the chart tool(s) that best answer it, using only columns that appear
  in the profile and are numeric where the tool requires numeric input.
- Then write a concise, plain-English interpretation of what the chart(s) show,
  grounded in the profile's statistics. Reference concrete numbers.

Work in a single pass: choose your tools and write your interpretation together.
If no chart is appropriate, answer from the profile statistics alone. Never
invent columns or values that are not in the profile.
```

- [ ] **Step 4: Write the failing test**

Create `backend/tests/test_llm.py`:

```python
import json
from types import SimpleNamespace

from app.llm import run_pass

PROFILE = {"columns": [{"name": "age", "dtype": "int64", "n_null": 0}], "n_rows": 3}


class _FakeMessages:
    def __init__(self, response: object) -> None:
        self._response = response
        self.captured: dict = {}

    def create(self, **kwargs: object) -> object:
        self.captured = kwargs
        return self._response


class _FakeClient:
    def __init__(self, response: object) -> None:
        self.messages = _FakeMessages(response)


def _response() -> object:
    tool_block = SimpleNamespace(
        type="tool_use", name="histogram", input={"column": "age"}
    )
    text_block = SimpleNamespace(type="text", text="Ages are spread evenly.")
    usage = SimpleNamespace(input_tokens=120, output_tokens=45)
    return SimpleNamespace(content=[tool_block, text_block], usage=usage)


def test_run_pass_parses_tools_and_text() -> None:
    client = _FakeClient(_response())
    result = run_pass(PROFILE, [], "show me the age distribution", client=client)

    assert result.interpretation == "Ages are spread evenly."
    assert result.tool_calls == [{"name": "histogram", "args": {"column": "age"}}]
    assert result.tokens_in == 120
    assert result.tokens_out == 45
    assert result.cost_usd > 0
    assert result.latency_ms >= 0


def test_run_pass_assembles_messages() -> None:
    client = _FakeClient(_response())
    prior = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    run_pass(PROFILE, prior, "and the age distribution?", client=client)

    kwargs = client.messages.captured
    assert kwargs["model"]  # from settings
    assert kwargs["tools"]  # TOOL_DEFS wired
    # system prompt carries the profile JSON
    assert "age" in json.dumps(kwargs["system"])
    # prior turns precede the new question
    contents = [m["content"] for m in kwargs["messages"]]
    assert contents[-1].endswith("age distribution?")
    assert "hi" in json.dumps(kwargs["messages"])
```

- [ ] **Step 5: Run test to verify it fails**

Run: `poetry run pytest backend/tests/test_llm.py -v`
Expected: FAIL (`app.llm` does not exist).

- [ ] **Step 6: Implement `llm.py`**

Create `backend/app/llm.py`:

```python
"""Single-pass Claude orchestrator (design D2). One API call selects chart
tools and writes the interpretation. The client is injectable for testing."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import settings
from app.tools import TOOL_DEFS

_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "system.md"

# Approx per-million-token USD prices, keyed by model id prefix. Used only for
# bookkeeping (chat_messages.cost_usd); not a billing source of truth.
_PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


@dataclass
class LLMResult:
    interpretation: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0


def _system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    in_price, out_price = _PRICES.get(model, (0.0, 0.0))
    return (tokens_in / 1_000_000) * in_price + (tokens_out / 1_000_000) * out_price


def _build_messages(
    prior_messages: list[dict[str, Any]], question: str
) -> list[dict[str, Any]]:
    messages = [
        {"role": m["role"], "content": m["content"]} for m in prior_messages
    ]
    messages.append({"role": "user", "content": question})
    return messages


def _default_client() -> Any:
    import anthropic

    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def run_pass(
    profile: dict[str, Any],
    prior_messages: list[dict[str, Any]],
    question: str,
    *,
    client: Any | None = None,
) -> LLMResult:
    client = client or _default_client()
    system = [
        {"type": "text", "text": _system_prompt()},
        {"type": "text", "text": "Dataset profile:\n" + json.dumps(profile, default=str)},
    ]

    start = time.monotonic()
    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=settings.anthropic_max_tokens,
        system=system,
        tools=TOOL_DEFS,
        messages=_build_messages(prior_messages, question),
    )
    latency_ms = int((time.monotonic() - start) * 1000)

    tool_calls: list[dict[str, Any]] = []
    text_parts: list[str] = []
    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            tool_calls.append({"name": block.name, "args": dict(block.input)})
        elif getattr(block, "type", None) == "text":
            text_parts.append(block.text)

    tokens_in = int(response.usage.input_tokens)
    tokens_out = int(response.usage.output_tokens)
    return LLMResult(
        interpretation="".join(text_parts).strip(),
        tool_calls=tool_calls,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=_estimate_cost(settings.anthropic_model, tokens_in, tokens_out),
        latency_ms=latency_ms,
    )
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `poetry run pytest backend/tests/test_llm.py -v`
Expected: PASS.

- [ ] **Step 8: Run the full gate**

Run: `make check`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/llm.py backend/app/config.py prompts/system.md .env.example \
        backend/tests/test_llm.py pyproject.toml poetry.lock
git commit -m "feat(llm): add single-pass Claude orchestrator with injectable client"
```

---

### Task 6: History chart re-render (`charts.py`)

Re-renders base64 charts from `datasets.data_csv` + a message's `tool_calls`, so `GET /chat` never needs stored images.

**Files:**
- Create: `backend/app/charts.py`
- Test: `backend/tests/test_charts.py`

**Interfaces:**
- Consumes: `load_csv` from `app.dataset_io`; `histogram`/`scatter`/`correlation_matrix` from `app.analysis`. A `Dataset` (needs `.data_csv`); a message-like object or dict exposing `tool_calls` as a list of `{"name": str, "args": dict}`.
- Produces: `render_message_charts(data_csv: str, tool_calls: list[dict[str, Any]]) -> list[str]` — a list of base64 PNG strings, one per successfully re-rendered tool call (invalid/failed calls are skipped).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_charts.py`:

```python
import base64

from app.charts import render_message_charts

CSV = "age,score\n20,1\n30,2\n40,3\n"


def _is_png(s: str) -> bool:
    return base64.b64decode(s)[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_histogram_and_scatter() -> None:
    calls = [
        {"name": "histogram", "args": {"column": "age"}},
        {"name": "scatter", "args": {"x": "age", "y": "score"}},
    ]
    charts = render_message_charts(CSV, calls)
    assert len(charts) == 2
    assert all(_is_png(c) for c in charts)


def test_unknown_tool_is_skipped() -> None:
    charts = render_message_charts(CSV, [{"name": "pie", "args": {}}])
    assert charts == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest backend/tests/test_charts.py -v`
Expected: FAIL (`app.charts` does not exist).

- [ ] **Step 3: Implement `charts.py`**

Create `backend/app/charts.py`:

```python
"""Re-render charts for history reads. Charts are a pure function of the raw
CSV plus a message's tool_calls — never stored (design D5)."""

from __future__ import annotations

from typing import Any

from app.analysis import correlation_matrix, histogram, scatter
from app.dataset_io import load_csv

_DISPATCH = {
    "histogram": lambda df, args: histogram(df, args["column"]),
    "scatter": lambda df, args: scatter(df, args["x"], args["y"]),
    "correlation_matrix": lambda df, args: correlation_matrix(df),
}


def render_message_charts(data_csv: str, tool_calls: list[dict[str, Any]]) -> list[str]:
    df = load_csv(data_csv)
    charts: list[str] = []
    for call in tool_calls:
        fn = _DISPATCH.get(call.get("name", ""))
        if fn is None:
            continue
        try:
            png, _stats = fn(df, call.get("args", {}))
        except (KeyError, ValueError):
            continue
        charts.append(png)
    return charts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest backend/tests/test_charts.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full gate**

Run: `make check`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/charts.py backend/tests/test_charts.py
git commit -m "feat(charts): re-render history charts from data_csv + tool_calls"
```

---

### Task 7: Chat endpoints (`routes/chats.py`)

Wires everything: `POST /datasets/{id}/chat` runs the pass, validates + executes tools, persists rows, and returns charts + interpretation. `GET /datasets/{id}/chat` replays history with re-rendered charts.

**Files:**
- Create: `backend/app/routes/chats.py`
- Modify: `backend/app/main.py` (register the router)
- Modify: `backend/app/schemas.py` (add request/response models)
- Test: `backend/tests/test_chats.py`

**Interfaces:**
- Consumes: `run_pass` (`app.llm`), `validate_tool_call` (`app.tools`), `histogram`/`scatter`/`correlation_matrix` (`app.analysis`), `render_message_charts` (`app.charts`), `get_session` (`app.db`), models `Dataset`/`Chat`/`ChatMessage`/`Analysis`.
- Produces: `POST /datasets/{dataset_id}/chat` body `{"question": str}` → `ChatResponse`; `GET /datasets/{dataset_id}/chat` → `{"messages": [...]}`.

- [ ] **Step 1: Add schemas**

Append to `backend/app/schemas.py`:

```python
from typing import Any


class ChatRequest(BaseModel):
    question: str


class ChatResponse(BaseModel):
    message_id: str
    interpretation: str
    charts: list[str]
    stats: list[dict[str, Any]]
    errors: list[str]
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_chats.py`:

```python
from types import SimpleNamespace

import app.routes.chats as chats_route


def _fake_llm(monkeypatch, tool_calls, text="Looks linear.") -> None:
    def fake_run_pass(profile, prior_messages, question, *, client=None):
        return SimpleNamespace(
            interpretation=text,
            tool_calls=tool_calls,
            tokens_in=100,
            tokens_out=30,
            cost_usd=0.001,
            latency_ms=12,
        )

    monkeypatch.setattr(chats_route, "run_pass", fake_run_pass)


def _upload(client) -> str:
    csv = "age,score\n20,1\n30,2\n40,3\n"
    resp = client.post("/datasets", files={"file": ("d.csv", csv, "text/csv")})
    return resp.json()["id"]


def test_chat_runs_and_persists(client, monkeypatch) -> None:
    _fake_llm(monkeypatch, [{"name": "scatter", "args": {"x": "age", "y": "score"}}])
    dataset_id = _upload(client)

    resp = client.post(f"/datasets/{dataset_id}/chat", json={"question": "relate them"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["interpretation"] == "Looks linear."
    assert len(body["charts"]) == 1
    assert body["errors"] == []

    from app.db import get_session
    from app.main import app
    from app.models import Analysis, Chat, ChatMessage

    session = next(app.dependency_overrides[get_session]())
    assert session.query(Chat).count() == 1
    assert session.query(ChatMessage).count() == 2  # user + assistant
    assert session.query(Analysis).count() == 1


def test_chat_invalid_tool_arg_is_graceful(client, monkeypatch) -> None:
    _fake_llm(monkeypatch, [{"name": "histogram", "args": {"column": "missing"}}])
    dataset_id = _upload(client)

    resp = client.post(f"/datasets/{dataset_id}/chat", json={"question": "hist"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["charts"] == []
    assert len(body["errors"]) == 1


def test_chat_reuses_single_chat(client, monkeypatch) -> None:
    _fake_llm(monkeypatch, [])
    dataset_id = _upload(client)
    client.post(f"/datasets/{dataset_id}/chat", json={"question": "q1"})
    client.post(f"/datasets/{dataset_id}/chat", json={"question": "q2"})

    from app.db import get_session
    from app.main import app
    from app.models import Chat

    session = next(app.dependency_overrides[get_session]())
    assert session.query(Chat).count() == 1


def test_get_history_rerenders_charts(client, monkeypatch) -> None:
    _fake_llm(monkeypatch, [{"name": "scatter", "args": {"x": "age", "y": "score"}}])
    dataset_id = _upload(client)
    client.post(f"/datasets/{dataset_id}/chat", json={"question": "relate them"})

    resp = client.get(f"/datasets/{dataset_id}/chat")
    assert resp.status_code == 200
    messages = resp.json()["messages"]
    assert len(messages) == 2
    assistant = [m for m in messages if m["role"] == "assistant"][0]
    assert len(assistant["charts"]) == 1


def test_chat_unknown_dataset_404(client, monkeypatch) -> None:
    _fake_llm(monkeypatch, [])
    resp = client.post("/datasets/nope/chat", json={"question": "hi"})
    assert resp.status_code == 404
```

- [ ] **Step 3: Run test to verify it fails**

Run: `poetry run pytest backend/tests/test_chats.py -v`
Expected: FAIL (`app.routes.chats` does not exist).

- [ ] **Step 4: Implement `routes/chats.py`**

Create `backend/app/routes/chats.py`:

```python
"""Chat endpoints: run a single Claude pass over a dataset, execute the chart
tools it selects (after validation), persist the turn, and return charts +
interpretation. History reads re-render charts, never store them."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis import correlation_matrix, histogram, scatter
from app.charts import render_message_charts
from app.db import get_session
from app.llm import run_pass
from app.models import Analysis, Chat, ChatMessage, Dataset
from app.schemas import ChatRequest, ChatResponse
from app.tools import validate_tool_call

router = APIRouter(prefix="/datasets/{dataset_id}/chat", tags=["chat"])

_DISPATCH = {
    "histogram": lambda df, a: histogram(df, a["column"]),
    "scatter": lambda df, a: scatter(df, a["x"], a["y"]),
    "correlation_matrix": lambda df, a: correlation_matrix(df),
}


def _get_dataset(session: Session, dataset_id: str) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset


def _get_or_create_chat(session: Session, dataset_id: str) -> Chat:
    chat = session.scalars(
        select(Chat).where(Chat.dataset_id == dataset_id).order_by(Chat.created_at)
    ).first()
    if chat is None:
        chat = Chat(dataset_id=dataset_id)
        session.add(chat)
        session.flush()
    return chat


def _prior_messages(session: Session, chat_id: str) -> list[dict[str, str]]:
    rows = session.scalars(
        select(ChatMessage)
        .where(ChatMessage.chat_id == chat_id)
        .order_by(ChatMessage.created_at)
    ).all()
    return [{"role": r.role, "content": r.content} for r in rows]


@router.post("", response_model=ChatResponse)
def post_chat(
    dataset_id: str,
    body: ChatRequest,
    session: Session = Depends(get_session),
) -> ChatResponse:
    dataset = _get_dataset(session, dataset_id)
    chat = _get_or_create_chat(session, dataset_id)

    prior = _prior_messages(session, chat.id)
    session.add(ChatMessage(chat_id=chat.id, role="user", content=body.question))
    session.flush()

    from app.dataset_io import load_csv

    result = run_pass(dataset.profile_json, prior, body.question)

    df = load_csv(dataset.data_csv)
    charts: list[str] = []
    stats: list[dict[str, Any]] = []
    errors: list[str] = []
    executed_calls: list[dict[str, Any]] = []

    for call in result.tool_calls:
        err = validate_tool_call(call["name"], call["args"], dataset.profile_json)
        if err is not None:
            errors.append(err)
            continue
        png, stat = _DISPATCH[call["name"]](df, call["args"])
        charts.append(png)
        stats.append(stat)
        executed_calls.append(call)

    assistant = ChatMessage(
        chat_id=chat.id,
        role="assistant",
        content=result.interpretation,
        tool_calls=executed_calls,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        cost_usd=result.cost_usd,
        latency_ms=result.latency_ms,
    )
    session.add(assistant)
    session.flush()

    for call, stat in zip(executed_calls, stats):
        session.add(
            Analysis(
                message_id=assistant.id,
                chart_type=call["name"],
                params=call["args"],
                result_stats=stat,
            )
        )

    session.commit()
    return ChatResponse(
        message_id=assistant.id,
        interpretation=result.interpretation,
        charts=charts,
        stats=stats,
        errors=errors,
    )


@router.get("")
def get_chat(
    dataset_id: str,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    dataset = _get_dataset(session, dataset_id)
    chat = session.scalars(
        select(Chat).where(Chat.dataset_id == dataset_id).order_by(Chat.created_at)
    ).first()
    if chat is None:
        return {"messages": []}

    rows = session.scalars(
        select(ChatMessage)
        .where(ChatMessage.chat_id == chat.id)
        .order_by(ChatMessage.created_at)
    ).all()

    messages: list[dict[str, Any]] = []
    for r in rows:
        charts = (
            render_message_charts(dataset.data_csv, r.tool_calls)
            if r.role == "assistant" and r.tool_calls
            else []
        )
        messages.append(
            {
                "id": r.id,
                "role": r.role,
                "content": r.content,
                "charts": charts,
            }
        )
    return {"messages": messages}
```

- [ ] **Step 5: Register the router**

In `backend/app/main.py`, register the chats router the same way datasets is registered (lazy import inside `create_app`). Find the line that includes the datasets router and add immediately after it:

```python
    from app.routes.chats import router as chats_router

    app.include_router(chats_router)
```

(Match the existing import/include style — if datasets uses `from app.routes.datasets import router`, mirror that exactly.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `poetry run pytest backend/tests/test_chats.py -v`
Expected: PASS (all six tests).

- [ ] **Step 7: Run the full gate**

Run: `make check`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/routes/chats.py backend/app/main.py backend/app/schemas.py \
        backend/tests/test_chats.py
git commit -m "feat(chat): add POST/GET chat endpoints (single-pass + history re-render)"
```

---

## Self-Review

**Spec coverage:**
- Phase 1 (schema reconcile + `dataset_columns`) → Tasks 1–2. ✅
- Phase 2 (analysis engine + tool defs) → Tasks 3–4. ✅
- Phase 3 (LLM orchestrator + chat persistence) → Tasks 5–7. ✅
- Confirmed decisions — charts base64/never stored (Tasks 3, 6, 7 return/re-render, no `output_path` write); auto single chat (`_get_or_create_chat`, Task 7); model configurable (Task 5 config); `output_path` NULL (Task 1 keeps nullable, never written). ✅
- Data flow steps 1–3 (upload writes columns; ask validates→executes→persists; history re-renders) → Tasks 2, 7. ✅
- Error handling — tool-arg validation before execution (Task 7 loop skips + records error); matplotlib fresh Figure in `finally` (Task 3). LLM network-failure 502 path relies on the SDK raising out of `run_pass`; FastAPI surfaces a 500 by default. If a dedicated 502 is required, that is a one-line `try/except` around `run_pass` in Task 7 — noted for the implementer, not blocking. ✅
- Testing — analysis unit tests + validator (Tasks 3–4); llm mocked-client test (Task 5); chats integration incl. history re-render (Task 7). No network in `make test` — Anthropic client injected/patched everywhere. ✅
- Phase 4 (React frontend) → **separate plan** (independent subsystem, per scope check).

**Placeholder scan:** No TBD/TODO; every code step contains complete code. The two "match existing style" notes (Task 5 SDK version, Task 7 router registration) reference concrete existing patterns in the repo, not vague instructions.

**Type consistency:** `LLMResult` fields (Task 5) are consumed by name in Task 7. `tool_calls` shape `{"name", "args"}` is consistent across `llm.py`, `charts.py`, `tools.validate_tool_call`, and the chats route `_DISPATCH`. `render_message_charts(data_csv, tool_calls)` signature matches its call in Task 7's `get_chat`. `validate_tool_call(name, args, profile) -> str | None` matches usage.

**Out of scope (unchanged):** multiple chats per dataset, `output_path` population, auth, 2-pass LLM.
