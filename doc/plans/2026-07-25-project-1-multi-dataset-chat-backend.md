# Multi-Dataset Chat — Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a chat span multiple datasets — existing per-dataset tools (`histogram`,
`scatter`, `correlation_matrix`) gain a `dataset_id` argument, and a new `compare`
tool does a lightweight key-based join across exactly two of the chat's datasets.

**Architecture:** `Chat` becomes a first-class resource created over a list of
already-uploaded `Dataset` ids (new `chat_datasets` join table). `POST /chats` /
`POST /chats/{id}/messages` / `GET /chats/{id}` replace the old
`/datasets/{dataset_id}/chat` routes. The tool schema, validation, analysis
engine, chart dispatch, and LLM prompt assembly all thread a `dataset_id` (or
`dataset_a_id`/`dataset_b_id`) through instead of assuming one dataframe.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, pandas, matplotlib (`Agg`), pytest,
Anthropic SDK (mocked in tests via an injectable client).

**Related design doc:** `doc/project-1-multi-dataset-chat-design.md` (approved).
This plan covers backend only — a separate frontend plan follows the repo's
established backend/frontend split (see `doc/plans/2026-07-04-project-1-week2-frontend.md`
for precedent).

## Global Constraints

- Backend application code lives in `backend/app/` only; tests in `backend/tests/` only.
- Imports are absolute from `app` (e.g. `from app.profiler import profile_dataframe`).
- Line length **100** (ruff + black both configured to 100).
- mypy is **strict** on `backend/app` — every new/changed function needs full type hints.
- No `users` table, no auth (D4) — do not add a `User` model or FK.
- Charts are never stored — always re-derived from `data_csv` + a message's `tool_calls`.
- Backend validates Claude's tool args before executing — never pass raw Claude
  output to the analysis functions unchecked; invalid calls become entries in the
  response's `errors: list[str]`, never an HTTP error mid-turn.
- matplotlib: `Agg` backend, fresh `Figure` per call, never touch `pyplot` global state.
- Run `poetry run pytest <file> -v` after every code step; run `make check` (lint +
  format-check + type-check + test) before the final commit of each task.

---

### Task 1: `ChatDataset` join table, remove `Chat.dataset_id`

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/tests/test_models.py`

**Interfaces:**
- Produces: `ChatDataset` model — `id: str`, `chat_id: str`, `dataset_id: str`,
  `ordinal_position: int`, `created_at: datetime`. `Chat` no longer has `dataset_id`.

- [ ] **Step 1: Write the failing tests**

Update `test_chat_message_defaults` (it currently does `Chat(dataset_id=dataset.id)`,
which will no longer compile once `dataset_id` is removed) and add two new tests.
Replace the whole file's `Chat`/`ChatDataset` usage:

```python
from app.models import Analysis, Base, Chat, ChatDataset, ChatMessage, Dataset, DatasetColumn
from sqlalchemy import Numeric, create_engine, select
from sqlalchemy.orm import sessionmaker


def _session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}", future=True).execution_options(
        schema_translate_map={"app": None}
    )

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_dataset_persists_profile_and_csv(tmp_path):
    session = _session(tmp_path)
    dataset = Dataset(
        name="sales.csv",
        n_rows=3,
        n_cols=2,
        profile_json={"n_rows": 3, "columns": ["a", "b"]},
        data_csv="a,b\n1,2\n3,4\n5,6\n",
    )
    session.add(dataset)
    session.commit()

    loaded = session.scalar(select(Dataset).where(Dataset.name == "sales.csv"))
    assert loaded is not None
    assert loaded.profile_json["n_rows"] == 3
    assert loaded.data_csv == "a,b\n1,2\n3,4\n5,6\n"


def test_chat_message_defaults(tmp_path):
    session = _session(tmp_path)
    dataset = Dataset(name="d.csv", n_rows=1, n_cols=1, profile_json={}, data_csv="x\n1\n")
    session.add(dataset)
    session.flush()
    chat = Chat()
    session.add(chat)
    session.flush()
    session.add(ChatDataset(chat_id=chat.id, dataset_id=dataset.id, ordinal_position=0))
    msg = ChatMessage(chat_id=chat.id, role="user", content="hello")
    session.add(msg)
    session.commit()

    assert msg.tool_calls == []
    assert msg.tokens_in == 0
    assert msg.cost_usd == 0.0
    assert msg.latency_ms == 0


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


def test_chat_datasets_ordinal_and_unique() -> None:
    cols = {c.name for c in ChatDataset.__table__.columns}
    assert "ordinal_position" in cols
    assert ChatDataset.__table__.c.ordinal_position.nullable is False
    unique_cols = {
        tuple(sorted(col.name for col in c.columns))
        for c in ChatDataset.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    }
    assert ("chat_id", "dataset_id") in unique_cols


def test_chat_no_longer_has_dataset_id() -> None:
    assert "dataset_id" not in {c.name for c in Chat.__table__.columns}


def test_cost_usd_is_numeric() -> None:
    assert isinstance(ChatMessage.__table__.c.cost_usd.type, Numeric)


