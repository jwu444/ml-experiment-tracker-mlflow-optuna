# Project 1 — Backend Foundation & Dataset Ingestion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the FastAPI backend so a user can upload a CSV via a shareable dataset link (no auth) and have it validated, profiled (bounded rich profile per design §4), and persisted as raw CSV in Postgres — with the database and engineering-standards scaffolding the rest of Project 1 builds on.

**Architecture:** A FastAPI app with a SQLAlchemy 2.0 data model (`datasets`, `chat_messages` — **no `users` table**, per design D4), a pure `profile_dataframe` function that computes the bounded rich profile fed to Claude in later plans, and a small CSV helper that stores uploaded data verbatim as raw CSV text on the `datasets` row (design D5 — single datastore, no object store, charts re-rendered on demand). The `/chat` route and LLM orchestrator are deliberately out of scope here — this plan ends with dataset ingestion working end-to-end.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, pandas, pydantic / pydantic-settings, Poetry, ruff + black + mypy, pytest + httpx (TestClient). Tests run on SQLite; production uses Postgres via `DATABASE_URL`.

## Global Constraints

- Python version: **3.12** (pinned via pyenv `.python-version`).
- Dependency management: **Poetry** only — no bare `pip install`.
- Code quality gate: `make check` = `ruff check` + `black --check` + `mypy` (strict, on `backend/app`) + `pytest`. All must pass.
- Line length: **100** (ruff + black agree).
- All application code lives under `backend/app/`; all tests under `backend/tests/`.
- Imports are absolute from the `app` package (e.g. `from app.profiler import profile_dataframe`).
- Database column for JSON uses SQLAlchemy's `JSON` type (maps to JSONB on Postgres, JSON on SQLite) so the same models run in tests and production.
- **No `users` table and no authentication** (design D4) — a dataset id *is* its own shareable link; datasets are addressed by id, not scoped to a user.
- Uploaded data is stored verbatim as **raw CSV text** in `datasets.data_csv` (`Text` → `text` on Postgres, `TEXT` on SQLite); **no object store** (design D5). Charts are a later plan's pure function of `data_csv` + `tool_calls`.

---

### Task 1: Project scaffold + health endpoint

**Files:**
- Create: `.python-version`
- Create: `pyproject.toml`
- Create: `Makefile`
- Create: `backend/app/__init__.py` (empty)
- Create: `backend/app/main.py`
- Create: `backend/tests/__init__.py` (empty)
- Create: `backend/tests/conftest.py`
- Test: `backend/tests/test_health.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `app.main.create_app() -> fastapi.FastAPI` — application factory.
  - `app.main.app` — the FastAPI instance for uvicorn.
  - pytest fixture `client` (in `conftest.py`) yielding a `fastapi.testclient.TestClient` wired to an isolated SQLite DB (used by all later tasks).

- [ ] **Step 1: Pin Python and create `pyproject.toml`**

`.python-version`:
```
3.12
```

`pyproject.toml`:
```toml
[tool.poetry]
name = "csv-analysis-assistant"
version = "0.1.0"
description = "Upload a CSV, ask questions, get plots + stats + LLM interpretation"
authors = ["WavePoint"]
readme = "README.md"
packages = [{ include = "app", from = "backend" }]

[tool.poetry.dependencies]
python = "^3.12"
fastapi = "^0.115"
uvicorn = { extras = ["standard"], version = "^0.30" }
sqlalchemy = "^2.0"
pandas = "^2.2"
pydantic = "^2.8"
pydantic-settings = "^2.4"
python-multipart = "^0.0.9"

[tool.poetry.group.dev.dependencies]
pytest = "^8.3"
httpx = "^0.27"
ruff = "^0.6"
black = "^24.8"
mypy = "^1.11"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]

[tool.black]
line-length = 100
target-version = ["py312"]

[tool.mypy]
python_version = "3.12"
strict = true
ignore_missing_imports = true

[tool.pytest.ini_options]
pythonpath = ["backend"]
testpaths = ["backend/tests"]
```

- [ ] **Step 2: Create the Makefile**

`Makefile`:
```make
.PHONY: install lint format format-check type-check test check dev eval

install:
	poetry install

lint:
	poetry run ruff check backend

format:
	poetry run black backend

format-check:
	poetry run black --check backend

type-check:
	poetry run mypy backend/app

test:
	poetry run pytest

check: lint format-check type-check test

dev:
	poetry run uvicorn app.main:app --reload --app-dir backend