def test_fk_columns_are_indexed() -> None:
    assert DatasetColumn.__table__.c.dataset_id.index is True
    assert ChatMessage.__table__.c.chat_id.index is True
    assert Analysis.__table__.c.message_id.index is True
    assert ChatDataset.__table__.c.chat_id.index is True
    assert ChatDataset.__table__.c.dataset_id.index is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest backend/tests/test_models.py -v`
Expected: FAIL — `Chat() got an unexpected keyword argument` gone (that's fine, it's
now `Chat()` with no args) but `ChatDataset` import fails: `ImportError: cannot
import name 'ChatDataset' from 'app.models'`.

- [ ] **Step 3: Modify `Chat` and add `ChatDataset` in `backend/app/models.py`**

Replace the existing `Chat` class:

```python
class Chat(Base):
    __tablename__ = "chats"
    __table_args__ = {"schema": "app"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ChatDataset(Base):
    __tablename__ = "chat_datasets"
    __table_args__ = (
        UniqueConstraint("chat_id", "dataset_id", name="uq_chat_datasets_chat_id_dataset_id"),
        {"schema": "app"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("app.chats.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("app.datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal_position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

Place `ChatDataset` right after `Chat` and before `ChatMessage` (matches the file's
existing top-to-bottom dependency order: `Dataset` → `DatasetColumn` → `Chat` →
`ChatDataset` → `ChatMessage` → `Analysis`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest backend/tests/test_models.py -v`
Expected: PASS (all tests green)

- [ ] **Step 5: Type-check and commit**

Run: `poetry run mypy backend/app`
Expected: no errors

```bash
git add backend/app/models.py backend/tests/test_models.py
git commit -m "feat(backend): add ChatDataset join table, drop Chat.dataset_id"
```

---

### Task 2: `dataset_id` argument on existing tools

**Files:**
- Modify: `backend/app/tools.py`
- Modify: `backend/tests/test_tools.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `validate_tool_call(name: str, args: dict, profiles: dict[str, dict]) -> str | None`
  — signature changes from a single `profile: dict` to `profiles: dict[str, dict]`
  keyed by `dataset_id`. Later tasks (charts dispatch, chats route) call this new
  signature.

- [ ] **Step 1: Write the failing tests**

Replace `backend/tests/test_tools.py` in full:

```python
from app.tools import TOOL_DEFS, validate_tool_call

PROFILES = {
    "ds1": {
        "columns": [
            {"name": "age", "dtype": "int64", "n_null": 0},
            {"name": "score", "dtype": "float64", "n_null": 0},
            {"name": "city", "dtype": "object", "n_null": 0},
        ]
    }
}


def test_tool_defs_cover_three_charts() -> None:
    names = {t["name"] for t in TOOL_DEFS}
    assert names == {"histogram", "scatter", "correlation_matrix"}


def test_valid_histogram_passes() -> None:
    args = {"dataset_id": "ds1", "column": "age"}
    assert validate_tool_call("histogram", args, PROFILES) is None


def test_histogram_unknown_column_rejected() -> None:
    args = {"dataset_id": "ds1", "column": "nope"}
    err = validate_tool_call("histogram", args, PROFILES)
    assert err is not None and "nope" in err


def test_histogram_non_numeric_column_rejected() -> None:
    args = {"dataset_id": "ds1", "column": "city"}
    err = validate_tool_call("histogram", args, PROFILES)
    assert err is not None and "numeric" in err.lower()


def test_histogram_unknown_dataset_rejected() -> None:
    args = {"dataset_id": "nope", "column": "age"}
    err = validate_tool_call("histogram", args, PROFILES)
    assert err is not None and "nope" in err


def test_scatter_requires_two_numeric_columns() -> None:
    ok = {"dataset_id": "ds1", "x": "age", "y": "score"}
    bad = {"dataset_id": "ds1", "x": "age", "y": "city"}
    assert validate_tool_call("scatter", ok, PROFILES) is None
    assert validate_tool_call("scatter", bad, PROFILES) is not None


def test_correlation_matrix_requires_dataset_id() -> None:
    assert validate_tool_call("correlation_matrix", {"dataset_id": "ds1"}, PROFILES) is None
    err = validate_tool_call("correlation_matrix", {"dataset_id": "nope"}, PROFILES)
    assert err is not None


def test_unknown_tool_rejected() -> None:
    assert validate_tool_call("pie", {}, PROFILES) is not None


def test_missing_required_arg_rejected() -> None:
    assert isinstance(validate_tool_call("histogram", {"dataset_id": "ds1"}, PROFILES), str)


def test_non_string_arg_rejected_without_raising() -> None:
    bad_column = {"dataset_id": "ds1", "column": ["a", "b"]}
    bad_x = {"dataset_id": "ds1", "x": {"k": 1}, "y": "score"}
    assert isinstance(validate_tool_call("histogram", bad_column, PROFILES), str)
    assert isinstance(validate_tool_call("scatter", bad_x, PROFILES), str)


def test_profile_column_missing_dtype_does_not_raise() -> None:
    profiles = {"ds1": {"columns": [{"name": "age", "n_null": 0}]}}
    args = {"dataset_id": "ds1", "column": "age"}
    result = validate_tool_call("histogram", args, profiles)
    assert isinstance(result, str)  # treated as non-numeric, rejected, not crashed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest backend/tests/test_tools.py -v`
Expected: FAIL — e.g. `test_valid_histogram_passes` fails because the current
`histogram` tool schema/validation doesn't require or use `dataset_id`, and the
single-profile-dict signature doesn't accept a `{dataset_id: profile}` mapping.

- [ ] **Step 3: Add `dataset_id` to `TOOL_DEFS` and rewrite `validate_tool_call`**

Replace `backend/app/tools.py` in full:

```python
"""Claude tool definitions and pre-execution validation for analysis functions.

This module defines the fixed menu of typed functions that Claude can call
(histogram, scatter, correlation_matrix) and provides a guard that validates
tool calls against the calling chat's dataset profiles before any chart executes.
"""

from typing import Any

TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "histogram",
        "description": "Generate a histogram for a single numeric column in one dataset.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_id": {
                    "type": "string",
                    "description": "The id of the dataset to read the column from.",
                },
                "column": {
                    "type": "string",
                    "description": "The name of the numeric column to visualize.",
                },
            },
            "required": ["dataset_id", "column"],
        },
    },
    {
        "name": "scatter",
        "description": "Generate a scatter plot for two numeric columns in one dataset.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_id": {
                    "type": "string",
                    "description": "The id of the dataset to read the columns from.",
                },
                "x": {
                    "type": "string",
                    "description": "The name of the numeric column for the x-axis.",
                },
                "y": {
                    "type": "string",
                    "description": "The name of the numeric column for the y-axis.",
                },
            },
            "required": ["dataset_id", "x", "y"],
        },
    },
    {
        "name": "correlation_matrix",
        "description": "Generate a correlation matrix heatmap for all numeric columns in one dataset.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_id": {
                    "type": "string",
                    "description": "The id of the dataset to compute correlations for.",
                }
            },
            "required": ["dataset_id"],
        },
    },
]


def _is_numeric(dtype: str) -> bool:
    """Check if a dtype string represents a numeric type."""
    return str(dtype).lower().startswith(("int", "float", "uint"))


def _numeric_columns(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        c["name"]: c for c in profile.get("columns", []) if _is_numeric(c.get("dtype", ""))
    }


def validate_tool_call(
    name: str, args: dict[str, Any], profiles: dict[str, dict[str, Any]]
) -> str | None:
    """Validate a tool call against the calling chat's dataset profiles.

    Args:
        name: Tool name (e.g., "histogram", "scatter").
        args: Tool arguments from Claude (e.g., {"dataset_id": "...", "column": "age"}).
        profiles: Dataset profiles for every dataset attached to the chat, keyed by
            dataset_id. Each profile has a "columns" key containing a list of
            {"name": str, "dtype": str, "n_null": int}.

    Returns:
        Error message string if validation fails, None if valid.
    """
    tool_names = {t["name"] for t in TOOL_DEFS}
    if name not in tool_names:
        return f"Unknown tool: {name}"

    dataset_id = args.get("dataset_id")
    if not isinstance(dataset_id, str) or dataset_id not in profiles:
        return f"Dataset not found: {dataset_id!r}"
    profile = profiles[dataset_id]
    columns_by_name = {c["name"]: c for c in profile.get("columns", [])}
    numeric_columns = _numeric_columns(profile)

    if name == "histogram":
        col = args.get("column")
        if not isinstance(col, str) or col not in columns_by_name:
            return f"Column not found: {col!r}"
        if col not in numeric_columns:
            return f"Column must be numeric: {col}"
        return None

    if name == "scatter":
        x = args.get("x")
        y = args.get("y")
        if not isinstance(x, str) or x not in columns_by_name:
            return f"Column not found: {x!r}"
        if not isinstance(y, str) or y not in columns_by_name:
            return f"Column not found: {y!r}"
        if x not in numeric_columns:
            return f"Column must be numeric: {x}"
        if y not in numeric_columns:
            return f"Column must be numeric: {y}"
        return None

    if name == "correlation_matrix":
        if len(numeric_columns) < 2:
            return "Correlation matrix requires at least 2 numeric columns"
        return None

    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest backend/tests/test_tools.py -v`
Expected: PASS

- [ ] **Step 5: Type-check and commit**

Run: `poetry run mypy backend/app`
Expected: no errors

```bash
git add backend/app/tools.py backend/tests/test_tools.py
git commit -m "feat(backend): require dataset_id on histogram/scatter/correlation_matrix"
```

---

### Task 3: `compare` tool — schema + validation

**Files:**
- Modify: `backend/app/tools.py`
- Modify: `backend/tests/test_tools.py`

**Interfaces:**
- Consumes: `_is_numeric`, `_numeric_columns` from Task 2.
- Produces: `compare` entry in `TOOL_DEFS` with args
  `dataset_a_id, dataset_b_id, key_a, key_b, metric_a, metric_b, agg` (`agg` ∈
  `{"mean", "sum", "count"}`). `validate_tool_call` now also validates `compare`
  calls. Task 4/5 (analysis + charts) consume this same arg shape.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_tools.py` (replace the existing
`test_tool_defs_cover_three_charts` with the four-tool version, and add the new
`PROFILES_COMPARE` fixture + compare tests):

```python
PROFILES_COMPARE = {
    "ds1": {
        "columns": [
            {"name": "region", "dtype": "object", "n_null": 0},
            {"name": "revenue", "dtype": "float64", "n_null": 0},
        ]
    },
    "ds2": {
        "columns": [
            {"name": "region", "dtype": "object", "n_null": 0},
            {"name": "revenue", "dtype": "int64", "n_null": 0},
        ]
    },
}


def test_tool_defs_cover_four_tools() -> None:
    names = {t["name"] for t in TOOL_DEFS}
    assert names == {"histogram", "scatter", "correlation_matrix", "compare"}


def _compare_args(**overrides: object) -> dict[str, object]:
    args: dict[str, object] = {
        "dataset_a_id": "ds1",
        "dataset_b_id": "ds2",
        "key_a": "region",
        "key_b": "region",
        "metric_a": "revenue",
        "metric_b": "revenue",
        "agg": "mean",
    }
    args.update(overrides)
    return args


def test_valid_compare_passes() -> None:
    assert validate_tool_call("compare", _compare_args(), PROFILES_COMPARE) is None


def test_compare_unknown_dataset_rejected() -> None:
    err = validate_tool_call("compare", _compare_args(dataset_a_id="nope"), PROFILES_COMPARE)
    assert err is not None and "nope" in err


def test_compare_unknown_key_rejected() -> None:
    err = validate_tool_call("compare", _compare_args(key_a="nope"), PROFILES_COMPARE)
    assert err is not None and "nope" in err


def test_compare_non_numeric_metric_rejected() -> None:
    err = validate_tool_call("compare", _compare_args(metric_a="region"), PROFILES_COMPARE)
    assert err is not None and "numeric" in err.lower()


def test_compare_unsupported_agg_rejected() -> None:
    err = validate_tool_call("compare", _compare_args(agg="median"), PROFILES_COMPARE)
    assert err is not None and "agg" in err.lower()
```

Remove the old `test_tool_defs_cover_three_charts` test (replaced above by
`test_tool_defs_cover_four_tools`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest backend/tests/test_tools.py -v`
Expected: FAIL — `test_tool_defs_cover_four_tools` fails (compare not in `TOOL_DEFS`
yet) and the new compare validation tests fail (`validate_tool_call("compare", ...)`
falls through to `return None` at the end of the current function, so
`test_compare_unknown_dataset_rejected` etc. get `None` instead of an error string).

- [ ] **Step 3: Add `compare` to `TOOL_DEFS` and `validate_tool_call`**

In `backend/app/tools.py`, append to `TOOL_DEFS` (after `correlation_matrix`):

```python
    {
        "name": "compare",
        "description": (
            "Compare an aggregated metric across two datasets, inner-joined on a "
            "shared key column, as a grouped bar chart."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_a_id": {"type": "string", "description": "The first dataset's id."},
                "dataset_b_id": {"type": "string", "description": "The second dataset's id."},
                "key_a": {
                    "type": "string",
                    "description": "The join key column name in the first dataset.",
                },
                "key_b": {
                    "type": "string",
                    "description": "The join key column name in the second dataset.",
                },
                "metric_a": {
                    "type": "string",
                    "description": "The numeric column to aggregate in the first dataset.",
                },
                "metric_b": {
                    "type": "string",
                    "description": "The numeric column to aggregate in the second dataset.",
                },
                "agg": {
                    "type": "string",
                    "enum": ["mean", "sum", "count"],
                    "description": "The aggregation applied to each metric, grouped by key.",
                },
            },
            "required": [
                "dataset_a_id",
                "dataset_b_id",
                "key_a",
                "key_b",
                "metric_a",
                "metric_b",
                "agg",
            ],
        },
    },
```

Replace the `if name == "correlation_matrix": ... return None` block at the end of
`validate_tool_call` with:

```python
    if name == "correlation_matrix":
        if len(numeric_columns) < 2:
            return "Correlation matrix requires at least 2 numeric columns"
        return None

    # name == "compare" — the only tool operating on two datasets at once, so it
    # re-validates dataset_id/columns against dataset_b independently of the
    # single-dataset block above (which only resolved dataset_a's profile).
    dataset_a_id = dataset_id
    profile_a = profile
    columns_a = columns_by_name
    numeric_a = numeric_columns

    dataset_b_id = args.get("dataset_b_id")
    if not isinstance(dataset_b_id, str) or dataset_b_id not in profiles:
        return f"Dataset not found: {dataset_b_id!r}"
    profile_b = profiles[dataset_b_id]
    columns_b = {c["name"]: c for c in profile_b.get("columns", [])}
    numeric_b = _numeric_columns(profile_b)

    key_a = args.get("key_a")
    key_b = args.get("key_b")
    metric_a = args.get("metric_a")
    metric_b = args.get("metric_b")
    agg = args.get("agg")

    if not isinstance(key_a, str) or key_a not in columns_a:
        return f"Column not found: {key_a!r}"
    if not isinstance(key_b, str) or key_b not in columns_b:
        return f"Column not found: {key_b!r}"
    if not isinstance(metric_a, str) or metric_a not in columns_a:
        return f"Column not found: {metric_a!r}"
    if not isinstance(metric_b, str) or metric_b not in columns_b:
        return f"Column not found: {metric_b!r}"
    if metric_a not in numeric_a:
        return f"Column must be numeric: {metric_a}"
    if metric_b not in numeric_b:
        return f"Column must be numeric: {metric_b}"
    if agg not in ("mean", "sum", "count"):
        return f"Unsupported aggregation: {agg!r}"
    return None
```

This relies on `dataset_id`/`profile`/`columns_by_name`/`numeric_columns` (resolved
against `args["dataset_id"]`, i.e. `dataset_a_id` for a `compare` call) from the
top of the function — Claude is expected to pass `dataset_a_id`'s value duplicated
into `dataset_id` is **not** required; instead, rename the top-of-function
resolution to read `args.get("dataset_id") or args.get("dataset_a_id")` so both
single-dataset and `compare` calls share the same resolution line. Update the top
of `validate_tool_call` accordingly:

```python
    dataset_id = args.get("dataset_id") or args.get("dataset_a_id")
    if not isinstance(dataset_id, str) or dataset_id not in profiles:
        return f"Dataset not found: {dataset_id!r}"
    profile = profiles[dataset_id]
    columns_by_name = {c["name"]: c for c in profile.get("columns", [])}
    numeric_columns = _numeric_columns(profile)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest backend/tests/test_tools.py -v`
Expected: PASS

- [ ] **Step 5: Type-check and commit**

Run: `poetry run mypy backend/app`
Expected: no errors

```bash
git add backend/app/tools.py backend/tests/test_tools.py
git commit -m "feat(backend): add compare tool schema and validation"
```

---

### Task 4: `compare` analysis function

**Files:**
- Modify: `backend/app/analysis.py`
- Modify: `backend/tests/test_analysis.py`

**Interfaces:**
- Consumes: nothing new from prior tasks (pure pandas/matplotlib, same pattern as
  `histogram`/`scatter`/`correlation_matrix` in the same file).
- Produces: `compare(df_a: pd.DataFrame, df_b: pd.DataFrame, key_a: str, key_b: str, metric_a: str, metric_b: str, agg: str) -> tuple[str, dict[str, Any]]`.
  Stats shape: `{"key": str, "agg": str, "rows": [{"key": str, "a": float | None, "b": float | None}, ...]}`.
  Task 5 (`charts.py` dispatch) calls this exact signature.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_analysis.py`:

```python
from app.analysis import compare


def test_compare_joins_and_aggregates() -> None:
    df_a = pd.DataFrame({"region": ["east", "east", "west"], "revenue": [10, 20, 5]})
    df_b = pd.DataFrame({"region": ["east", "west", "west"], "revenue": [100, 200, 300]})
    png, stats = compare(df_a, df_b, "region", "region", "revenue", "revenue", "mean")
    assert _is_png_base64(png)
    rows_by_key = {r["key"]: r for r in stats["rows"]}
    assert rows_by_key["east"]["a"] == 15.0
    assert rows_by_key["east"]["b"] == 100.0
    assert rows_by_key["west"]["a"] == 5.0
    assert rows_by_key["west"]["b"] == 250.0


def test_compare_sum_agg() -> None:
    df_a = pd.DataFrame({"k": ["x", "x"], "v": [1, 2]})
    df_b = pd.DataFrame({"k": ["x"], "v": [10]})
    _png, stats = compare(df_a, df_b, "k", "k", "v", "v", "sum")
    assert stats["rows"] == [{"key": "x", "a": 3.0, "b": 10.0}]


def test_compare_only_matching_keys_included() -> None:
    df_a = pd.DataFrame({"k": ["x", "y"], "v": [1, 2]})
    df_b = pd.DataFrame({"k": ["x", "z"], "v": [10, 20]})
    _png, stats = compare(df_a, df_b, "k", "k", "v", "v", "mean")
    assert {r["key"] for r in stats["rows"]} == {"x"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest backend/tests/test_analysis.py -v`
Expected: FAIL with `ImportError: cannot import name 'compare' from 'app.analysis'`

- [ ] **Step 3: Implement `compare` in `backend/app/analysis.py`**

Append to `backend/app/analysis.py`:

```python
def compare(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    key_a: str,
    key_b: str,
    metric_a: str,
    metric_b: str,
    agg: str,
) -> tuple[str, dict[str, Any]]:
    left = df_a[[key_a, metric_a]].copy()
    left[metric_a] = pd.to_numeric(left[metric_a], errors="coerce")
    right = df_b[[key_b, metric_b]].copy()
    right[metric_b] = pd.to_numeric(right[metric_b], errors="coerce")

    left_agg = left.groupby(key_a)[metric_a].agg(agg)
    right_agg = right.groupby(key_b)[metric_b].agg(agg)
    joined = pd.concat({"a": left_agg, "b": right_agg}, axis=1, join="inner")

    fig = Figure(figsize=(6, 4))
    try:
        ax = fig.subplots()
        x = np.arange(len(joined))
        width = 0.35
        ax.bar(x - width / 2, joined["a"], width, label=f"A: {metric_a}", color="#4C72B0")
        ax.bar(x + width / 2, joined["b"], width, label=f"B: {metric_b}", color="#DD8452")
        ax.set_xticks(x)
        ax.set_xticklabels([str(v) for v in joined.index], rotation=45, ha="right")
        ax.set_title(f"{agg}({metric_a}) vs {agg}({metric_b}) by {key_a}")
        ax.legend()
        png = _fig_to_base64(fig)
    finally:
        fig.clear()

    stats: dict[str, Any] = {
        "key": key_a,
        "agg": agg,
        "rows": [
            {"key": str(idx), "a": _nan_to_none(row["a"]), "b": _nan_to_none(row["b"])}
            for idx, row in joined.iterrows()
        ],
    }
    return png, stats
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest backend/tests/test_analysis.py -v`
Expected: PASS

- [ ] **Step 5: Type-check and commit**

Run: `poetry run mypy backend/app`
Expected: no errors

```bash
git add backend/app/analysis.py backend/tests/test_analysis.py
git commit -m "feat(backend): add compare join+aggregate analysis function"
```

---

### Task 5: Multi-dataset chart dispatch

**Files:**
- Modify: `backend/app/charts.py`
- Modify: `backend/tests/test_charts.py`

**Interfaces:**
- Consumes: `compare` from Task 4; `histogram`/`scatter`/`correlation_matrix` (unchanged).
- Produces: `_DISPATCH[name](dfs: dict[str, pd.DataFrame], args: dict) -> tuple[str, dict]`
  (was `_DISPATCH[name](df, args)`). `render_message_analysis(data_csv_by_id: dict[str, str], tool_calls) -> tuple[list[str], list[dict]]`
  (was `render_message_analysis(data_csv: str, tool_calls)`). `render_message_charts`
  same signature change. Task 8 (`routes/chats.py`) calls both with the new signatures.

- [ ] **Step 1: Write the failing tests**

Replace `backend/tests/test_charts.py` in full:

```python
import base64

from app.charts import render_message_charts

DATA = {"ds1": "age,score\n20,1\n30,2\n40,3\n"}
DATA_TWO = {
    "ds1": "region,revenue\neast,10\neast,20\nwest,5\n",
    "ds2": "region,revenue\neast,100\nwest,200\nwest,300\n",
}


def _is_png(s: str) -> bool:
    return base64.b64decode(s)[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_histogram_and_scatter() -> None:
    calls = [
        {"name": "histogram", "args": {"dataset_id": "ds1", "column": "age"}},
        {"name": "scatter", "args": {"dataset_id": "ds1", "x": "age", "y": "score"}},
    ]
    charts = render_message_charts(DATA, calls)
    assert len(charts) == 2
    assert all(_is_png(c) for c in charts)


def test_unknown_tool_is_skipped() -> None:
    charts = render_message_charts(DATA, [{"name": "pie", "args": {}}])
    assert charts == []


def test_bad_column_skipped_but_good_call_still_renders() -> None:
    calls = [
        {"name": "histogram", "args": {"dataset_id": "ds1", "column": "does_not_exist"}},
        {"name": "scatter", "args": {"dataset_id": "ds1", "x": "age", "y": "score"}},
    ]
    charts = render_message_charts(DATA, calls)
    assert len(charts) == 1
    assert _is_png(charts[0])


def test_correlation_matrix_renders() -> None:
    calls = [{"name": "correlation_matrix", "args": {"dataset_id": "ds1"}}]
    charts = render_message_charts(DATA, calls)
    assert len(charts) == 1
    assert _is_png(charts[0])


def test_partial_scatter_args_skipped() -> None:
    calls = [{"name": "scatter", "args": {"dataset_id": "ds1", "x": "age"}}]
    charts = render_message_charts(DATA, calls)
    assert charts == []


def test_unknown_dataset_id_skipped() -> None:
    calls = [{"name": "histogram", "args": {"dataset_id": "nope", "column": "age"}}]
    assert render_message_charts(DATA, calls) == []


def test_compare_renders_across_two_datasets() -> None:
    calls = [
        {
            "name": "compare",
            "args": {
                "dataset_a_id": "ds1",
                "dataset_b_id": "ds2",
                "key_a": "region",
                "key_b": "region",
                "metric_a": "revenue",
                "metric_b": "revenue",
                "agg": "mean",
            },
        }
    ]
    charts = render_message_charts(DATA_TWO, calls)
    assert len(charts) == 1
    assert _is_png(charts[0])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest backend/tests/test_charts.py -v`
Expected: FAIL — `render_message_charts` currently takes a single CSV string, so
passing a `dict` breaks `load_csv(data_csv)` inside it (`pd.read_csv` on a dict
raises).

- [ ] **Step 3: Rewrite `backend/app/charts.py`**

```python
"""Re-render charts for history reads. Charts are a pure function of each
attached dataset's raw CSV plus a message's tool_calls — never stored (design D5)."""

from __future__ import annotations

from typing import Any

from app.analysis import compare, correlation_matrix, histogram, scatter
from app.dataset_io import load_csv

_DISPATCH = {
    "histogram": lambda dfs, args: histogram(dfs[args["dataset_id"]], args["column"]),
    "scatter": lambda dfs, args: scatter(dfs[args["dataset_id"]], args["x"], args["y"]),
    "correlation_matrix": lambda dfs, args: correlation_matrix(dfs[args["dataset_id"]]),
    "compare": lambda dfs, args: compare(
        dfs[args["dataset_a_id"]],
        dfs[args["dataset_b_id"]],
        args["key_a"],
        args["key_b"],
        args["metric_a"],
        args["metric_b"],
        args["agg"],
    ),
}


def render_message_analysis(
    data_csv_by_id: dict[str, str], tool_calls: list[dict[str, Any]]
) -> tuple[list[str], list[dict[str, Any]]]:
    """Re-derive charts AND stats from each attached dataset's CSV + a message's
    tool_calls (history path). Charts and stats are pure functions of these
    inputs, re-derived on read — consistent with the 'charts are never stored'
    invariant. Unknown/invalid calls (including an unknown dataset_id, which
    raises KeyError against dfs) are skipped so one bad call never breaks a
    history read."""
    dfs = {dataset_id: load_csv(csv) for dataset_id, csv in data_csv_by_id.items()}
    charts: list[str] = []
    stats: list[dict[str, Any]] = []
    for call in tool_calls:
        fn = _DISPATCH.get(call.get("name", ""))
        if fn is None:
            continue
        try:
            png, stat = fn(dfs, call.get("args", {}))
        except (KeyError, ValueError):
            continue
        charts.append(png)
        stats.append(stat)
    return charts, stats


def render_message_charts(
    data_csv_by_id: dict[str, str], tool_calls: list[dict[str, Any]]
) -> list[str]:
    charts, _stats = render_message_analysis(data_csv_by_id, tool_calls)
    return charts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest backend/tests/test_charts.py -v`
Expected: PASS

- [ ] **Step 5: Type-check and commit**

Run: `poetry run mypy backend/app`
Expected: no errors

```bash
git add backend/app/charts.py backend/tests/test_charts.py
git commit -m "feat(backend): dispatch charts against a dict of per-dataset dataframes"
```

---

### Task 6: Multi-dataset LLM prompt assembly

**Files:**
- Modify: `backend/app/llm.py`
- Modify: `backend/tests/test_llm.py`

**Interfaces:**
- Consumes: `settings.profile_token_budget` from `app.config`.
- Produces: `run_pass(datasets: list[dict[str, Any]], prior_messages: list[dict[str, Any]], question: str, *, client: Any | None = None) -> LLMResult`
  where each `datasets` entry is `{"id": str, "name": str, "profile": dict}` (was
  `run_pass(profile: dict, ...)`). Also exports `_assemble_dataset_profiles` for
  the budget-degrade test. Task 8 (`routes/chats.py`) calls `run_pass` with this
  new `datasets` list shape.

- [ ] **Step 1: Write the failing tests**

Replace `backend/tests/test_llm.py` in full:

```python
import json
from types import SimpleNamespace

import app.llm as llm_module
from app.llm import _SYSTEM_PROMPT_PATH, _USER_PROMPT_PATH, _system_prompt, run_pass

DATASETS = [
    {
        "id": "ds1",
        "name": "d.csv",
        "profile": {"columns": [{"name": "age", "dtype": "int64", "n_null": 0}], "n_rows": 3},
    }
]


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
    tool_block = SimpleNamespace(type="tool_use", name="histogram", input={"column": "age"})
    text_block = SimpleNamespace(type="text", text="Ages are spread evenly.")
    usage = SimpleNamespace(input_tokens=120, output_tokens=45)
    return SimpleNamespace(content=[tool_block, text_block], usage=usage)


def test_run_pass_parses_tools_and_text() -> None:
    client = _FakeClient(_response())
    result = run_pass(DATASETS, [], "show me the age distribution", client=client)

    assert result.interpretation == "Ages are spread evenly."
    assert result.tool_calls == [{"name": "histogram", "args": {"column": "age"}}]
    assert result.tokens_in == 120
    assert result.tokens_out == 45
    assert result.cost_usd > 0
    assert result.latency_ms >= 0


def test_system_prompt_appends_user_prompt() -> None:
    combined = _system_prompt()
    assert _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip() in combined
    assert _USER_PROMPT_PATH.read_text(encoding="utf-8").strip() in combined
    assert combined.index("data analysis assistant") < combined.index("Answer the user's latest")


def test_run_pass_assembles_messages() -> None:
    client = _FakeClient(_response())
    prior = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    run_pass(DATASETS, prior, "and the age distribution?", client=client)

    kwargs = client.messages.captured
    assert kwargs["model"]
    assert kwargs["tools"]
    assert "age" in json.dumps(kwargs["system"])
    assert "ds1" in json.dumps(kwargs["system"])
    contents = [m["content"] for m in kwargs["messages"]]
    assert contents[-1].endswith("age distribution?")
    assert "hi" in json.dumps(kwargs["messages"])


def test_run_pass_labels_every_attached_dataset() -> None:
    client = _FakeClient(_response())
    two_datasets = DATASETS + [
        {"id": "ds2", "name": "b.csv", "profile": {"columns": [], "n_rows": 1}}
    ]
    run_pass(two_datasets, [], "compare them", client=client)

    system_text = json.dumps(client.messages.captured["system"])
    assert "ds1" in system_text
    assert "ds2" in system_text
    assert "b.csv" in system_text


def test_combined_budget_keeps_sample_rows_when_small() -> None:
    datasets = [{"id": "ds1", "name": "a.csv", "profile": {"columns": [], "sample_rows": [{"x": 1}]}}]
    labeled = llm_module._assemble_dataset_profiles(datasets)
    assert labeled[0]["profile"]["sample_rows"] == [{"x": 1}]


def test_combined_budget_drops_sample_rows_when_over(monkeypatch) -> None:
    monkeypatch.setattr(llm_module.settings, "profile_token_budget", 10)
    datasets = [
        {"id": "ds1", "name": "a.csv", "profile": {"columns": [], "sample_rows": [{"x": 1}]}},
        {"id": "ds2", "name": "b.csv", "profile": {"columns": [], "sample_rows": [{"x": 2}]}},
    ]
    labeled = llm_module._assemble_dataset_profiles(datasets)
    assert all(entry["profile"]["sample_rows"] == [] for entry in labeled)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest backend/tests/test_llm.py -v`
Expected: FAIL — `run_pass(DATASETS, ...)` currently expects `profile: dict` as its
first arg and does `json.dumps(profile, ...)` directly, so passing a `list` breaks
the "age" assertion, and `_assemble_dataset_profiles` doesn't exist yet
(`AttributeError`).

- [ ] **Step 3: Rewrite the profile-assembly and `run_pass` parts of `backend/app/llm.py`**

Keep everything above `run_pass` unchanged (`LLMResult`, `_system_prompt`,
`_estimate_cost`, `_build_messages`, `_default_client`, `_PRICES`) and add/replace:

```python
def _estimate_tokens(payload: Any) -> int:
    return len(json.dumps(payload, default=str)) // 4


def _assemble_dataset_profiles(datasets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Label each attached dataset's stored profile with its id/name for the
    prompt. If the combined payload exceeds the per-dataset token budget scaled
    by dataset count, drop sample_rows from every profile first — the same
    cheapest-cut priority as the single-dataset degrade in profile_dataframe()."""
    profiles = [d["profile"] for d in datasets]
    budget = settings.profile_token_budget * max(len(datasets), 1)
    if _estimate_tokens(profiles) > budget:
        profiles = [{**p, "sample_rows": []} for p in profiles]
    return [
        {"dataset_id": d["id"], "name": d["name"], "profile": profile}
        for d, profile in zip(datasets, profiles, strict=True)
    ]


def run_pass(
    datasets: list[dict[str, Any]],
    prior_messages: list[dict[str, Any]],
    question: str,
    *,
    client: Any | None = None,
) -> LLMResult:
    client = client or _default_client()
    labeled = _assemble_dataset_profiles(datasets)
    system = [{"type": "text", "text": _system_prompt()}]
    for entry in labeled:
        header = f"Dataset {entry['dataset_id']} ({entry['name']}) profile:\n"
        system.append(
            {"type": "text", "text": header + json.dumps(entry["profile"], default=str)}
        )

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

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest backend/tests/test_llm.py -v`
Expected: PASS

- [ ] **Step 5: Type-check and commit**

Run: `poetry run mypy backend/app`
Expected: no errors

```bash
git add backend/app/llm.py backend/tests/test_llm.py
git commit -m "feat(backend): assemble labeled multi-dataset profiles in run_pass"
```

---

### Task 7: Chat/dataset response schemas

**Files:**
- Modify: `backend/app/schemas.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ChatCreateRequest(dataset_ids: list[str])`, `ChatDatasetOut(id: str, name: str)`,
  `ChatOut(id: str, datasets: list[ChatDatasetOut])`, `ChatHistoryOut(datasets: list[ChatDatasetOut], messages: list[ChatMessageOut])`
  (was `ChatHistoryOut(messages: ...)` only). `ChatRequest`/`ChatMessageOut`/`DatasetOut`
  unchanged. Task 8 (`routes/chats.py`) is the only consumer — there's no dedicated
  schema test file in this repo (schemas are exercised through the route tests in
  Task 8), so this task has no test step of its own; it's verified transitively
  when Task 8's tests pass.

- [ ] **Step 1: Replace `backend/app/schemas.py` in full**

```python
from typing import Any

from pydantic import BaseModel, ConfigDict


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    n_rows: int
    n_cols: int


class ChatCreateRequest(BaseModel):
    dataset_ids: list[str]


class ChatDatasetOut(BaseModel):
    id: str
    name: str


class ChatOut(BaseModel):
    id: str
    datasets: list[ChatDatasetOut]


class ChatRequest(BaseModel):
    question: str


class ChatMessageOut(BaseModel):
    id: str
    role: str
    content: str
    charts: list[str] = []
    stats: list[dict[str, Any]] = []
    errors: list[str] = []


class ChatHistoryOut(BaseModel):
    datasets: list[ChatDatasetOut]
    messages: list[ChatMessageOut]
```

- [ ] **Step 2: Type-check**

Run: `poetry run mypy backend/app`
Expected: no errors (note: `app/routes/chats.py` will still reference the old
schemas/route shape until Task 8 — this step only confirms `schemas.py` itself is
well-typed in isolation; a full `mypy backend/app` may show errors in
`routes/chats.py` until Task 8 is done, which is expected and resolved there.
If your mypy config errors on unrelated files, run `poetry run mypy backend/app/schemas.py` instead.)

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas.py
git commit -m "feat(backend): add ChatCreateRequest/ChatOut/ChatDatasetOut schemas"
```

---

### Task 8: `/chats` routes (replaces `/datasets/{dataset_id}/chat`)

**Files:**
- Modify: `backend/app/routes/chats.py`
- Modify: `backend/tests/test_chats.py`

**Interfaces:**
- Consumes: `ChatDataset` (Task 1), `validate_tool_call`/`profiles` shape (Task 2/3),
  `_DISPATCH`/`render_message_analysis` (Task 5), `run_pass`/`datasets` shape (Task 6),
  `ChatCreateRequest`/`ChatOut`/`ChatDatasetOut`/`ChatHistoryOut` (Task 7).
- Produces: `POST /chats`, `POST /chats/{chat_id}/messages`, `GET /chats/{chat_id}`.
  The old `POST/GET /datasets/{dataset_id}/chat` routes are removed entirely.

- [ ] **Step 1: Write the failing tests**

Replace `backend/tests/test_chats.py` in full:

```python
from types import SimpleNamespace

import app.routes.chats as chats_route


def _fake_llm(monkeypatch, tool_calls, text="Looks linear.") -> None:
    def fake_run_pass(datasets, prior_messages, question, *, client=None):
        return SimpleNamespace(
            interpretation=text,
            tool_calls=tool_calls,
            tokens_in=100,
            tokens_out=30,
            cost_usd=0.001,
            latency_ms=12,
        )

    monkeypatch.setattr(chats_route, "run_pass", fake_run_pass)


def _upload(client, csv="age,score\n20,1\n30,2\n40,3\n", name="d.csv") -> str:
    resp = client.post("/datasets", files={"file": (name, csv, "text/csv")})
    return resp.json()["id"]


def test_create_chat_with_one_dataset(client) -> None:
    dataset_id = _upload(client)
    resp = client.post("/chats", json={"dataset_ids": [dataset_id]})
    assert resp.status_code == 200
    assert resp.json()["datasets"] == [{"id": dataset_id, "name": "d.csv"}]


def test_create_chat_with_multiple_datasets(client) -> None:
    id_a = _upload(client, name="a.csv")
    id_b = _upload(client, csv="region,revenue\neast,1\nwest,2\n", name="b.csv")
    resp = client.post("/chats", json={"dataset_ids": [id_a, id_b]})
    assert resp.status_code == 200
    names = [d["name"] for d in resp.json()["datasets"]]
    assert names == ["a.csv", "b.csv"]


def test_create_chat_requires_at_least_one_dataset(client) -> None:
    resp = client.post("/chats", json={"dataset_ids": []})
    assert resp.status_code == 400


def test_create_chat_unknown_dataset_404(client) -> None:
    resp = client.post("/chats", json={"dataset_ids": ["nope"]})
    assert resp.status_code == 404


def test_chat_runs_and_persists(client, monkeypatch) -> None:
    dataset_id = _upload(client)
    args = {"dataset_id": dataset_id, "x": "age", "y": "score"}
    _fake_llm(monkeypatch, [{"name": "scatter", "args": args}])
    chat_id = client.post("/chats", json={"dataset_ids": [dataset_id]}).json()["id"]

    resp = client.post(f"/chats/{chat_id}/messages", json={"question": "relate them"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["content"] == "Looks linear."
    assert len(body["charts"]) == 1
    assert len(body["stats"]) == 1
    assert body["errors"] == []

    from app.db import get_session
    from app.models import Analysis, Chat, ChatMessage

    session = next(client.app.dependency_overrides[get_session]())
    assert session.query(Chat).count() == 1
    assert session.query(ChatMessage).count() == 2  # user + assistant
    assert session.query(Analysis).count() == 1


def test_chat_invalid_tool_arg_is_graceful(client, monkeypatch) -> None:
    dataset_id = _upload(client)
    args = {"dataset_id": dataset_id, "column": "missing"}
    _fake_llm(monkeypatch, [{"name": "histogram", "args": args}])
    chat_id = client.post("/chats", json={"dataset_ids": [dataset_id]}).json()["id"]

    resp = client.post(f"/chats/{chat_id}/messages", json={"question": "hist"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["charts"] == []
    assert len(body["errors"]) == 1


def test_chat_persists_multiple_messages(client, monkeypatch) -> None:
    dataset_id = _upload(client)
    _fake_llm(monkeypatch, [])
    chat_id = client.post("/chats", json={"dataset_ids": [dataset_id]}).json()["id"]
    client.post(f"/chats/{chat_id}/messages", json={"question": "q1"})
    client.post(f"/chats/{chat_id}/messages", json={"question": "q2"})

    resp = client.get(f"/chats/{chat_id}")
    assert len(resp.json()["messages"]) == 4


def test_get_history_rerenders_charts(client, monkeypatch) -> None:
    dataset_id = _upload(client)
    args = {"dataset_id": dataset_id, "x": "age", "y": "score"}
    _fake_llm(monkeypatch, [{"name": "scatter", "args": args}])
    chat_id = client.post("/chats", json={"dataset_ids": [dataset_id]}).json()["id"]
    client.post(f"/chats/{chat_id}/messages", json={"question": "relate them"})

    resp = client.get(f"/chats/{chat_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["datasets"] == [{"id": dataset_id, "name": "d.csv"}]
    messages = body["messages"]
    assert len(messages) == 2
    assistant = [m for m in messages if m["role"] == "assistant"][0]
    assert len(assistant["charts"]) == 1
    assert len(assistant["stats"]) == 1
    assert assistant["errors"] == []


def test_message_unknown_chat_404(client, monkeypatch) -> None:
    _fake_llm(monkeypatch, [])
    resp = client.post("/chats/nope/messages", json={"question": "hi"})
    assert resp.status_code == 404


def test_get_history_unknown_chat_404(client) -> None:
    resp = client.get("/chats/nope")
    assert resp.status_code == 404


def test_compare_across_two_datasets(client, monkeypatch) -> None:
    id_a = _upload(client, csv="region,revenue\neast,10\neast,20\nwest,5\n", name="a.csv")
    id_b = _upload(client, csv="region,revenue\neast,100\nwest,200\nwest,300\n", name="b.csv")
    compare_args = {
        "dataset_a_id": id_a,
        "dataset_b_id": id_b,
        "key_a": "region",
        "key_b": "region",
        "metric_a": "revenue",
        "metric_b": "revenue",
        "agg": "mean",
    }
    _fake_llm(monkeypatch, [{"name": "compare", "args": compare_args}])
    chat_id = client.post("/chats", json={"dataset_ids": [id_a, id_b]}).json()["id"]

    resp = client.post(f"/chats/{chat_id}/messages", json={"question": "compare revenue"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["charts"]) == 1
    assert body["errors"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest backend/tests/test_chats.py -v`
Expected: FAIL — `POST /chats` returns 404 (route doesn't exist yet, only
`/datasets/{dataset_id}/chat` does).

- [ ] **Step 3: Replace `backend/app/routes/chats.py` in full**

```python
"""Chat endpoints: a chat spans one or more datasets. Runs a single Claude pass,
executes the chart tools it selects (after validation), persists the turn, and
returns charts + interpretation. History reads re-render charts, never store
them."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.charts import _DISPATCH, render_message_analysis
from app.dataset_io import load_csv
from app.db import get_session
from app.llm import run_pass
from app.models import Analysis, Chat, ChatDataset, ChatMessage, Dataset
from app.schemas import (
    ChatCreateRequest,
    ChatDatasetOut,
    ChatHistoryOut,
    ChatMessageOut,
    ChatOut,
    ChatRequest,
)
from app.tools import validate_tool_call

router = APIRouter(prefix="/chats", tags=["chat"])


def _get_chat(session: Session, chat_id: str) -> Chat:
    chat = session.get(Chat, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


def _chat_datasets(session: Session, chat_id: str) -> list[Dataset]:
    rows = session.scalars(
        select(ChatDataset)
        .where(ChatDataset.chat_id == chat_id)
        .order_by(ChatDataset.ordinal_position)
    ).all()
    datasets: list[Dataset] = []
    for row in rows:
        dataset = session.get(Dataset, row.dataset_id)
        if dataset is not None:
            datasets.append(dataset)
    return datasets


def _prior_messages(session: Session, chat_id: str) -> list[dict[str, str]]:
    rows = session.scalars(
        select(ChatMessage).where(ChatMessage.chat_id == chat_id).order_by(ChatMessage.created_at)
    ).all()
    return [{"role": r.role, "content": r.content} for r in rows]


@router.post("", response_model=ChatOut)
def create_chat(body: ChatCreateRequest, session: Session = Depends(get_session)) -> ChatOut:
    if not body.dataset_ids:
        raise HTTPException(status_code=400, detail="At least one dataset_id is required")

    datasets: list[Dataset] = []
    for dataset_id in body.dataset_ids:
        dataset = session.get(Dataset, dataset_id)
        if dataset is None:
            raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
        datasets.append(dataset)

    chat = Chat()
    session.add(chat)
    session.flush()
    for ordinal_position, dataset in enumerate(datasets):
        session.add(
            ChatDataset(chat_id=chat.id, dataset_id=dataset.id, ordinal_position=ordinal_position)
        )
    session.commit()

    return ChatOut(id=chat.id, datasets=[ChatDatasetOut(id=d.id, name=d.name) for d in datasets])


@router.post("/{chat_id}/messages", response_model=ChatMessageOut)
def post_message(
    chat_id: str,
    body: ChatRequest,
    session: Session = Depends(get_session),
) -> ChatMessageOut:
    chat = _get_chat(session, chat_id)
    datasets = _chat_datasets(session, chat.id)

    prior = _prior_messages(session, chat.id)
    session.add(ChatMessage(chat_id=chat.id, role="user", content=body.question))
    session.flush()

    result = run_pass(
        [{"id": d.id, "name": d.name, "profile": d.profile_json} for d in datasets],
        prior,
        body.question,
    )

    profiles = {d.id: d.profile_json for d in datasets}
    dfs = {d.id: load_csv(d.data_csv) for d in datasets}
    charts: list[str] = []
    stats: list[dict[str, Any]] = []
    errors: list[str] = []
    executed_calls: list[dict[str, Any]] = []

    for call in result.tool_calls:
        err = validate_tool_call(call["name"], call["args"], profiles)
        if err is not None:
            errors.append(err)
            continue
        png, stat = _DISPATCH[call["name"]](dfs, call["args"])
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

    for call, stat in zip(executed_calls, stats, strict=True):
        session.add(
            Analysis(
                message_id=assistant.id,
                chart_type=call["name"],
                params=call["args"],
                result_stats=stat,
            )
        )

    session.commit()
    return ChatMessageOut(
        id=assistant.id,
        role="assistant",
        content=result.interpretation,
        charts=charts,
        stats=stats,
        errors=errors,
    )


@router.get("/{chat_id}", response_model=ChatHistoryOut)
def get_chat(chat_id: str, session: Session = Depends(get_session)) -> ChatHistoryOut:
    chat = _get_chat(session, chat_id)
    datasets = _chat_datasets(session, chat.id)
    data_csv_by_id = {d.id: d.data_csv for d in datasets}

    rows = session.scalars(
        select(ChatMessage).where(ChatMessage.chat_id == chat.id).order_by(ChatMessage.created_at)
    ).all()

    messages: list[ChatMessageOut] = []
    for r in rows:
        if r.role == "assistant" and r.tool_calls:
            charts, stats = render_message_analysis(data_csv_by_id, r.tool_calls)
        else:
            charts, stats = [], []
        messages.append(
            ChatMessageOut(
                id=r.id,
                role=r.role,
                content=r.content,
                charts=charts,
                stats=stats,
                errors=[],
            )
        )
    return ChatHistoryOut(
        datasets=[ChatDatasetOut(id=d.id, name=d.name) for d in datasets],
        messages=messages,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest backend/tests/test_chats.py -v`
Expected: PASS

- [ ] **Step 5: Run the full backend suite and type-check**

Run: `poetry run pytest backend/tests -v`
Expected: PASS (all files, including `test_datasets.py`, `test_health.py`,
`test_cors.py`, `test_dataset_io.py`, `test_profiler.py`, unaffected by this plan)

Run: `poetry run mypy backend/app`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/chats.py backend/tests/test_chats.py
git commit -m "feat(backend): replace /datasets/{id}/chat with /chats resource"
```

---

### Task 9: Doc sync + final gate

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `doc/project-1-csv-analysis-assistant-design.md`

**Interfaces:** None — documentation only, per this repo's required doc-sync rule
(CLAUDE.md: "Document sync — required before merging a PR").

- [ ] **Step 1: Update `README.md`'s API table and curl example**

Find the lines:

```
curl -X POST http://localhost:8000/datasets/<uuid>/chat \
```

and

```
| POST   | `/datasets/{id}/chat`         | Ask a question → Claude selects tools → charts + interpretation |
| GET    | `/datasets/{id}/chat`         | Chat history (charts re-rendered on the fly, never stored)     |
```

Replace with the new three-route shape (adjust surrounding curl flags to match
the existing example's style — inspect the lines immediately around them for the
exact `-H`/`-d` flags already in use before editing):

```
| POST   | `/chats`                      | Create a chat over one or more dataset_ids |
| POST   | `/chats/{chat_id}/messages`   | Ask a question → Claude selects tools → charts + interpretation |
| GET    | `/chats/{chat_id}`            | Chat history (charts re-rendered on the fly, never stored)     |
```

- [ ] **Step 2: Update `CLAUDE.md`'s code layout section**

In the `backend/app/` tree, update the `routes/chats.py` line's description to
mention the new `/chats`, `/chats/{chat_id}/messages` routes instead of
`/datasets/{id}/chat`, and add a one-line mention of the `ChatDataset` join table
under `models.py`'s description. Add a short new bullet under "Non-obvious design
decisions" summarizing: a chat now spans N datasets via `chat_datasets`; existing
tools require `dataset_id`; a new `compare` tool does an in-memory, non-persisted,
inner-join comparison across exactly two datasets.

- [ ] **Step 3: Append an amendment to the base design doc**

Append to the end of `doc/project-1-csv-analysis-assistant-design.md`:

```markdown

---

## 12. Amendments

- **Multi-dataset chat (issue #6, see `doc/project-1-multi-dataset-chat-design.md`):**
  A chat now spans one or more datasets via a new `chat_datasets` join table,
  replacing the single `chats.dataset_id` FK. Existing per-dataset tools
  (`histogram`, `scatter`, `correlation_matrix`) require a `dataset_id` argument;
  a new `compare` tool does a lightweight, in-memory, inner-join comparison
  across exactly two datasets. This is additive to D2 (still one Claude API call
  per turn — the multi-dataset profile is assembled into that same single system
  prompt) and D5 (joined data is computed in-memory per call and never
  persisted — raw CSV per dataset remains the only durable copy).
```

- [ ] **Step 4: Full CI-gate check**

Run: `make check`
Expected: PASS (lint + format-check + type-check + test)

- [ ] **Step 5: Commit**

```bash
git add README.md CLAUDE.md doc/project-1-csv-analysis-assistant-design.md
git commit -m "docs: sync README/CLAUDE/base design doc for multi-dataset chat"
```