eval:
	@echo "Eval suite arrives in a later plan (make eval)"
```

- [ ] **Step 3: Install dependencies**

Run: `make install`
Expected: Poetry resolves and installs; creates `poetry.lock`.

- [ ] **Step 4: Write the failing health test**

`backend/tests/test_health.py`:
```python
def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 5: Write the test fixture (conftest)**

`backend/tests/conftest.py`:
```python
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_session
from app.main import create_app
from app.models import Base


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_session() -> Iterator[Session]:
        with testing_session() as session:
            yield session

    app = create_app(init_on_startup=False)
    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as test_client:
        yield test_client
```

> Note: `conftest` imports `app.db` and `app.models` — those modules are created in Task 2. This task's test run (Step 7) will fail on import until Task 2 exists. That is expected. If executing strictly task-by-task, defer running `test_health.py` until Task 2 is complete (it has no logic dependency on Task 2, only an import-time one through conftest).

- [ ] **Step 6: Write the application factory**

`backend/app/main.py`:
```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI


def create_app(init_on_startup: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if init_on_startup:
            from app.db import init_db

            init_db()
        yield

    app = FastAPI(title="CSV Analysis Assistant", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    from app.routes import datasets

    app.include_router(datasets.router)
    return app


app = create_app()
```

> The `app.routes` import is inside `create_app` so the module imports lazily after all sibling modules exist. The datasets router is added in Task 5; until then, comment out the `from app.routes import datasets` and `app.include_router(datasets.router)` lines and re-enable them in Task 5.

- [ ] **Step 7: Run the health test**

Run: `poetry run pytest backend/tests/test_health.py -v`
Expected: PASS once Task 2 exists (DB module importable by conftest). If run immediately, expect an ImportError on `app.db` — proceed to Task 2.

- [ ] **Step 8: Commit**

```bash
git add .python-version pyproject.toml poetry.lock Makefile backend/app/__init__.py backend/app/main.py backend/tests/__init__.py backend/tests/conftest.py backend/tests/test_health.py
git commit -m "chore: scaffold FastAPI backend, tooling, and test harness"
```

---

### Task 2: Configuration + database models + session

**Files:**
- Create: `backend/app/config.py`
- Create: `backend/app/models.py`
- Create: `backend/app/db.py`
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `app.config.settings` — singleton `Settings` with `database_url: str`, `max_upload_bytes: int`, `max_rows: int`, and the profiler tunables `profile_max_cardinality: int`, `profile_max_corr_cols: int`, `profile_top_corr_pairs: int`, `profile_sample_rows: int`, `profile_token_budget: int` (all overridable via `.env`; see `.env.example`).
  - `app.models.Base` — SQLAlchemy `DeclarativeBase`.
  - `app.models.Dataset(id, name, n_rows, n_cols, profile_json: dict, data_csv: str, created_at)`,
    `app.models.ChatMessage(id, dataset_id, role, content, tool_calls: list, tokens_in, tokens_out, cost_usd, latency_ms, created_at)`.
  - `app.db.engine`, `app.db.SessionLocal`, `app.db.init_db() -> None`, `app.db.get_session() -> Iterator[Session]`.

- [ ] **Step 1: Write the failing model test**

`backend/tests/test_models.py`:
```python
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import Base, ChatMessage, Dataset


def _session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}", future=True)
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
    dataset = Dataset(
        name="d.csv", n_rows=1, n_cols=1, profile_json={}, data_csv="x\n1\n"
    )
    session.add(dataset)
    session.flush()
    msg = ChatMessage(dataset_id=dataset.id, role="user", content="hello")
    session.add(msg)
    session.commit()

    assert msg.tool_calls == []
    assert msg.tokens_in == 0
    assert msg.cost_usd == 0.0
    assert msg.latency_ms == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `poetry run pytest backend/tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models'`.

- [ ] **Step 3: Write the configuration module**

`backend/app/config.py`:
```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./dev.db"
    max_upload_bytes: int = 50 * 1024 * 1024  # 50 MB
    max_rows: int = 1_000_000

    # Profiler tunables (design §4) — single source of truth; override per-env via .env.
    profile_max_cardinality: int = 20  # value_counts only for non-numeric cols at/below this; top-N
    profile_max_corr_cols: int = 30  # full correlation matrix up to this many numeric cols
    profile_top_corr_pairs: int = 25  # beyond the col cap, keep only the strongest N pairs
    profile_sample_rows: int = 5  # sample rows included in the profile
    profile_token_budget: int = 8000  # approx token ceiling for the assembled profile


settings = Settings()
```

Also create `.env.example` (committed; the real `.env` is gitignored) documenting every
override. pydantic-settings matches env names case-insensitively, so `PROFILE_MAX_CARDINALITY`
→ `profile_max_cardinality`:
```dotenv
# Database (production uses Postgres; tests/dev default to SQLite)
DATABASE_URL=sqlite:///./dev.db

# Upload limits
MAX_UPLOAD_BYTES=52428800
MAX_ROWS=1000000

# Profiler tunables (design §4)
PROFILE_MAX_CARDINALITY=20
PROFILE_MAX_CORR_COLS=30
PROFILE_TOP_CORR_PAIRS=25
PROFILE_SAMPLE_ROWS=5
PROFILE_TOKEN_BUDGET=8000
```

- [ ] **Step 4: Write the models**

`backend/app/models.py`:
```python
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    n_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    n_cols: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    data_csv: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tool_calls: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

> `data_csv` is `Text` (→ `text` on Postgres, `TEXT` on SQLite) — the single durable copy of the uploaded data, stored verbatim as the raw CSV (design D5). No `users` table and no `chart_urls`/`storage_key` columns: charts are re-rendered on demand in a later plan from `data_csv` + `tool_calls`.

- [ ] **Step 5: Write the database session module**

`backend/app/db.py`:
```python
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import Base

engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `poetry run pytest backend/tests/test_models.py -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add .env.example backend/app/config.py backend/app/models.py backend/app/db.py backend/tests/test_models.py
git commit -m "feat: add settings, SQLAlchemy models (datasets + chat_messages), and DB session"
```

---

### Task 3: CSV (de)serialization helper

**Files:**
- Create: `backend/app/dataset_io.py`
- Test: `backend/tests/test_dataset_io.py`

**Interfaces:**
- Consumes: nothing from other tasks (pure functions over bytes / a CSV string).
- Produces:
  - `app.dataset_io.decode_csv(raw: bytes) -> str` — decode uploaded bytes (UTF-8) to the raw CSV text stored in `datasets.data_csv`.
  - `app.dataset_io.load_csv(data_csv: str) -> pandas.DataFrame` — parse stored CSV text back to a DataFrame; the single canonical parser, used at upload and by later plans to re-render charts (so profiling and re-render see identical dtypes).

- [ ] **Step 1: Write the failing CSV-helper test**

`backend/tests/test_dataset_io.py`:
```python
import io

import pandas as pd
from pandas.testing import assert_frame_equal

from app.dataset_io import decode_csv, load_csv


def test_decode_returns_raw_text():
    raw = b"age,city\n20,NY\n30,LA\n"
    assert decode_csv(raw) == "age,city\n20,NY\n30,LA\n"


def test_round_trip_matches_pandas_parse():
    raw = b"age,city\n20,NY\n30,NY\n40,LA\n"
    restored = load_csv(decode_csv(raw))
    expected = pd.read_csv(io.BytesIO(raw))
    assert_frame_equal(restored, expected)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `poetry run pytest backend/tests/test_dataset_io.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.dataset_io'`.

- [ ] **Step 3: Write the CSV helper**

`backend/app/dataset_io.py`:
```python
from __future__ import annotations

import io

import pandas as pd


def decode_csv(raw: bytes) -> str:
    return raw.decode("utf-8")


def load_csv(data_csv: str) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(data_csv))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `poetry run pytest backend/tests/test_dataset_io.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/dataset_io.py backend/tests/test_dataset_io.py
git commit -m "feat: add CSV (de)serialization helper (bytes -> text -> DataFrame)"
```

---

### Task 4: Profiler (bounded rich profile)

Implements the full design §4 profiling policy — the Project 1 context-engineering lesson made concrete: a profile that is a *bounded summary*, never a data dump.

**Files:**
- Create: `backend/app/profiler.py`
- Test: `backend/tests/test_profiler.py`

**Interfaces:**
- Consumes: nothing from other tasks (pure function over a DataFrame).
- Produces:
  - `app.profiler.profile_dataframe(df, sample_rows=5, max_cardinality=20, max_corr_cols=30, top_corr_pairs=25, token_budget=8000) -> dict` returning keys: `n_rows`, `n_cols`, `columns` (list of `{name, dtype, n_null}`), `numeric_summary` (`{col: {stat: float}}` from `describe()`), `categorical_summary` (`{col: {value: count}}`, **only** for non-numeric columns with cardinality ≤ `max_cardinality`, top `max_cardinality` values), `correlations` (list of `{a, b, abs_corr}`; full pairwise list when numeric columns ≤ `max_corr_cols`, else the strongest `top_corr_pairs`), `sample_rows` (list of row dicts with NaN → None), and `degraded` (bool). If the assembled profile exceeds `token_budget`, it degrades to schema + `numeric_summary` + `correlations` only (categorical/sample dropped, `degraded=True`).

- [ ] **Step 1: Write the failing profiler test**

`backend/tests/test_profiler.py`:
```python
import numpy as np
import pandas as pd

from app.profiler import profile_dataframe


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "age": [20, 30, 40, np.nan],
            "income": [100, 200, 300, 400],
            "city": ["NY", "NY", "LA", "LA"],
        }
    )


def test_shape_and_columns():
    profile = profile_dataframe(_frame())
    assert profile["n_rows"] == 4
    assert profile["n_cols"] == 3
    names = {c["name"]: c for c in profile["columns"]}
    assert names["age"]["n_null"] == 1
    assert names["income"]["n_null"] == 0


def test_numeric_summary_has_mean():
    profile = profile_dataframe(_frame())
    assert "income" in profile["numeric_summary"]
    assert profile["numeric_summary"]["income"]["mean"] == 250.0


def test_categorical_summary_counts():
    profile = profile_dataframe(_frame())
    assert profile["categorical_summary"]["city"] == {"NY": 2, "LA": 2}


def test_high_cardinality_column_skipped():
    df = pd.DataFrame({"id": [f"u{i}" for i in range(50)]})
    profile = profile_dataframe(df, max_cardinality=20)
    assert "id" not in profile["categorical_summary"]


def test_correlations_present_and_sorted():
    profile = profile_dataframe(_frame())
    assert len(profile["correlations"]) >= 1
    assert profile["correlations"][0]["abs_corr"] >= profile["correlations"][-1]["abs_corr"]


def test_sample_rows_nan_becomes_none():
    profile = profile_dataframe(_frame())
    assert profile["sample_rows"][3]["age"] is None


def test_profile_degrades_over_token_budget():
    profile = profile_dataframe(_frame(), token_budget=1)
    assert profile["degraded"] is True
    assert profile["categorical_summary"] == {}
    assert profile["sample_rows"] == []
    # schema + describe + correlations survive the degrade
    assert profile["columns"]
    assert profile["numeric_summary"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `poetry run pytest backend/tests/test_profiler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.profiler'`.

- [ ] **Step 3: Write the profiler**

`backend/app/profiler.py`:
```python
from __future__ import annotations

import json
from typing import Any

import pandas as pd


def _estimate_tokens(profile: dict[str, Any]) -> int:
    # Cheap proxy: ~4 characters per token over the serialized profile.
    return len(json.dumps(profile, default=str)) // 4


# Keyword defaults mirror `app.config.Settings` so the function stays unit-testable in
# isolation; the upload route passes the live `settings.profile_*` values explicitly, which
# are the single source of truth (overridable via `.env`, see design §4).
def profile_dataframe(
    df: pd.DataFrame,
    sample_rows: int = 5,
    max_cardinality: int = 20,
    max_corr_cols: int = 30,
    top_corr_pairs: int = 25,
    token_budget: int = 8000,
) -> dict[str, Any]:
    numeric = df.select_dtypes(include="number")

    columns = [
        {"name": str(c), "dtype": str(df[c].dtype), "n_null": int(df[c].isna().sum())}
        for c in df.columns
    ]

    numeric_summary: dict[str, Any] = {}
    if not numeric.empty:
        desc = numeric.describe().to_dict()
        numeric_summary = {
            str(col): {str(stat): float(val) for stat, val in stats.items()}
            for col, stats in desc.items()
        }

    # Correlations: full pairwise list when within the column cap, else only the
    # strongest `top_corr_pairs` pairs (design §4).
    correlations: list[dict[str, Any]] = []
    if numeric.shape[1] >= 2:
        corr = numeric.corr().abs()
        cols = list(corr.columns)
        pairs: list[dict[str, Any]] = []
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                pairs.append(
                    {"a": str(cols[i]), "b": str(cols[j]), "abs_corr": float(corr.iloc[i, j])}
                )
        pairs.sort(key=lambda p: p["abs_corr"], reverse=True)
        correlations = pairs if numeric.shape[1] <= max_corr_cols else pairs[:top_corr_pairs]

    # Cardinality-aware value_counts: only low-cardinality non-numeric columns,
    # top `max_cardinality` values. High-cardinality columns (IDs, free text,
    # timestamps) are skipped — they bloat context and teach Claude nothing.
    categorical_summary: dict[str, Any] = {}
    for col in df.select_dtypes(exclude="number").columns:
        if df[col].nunique(dropna=True) > max_cardinality:
            continue
        counts = df[col].value_counts().head(max_cardinality)
        categorical_summary[str(col)] = {
            str(value): int(count) for value, count in counts.items()
        }

    sample = df.head(sample_rows)
    sample = sample.where(pd.notna(sample), None)
    sample_records = sample.to_dict(orient="records")

    profile: dict[str, Any] = {
        "n_rows": int(len(df)),
        "n_cols": int(df.shape[1]),
        "columns": columns,
        "numeric_summary": numeric_summary,
        "categorical_summary": categorical_summary,
        "correlations": correlations,
        "sample_rows": sample_records,
        "degraded": False,
    }

    # Profile-token budget: if the assembled profile is too large, degrade to
    # schema + describe() + correlations only (design §4).
    if _estimate_tokens(profile) > token_budget:
        profile = {
            "n_rows": profile["n_rows"],
            "n_cols": profile["n_cols"],
            "columns": columns,
            "numeric_summary": numeric_summary,
            "categorical_summary": {},
            "correlations": correlations,
            "sample_rows": [],
            "degraded": True,
        }
    return profile
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `poetry run pytest backend/tests/test_profiler.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/profiler.py backend/tests/test_profiler.py
git commit -m "feat: add profile_dataframe bounded rich profiler (design §4)"
```

---

### Task 5: Datasets route (upload → validate → profile → persist; get by id)

**Files:**
- Create: `backend/app/schemas.py`
- Create: `backend/app/routes/__init__.py` (empty)
- Create: `backend/app/routes/datasets.py`
- Modify: `backend/app/main.py` (enable `datasets.router` include — uncomment from Task 1 Step 6)
- Test: `backend/tests/test_datasets.py`

**Interfaces:**
- Consumes: `app.db.get_session`, `app.models.Dataset`, `app.profiler.profile_dataframe`,
  `app.dataset_io.decode_csv`, `app.dataset_io.load_csv`, `app.config.settings`, `app.schemas.DatasetOut`.
- Produces:
  - `app.schemas.DatasetOut(id: str, name: str, n_rows: int, n_cols: int)`.
  - `app.routes.datasets.router` — `POST /datasets` (multipart: `file`), `GET /datasets/{dataset_id}`.

- [ ] **Step 1: Write the failing datasets tests**

`backend/tests/test_datasets.py`:
```python
import io


def _csv_bytes() -> bytes:
    return b"age,income,city\n20,100,NY\n30,200,NY\n40,300,LA\n"


def test_upload_csv_persists_and_profiles(client):
    files = {"file": ("sales.csv", io.BytesIO(_csv_bytes()), "text/csv")}
    response = client.post("/datasets", files=files)
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "sales.csv"
    assert body["n_rows"] == 3
    assert body["n_cols"] == 3
    assert body["id"]


def test_get_dataset_by_id(client):
    files = {"file": ("sales.csv", io.BytesIO(_csv_bytes()), "text/csv")}
    created = client.post("/datasets", files=files).json()
    fetched = client.get(f"/datasets/{created['id']}").json()
    assert fetched["id"] == created["id"]
    assert fetched["name"] == "sales.csv"


def test_get_missing_dataset_404(client):
    assert client.get("/datasets/does-not-exist").status_code == 404


def test_reject_non_csv(client):
    files = {"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")}
    response = client.post("/datasets", files=files)
    assert response.status_code == 400


def test_reject_empty_csv(client):
    files = {"file": ("empty.csv", io.BytesIO(b"a,b\n"), "text/csv")}
    response = client.post("/datasets", files=files)
    assert response.status_code == 400
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `poetry run pytest backend/tests/test_datasets.py -v`
Expected: FAIL — `404 Not Found` or ImportError on `app.routes.datasets`.

- [ ] **Step 3: Write the Pydantic schema**

`backend/app/schemas.py`:
```python
from pydantic import BaseModel, ConfigDict


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    n_rows: int
    n_cols: int
```

- [ ] **Step 4: Write the datasets router**

`backend/app/routes/datasets.py`:
```python
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.dataset_io import decode_csv, load_csv
from app.db import get_session
from app.models import Dataset
from app.profiler import profile_dataframe
from app.schemas import DatasetOut

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.post("", response_model=DatasetOut)
def upload_dataset(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> Dataset:
    raw = file.file.read()
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="File exceeds size limit")
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are accepted")
    try:
        data_csv = decode_csv(raw)
        df = load_csv(data_csv)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {exc}") from exc
    if df.empty:
        raise HTTPException(status_code=400, detail="CSV has no rows")
    if len(df) > settings.max_rows:
        raise HTTPException(status_code=413, detail="CSV exceeds row limit")

    dataset = Dataset(
        name=file.filename or "dataset.csv",
        n_rows=int(len(df)),
        n_cols=int(df.shape[1]),
        profile_json=profile_dataframe(
            df,
            sample_rows=settings.profile_sample_rows,
            max_cardinality=settings.profile_max_cardinality,
            max_corr_cols=settings.profile_max_corr_cols,
            top_corr_pairs=settings.profile_top_corr_pairs,
            token_budget=settings.profile_token_budget,
        ),
        data_csv=data_csv,
    )
    session.add(dataset)
    session.commit()
    session.refresh(dataset)
    return dataset


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: str, session: Session = Depends(get_session)) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset
```

> The uploaded data is stored verbatim as raw CSV text inline on the `datasets` row (design D5) — no object store, no file on disk. The returned `dataset.id` is the shareable link (design D4); a later plan adds `GET /datasets/{id}/...` thread + `/chat`.

- [ ] **Step 5: Enable the router in `main.py`**

Confirm these lines in `create_app` (uncomment if they were commented in Task 1):
```python
    from app.routes import datasets

    app.include_router(datasets.router)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `poetry run pytest backend/tests/test_datasets.py -v`
Expected: PASS (5 passed).

- [ ] **Step 7: Run the full suite and the quality gate**

Run: `make check`
Expected: ruff clean, black clean, mypy clean, all tests pass (health + models + dataset_io + profiler + datasets).

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas.py backend/app/routes/__init__.py backend/app/routes/datasets.py backend/app/main.py backend/tests/test_datasets.py
git commit -m "feat: add dataset upload (validate + profile + raw-CSV persist) and get-by-id routes"
```

---

## Self-Review

**1. Spec coverage (against the design doc, Plan 1 scope):**
- No auth / dataset-link identity (D4) → no `users` table or route; a dataset id is its shareable link (Tasks 2 + 5). ✓
- Upload a CSV → Task 5 (`POST /datasets`, multipart `file`, no `user_id`). ✓
- Bounded rich profile per §4 (cardinality gating, correlation caps, token budget + graceful degradation) computed and persisted → Task 4 (`profile_dataframe`) + Task 5 (stored in `datasets.profile_json`). ✓
- Raw-CSV-in-Postgres, no object store (D5) → Task 3 (`dataset_io` helper) + Task 2 (`data_csv` `Text`) + Task 5 (store on upload). Charts re-rendered in a later plan. ✓
- Datasets persist (survive restart) → Tasks 2 + 5 (Postgres row + raw CSV text). ✓
- `chat_messages` table ready for the chat plan → Task 2 (model defined with `tool_calls`, `tokens_in/out`, `cost_usd`, `latency_ms`; no `chart_urls` — charts re-rendered; route deferred, intentionally out of scope). ✓
- Engineering standards (`make check`, ruff/black/mypy/pytest) → Task 1 + Task 5 Step 7. ✓
- Validation/error handling (bad/oversized/empty CSV) → Task 5 (4xx with messages, validated before profiling). ✓
- LLM `/chat`, analysis engine, frontend, eval, rate-limit/token-ceiling, deploy → **intentionally not in this plan** (later plans). ✓

**2. Placeholder scan:** No "TBD/TODO/handle edge cases" — every code step shows complete code. The only forward-references (conftest importing modules created in Task 2; router include toggled in Tasks 1/5) are called out explicitly with instructions, not left vague. ✓

**3. Type consistency:** `profile_dataframe(df, ...) -> dict` consumed identically in Task 5. `get_session` dependency name matches between `conftest.py` override (Task 1), its definition (Task 2), and route usage (Task 5). `Dataset` field names (`profile_json`, `data_csv`, `n_rows`, `n_cols`) are consistent across model (Task 2), route (Task 5), and `DatasetOut` (Task 5). `decode_csv`/`load_csv` signatures (Task 3) match their calls in Task 5. ✓

No issues found that need a new task.
