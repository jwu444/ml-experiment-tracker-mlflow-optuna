# Project 2 Phase 1 — Foundations and Domain Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Project 1 fork into a Project 2 foundation: continuous integration, a pgvector-capable Postgres plus a local Jaeger, the `experiments` and `experiment_note_chunks` tables, an MLflow tracking store sharing that Postgres, and a real computer-component dataset loaded through the existing upload pipeline.

**Architecture:** Nothing model-related is built here. Every deliverable is a prerequisite that Phase 2 (training/Optuna) or Phase 3 (embeddings/agent) consumes. The one non-obvious piece of engineering is making the pgvector `Vector` column coexist with the SQLite test backend — solved with `Vector(512).with_variant(sa.JSON(), "sqlite")`, which has been verified to emit `VECTOR(512)` on Postgres, `JSON` on SQLite, and round-trip a Python `list[float]` on both.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Alembic (backend) · Postgres 16 + pgvector · MLflow 3 · OpenTelemetry/Jaeger (provisioned here, used in Phase 3) · Docker Compose · GitHub Actions · pytest · React 18 + Vite + Vitest (unchanged this phase).

## Table of contents

- [Global Constraints](#global-constraints)
- [Task 1: GitHub Actions CI](#task-1-github-actions-ci)
- [Task 2: Correct the stale Project 2 claims in the docs](#task-2-correct-the-stale-project-2-claims-in-the-docs)
- [Task 3: Docker Compose — Postgres with pgvector, and Jaeger](#task-3-docker-compose--postgres-with-pgvector-and-jaeger)
- [Task 4: `experiments` and `experiment_note_chunks` models](#task-4-experiments-and-experiment_note_chunks-models)
- [Task 5: Alembic migration for the new tables](#task-5-alembic-migration-for-the-new-tables)
- [Task 6: MLflow tracking store on the shared Postgres](#task-6-mlflow-tracking-store-on-the-shared-postgres)
- [Task 7: Ingest the computer-component dataset](#task-7-ingest-the-computer-component-dataset)
- [Task 8: Close out Phase 1](#task-8-close-out-phase-1)
- [Phase 1 exit criteria](#phase-1-exit-criteria)
- [What Phase 2 picks up](#what-phase-2-picks-up)

Every task below ends with a **Student checkpoint** — a plain-language summary of
what got built and a short list of things to personally verify before moving on.
Since this phase is foundational (CI, database schema, migrations) and less
visibly "working" than a UI feature, use those checkpoints to build a real
understanding of the flow, not just to confirm commands exited 0.

## Global Constraints

- Design spec: `doc/project-2-ml-experiment-tracker-design.md`. Program plan: `doc/plans/2026-08-05-project-2-overall-implementation-plan.md` §2.
- Python **3.12** (`.python-version` pins `3.12`; the Poetry venv must be `py3.12`, not the system 3.13).
- Line length **100** for both ruff and black; `target-version = py312`.
- ruff lint select is `["E", "F", "I", "B", "UP"]`; `backend/alembic/versions` is excluded from ruff **and** black. Hand-written `backend/alembic/env.py` **is** linted.
- mypy runs `strict = true` over `backend/app` only.
- pytest: `pythonpath = ["backend"]`, `testpaths = ["backend/tests"]`.
- **Models bind to the Postgres `app` schema.** SQLite (local default + test backend) has no schemas, so `app/db.py`, `backend/alembic/env.py`, and `backend/tests/conftest.py` all apply `schema_translate_map={"app": None}`. Any new model must keep working under that translation.
- **No `users` table, no auth (D2).** `experiments` gets no owner/user FK.
- **MLflow owns the `mlflow` schema (D4).** Never model MLflow's tables in `app/models.py`; never query them through our ORM. Access is via the `mlflow` SDK only.
- Alembic head at the start of this phase is `342d02b2a507`. New revisions chain from it.
- Doc-sync rule (`CLAUDE.md`): update `README.md` + `CLAUDE.md` in the same task that changes user-facing behavior.
- Every task ends green: `make check` (ruff + black --check + mypy + pytest). Frontend is untouched this phase, but `npm run type-check && npm test` must still pass in CI.
- Secrets never land in git. `.env` is gitignored; only `.env.example` is committed, with empty values for anything secret.

---

### Task 1: GitHub Actions CI

CI is first because every later task's definition of "done" is "CI green." Building it last means four weeks of unverified merges.

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: a required status check named `backend` and one named `frontend`, running on every push and PR to `main`.

- [x] **Step 1: Confirm the branch and a green local baseline**

```bash
git rev-parse --abbrev-ref HEAD    # expect: docs/project-2-implementation-plan or a new feature branch
make check
cd frontend && npm run type-check && npm test -- --run && cd ..
```

Expected: all green. If `make check` fails here, stop — CI would only be encoding a broken baseline. If the Poetry venv reports Python 3.13, fix it first:

```bash
poetry env remove --all
poetry env use "$(pyenv which python3.12)"
poetry install
poetry run python --version    # expect: Python 3.12.x
```

- [x] **Step 2: Write the workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install Poetry
        run: pipx install poetry

      - name: Cache the virtualenv
        uses: actions/cache@v4
        with:
          path: .venv
          key: venv-${{ runner.os }}-py312-${{ hashFiles('poetry.lock') }}

      - name: Install dependencies
        run: |
          poetry config virtualenvs.in-project true
          poetry install --no-interaction

      # `make check` == lint + format-check + type-check + test.
      # Tests use the SQLite backend, so no service container is needed.
      - name: make check
        run: make check

  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm
          cache-dependency-path: frontend/package-lock.json

      - run: npm ci

      - run: npm run type-check

      - run: npm test

      - run: npm run build
```

- [x] **Step 3: Verify the workflow parses**

```bash
python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('yaml ok')"
```

Expected: `yaml ok`.

- [x] **Step 4: Commit and push, then watch the run**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add GitHub Actions workflow for backend and frontend checks"
git push
gh run watch
```

Expected: both `backend` and `frontend` jobs succeed. If `npm ci` fails because `frontend/package-lock.json` is absent, run `cd frontend && npm install` locally, commit the lockfile, and push again.

- [x] **Step 5: Make the checks required on `main`**

```bash
gh api -X PUT "repos/{owner}/{repo}/branches/main/protection" \
  -H "Accept: application/vnd.github+json" \
  -f 'required_status_checks[strict]=true' \
  -f 'required_status_checks[contexts][]=backend' \
  -f 'required_status_checks[contexts][]=frontend' \
  -F 'enforce_admins=false' \
  -F 'required_pull_request_reviews=null' \
  -F 'restrictions=null'
```

Expected: a JSON protection object. If this returns 403 (branch protection unavailable on the plan), skip it and note in the PR that the checks are advisory.

#### Student checkpoint

**What's implemented:** A GitHub Actions workflow (`.github/workflows/ci.yml`) that
runs on every push/PR to `main`: a `backend` job (`make check` — lint,
format-check, mypy, pytest) and a `frontend` job (type-check, test, build).
Branch protection, if available on the plan, makes both required before a PR
can merge.

**What to verify:**
- Open the repo's GitHub Actions tab and look at the real run — confirm both
  `backend` and `frontend` are green, rather than trusting the plan's
  "Expected" text.
- If Step 5's branch-protection call returned 403, note that yourself in the
  PR — it means the plan doesn't support required checks, not that something
  broke.
- Every later task's "done" now depends on `make check` passing in CI — if
  you're not sure what it actually runs (lint + format-check + type-check +
  test), this is the moment to ask, since you'll be relying on it for the
  rest of the workshop.

---

### Task 2: Correct the stale Project 2 claims in the docs

Three committed sentences inherited from Project 1 now assert things the design explicitly rejected. D2 says there is **no auth** in Project 2, so the "Project 2 adds auth" claims are wrong, and this repo is no longer Project 1.

**Files:**
- Modify: `CLAUDE.md:7`, `CLAUDE.md:121`
- Modify: `README.md:1-9`

- [x] **Step 1: Fix the stale auth claim in the CLAUDE.md summary**

In `CLAUDE.md` line 7, the paragraph currently ends with:

```
Full-stack: **FastAPI** backend + **React/Vite/TypeScript** frontend (`frontend/`). Project 2 forks this repo to add a real agent loop and auth.
```

Replace that final sentence so the line ends:

```
Full-stack: **FastAPI** backend + **React/Vite/TypeScript** frontend (`frontend/`). **This repo is Project 2**, forked from Project 1 to add ML experiment tracking (MLflow + Optuna), retrieval over experiment history, and a hand-rolled agent loop. Project 2 deliberately does **not** add auth (design D2).
```

- [x] **Step 2: Fix the stale auth claim in the decisions section**

In `CLAUDE.md` line 121, replace:

```
**No `users` table, no auth (D4).** A dataset `id` is its own shareable link. There is no user scoping, no login, no session. Do not add a `User` model or FK — that arrives in the Project 2 fork.
```

with:

```
**No `users` table, no auth (Project 1 D4, reaffirmed by Project 2 D2).** A dataset `id` is its own shareable link. There is no user scoping, no login, no session. Do not add a `User` model or FK — Project 2 stays single-tenant, and `experiments` has no owner column.
```

- [x] **Step 3: Reframe the README opening**

Replace `README.md` lines 1–9:

```markdown
# WavePoint-Project-1 — CSV Analysis Assistant

Upload a CSV, ask natural-language questions, and get plots + statistics + an LLM
interpretation. Claude reads a bounded profile of your data, selects from a fixed
menu of pandas/plot tools (histogram, scatter, correlation matrix), and writes the
interpretation — all in a single LLM pass.

Project 1 of a 3-project AI Engineering Workshop. This repo is a full-stack app:
a **FastAPI** backend and a **React + Vite** frontend.
```

with:

```markdown
# WavePoint-Project-2 — ML Experiment Tracker

Project 2 of a 3-project AI Engineering Workshop, forked from Project 1's CSV
Analysis Assistant. It keeps Project 1's upload-and-ask flow — Claude reads a
bounded profile of your data, selects from a fixed menu of pandas/plot tools, and
writes an interpretation through a judge-gated multi-pass loop — and adds ML
experiment tracking on top: training runs logged to MLflow, hyperparameter search
with Optuna, retrieval over experiment history, and an agent that recommends what
to try next.

The working domain is computer-component pricing and demand (see
`doc/project-2-ml-experiment-tracker-design.md` §2). This repo is a full-stack
app: a **FastAPI** backend and a **React + Vite** frontend.

Design: `doc/project-2-ml-experiment-tracker-design.md` ·
Roadmap: `doc/plans/2026-08-05-project-2-overall-implementation-plan.md`
```

Note the deliberate correction: Project 1's README still said "all in a single LLM pass," which the judge-gated loop replaced.

- [x] **Step 4: Verify no stale claim survives**

```bash
grep -rn "add a real agent loop and auth\|arrives in the Project 2 fork\|single LLM pass" CLAUDE.md README.md
```

Expected: no output.

- [x] **Step 5: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: reframe repo as Project 2 and drop the stale auth claims (D2)"
```

#### Student checkpoint

**What's implemented:** Removes three sentences carried over from Project 1
that incorrectly claimed Project 2 would add auth, and rewrites the README's
opening to describe Project 2 (ML Experiment Tracker) instead of Project 1
(CSV Analysis Assistant).

**What to verify:**
- Read the actual diff of `CLAUDE.md` and `README.md` — not just the plan's
  inline snippets — and confirm the wording matches your own understanding
  of D2 (no auth, single-tenant, for the life of this project).
- Run the Step 4 `grep` yourself and confirm it prints nothing. That command
  is the actual proof the stale claim is gone; "the task ran" isn't.

---

### Task 3: Docker Compose — Postgres with pgvector, and Jaeger

Postgres 16 with the pgvector extension available, plus a local Jaeger all-in-one that Phase 3's tracing exports to. Provisioned now so Task 5's migration can be tested against a real Postgres rather than only SQLite.

**Files:**
- Create: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `Makefile`
- Modify: `README.md` (a "Local services" section)

**Interfaces:**
- Produces: Postgres reachable at `postgresql+psycopg2://wavepoint:wavepoint@localhost:5433/wavepoint`, with the `vector` extension installable. Jaeger UI at `http://localhost:16686`, OTLP gRPC at `localhost:4317`, OTLP HTTP at `localhost:4318`. Make targets `db-up`, `db-down`, `db-psql`.

Port 5433 (not 5432) is deliberate — it avoids colliding with any Postgres already running on the developer's machine.

- [x] **Step 1: Write the compose file**

Create `docker-compose.yml`:

```yaml
# Local dev services for Project 2. Not used in CI (tests run on SQLite) and not
# used in production (Render/Fly provide their own Postgres).
services:
  postgres:
    # pgvector's own image = stock Postgres 16 + the vector extension preinstalled.
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: wavepoint
      POSTGRES_PASSWORD: wavepoint
      POSTGRES_DB: wavepoint
    ports:
      - "5433:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U wavepoint -d wavepoint"]
      interval: 5s
      timeout: 5s
      retries: 10

  jaeger:
    # Trace viewer for Phase 3's OTel spans. Nothing exports to it until then.
    image: jaegertracing/all-in-one:1.62.0
    environment:
      COLLECTOR_OTLP_ENABLED: "true"
    ports:
      - "16686:16686"   # web UI
      - "4317:4317"     # OTLP gRPC
      - "4318:4318"     # OTLP HTTP

volumes:
  pgdata:
```

- [x] **Step 2: Add the Make targets**

In `Makefile`, add `db-up db-down db-psql` to the `.PHONY` line, then append:

```makefile
db-up:
	docker compose up -d
	@echo "Postgres  -> postgresql+psycopg2://wavepoint:wavepoint@localhost:5433/wavepoint"
	@echo "Jaeger UI -> http://localhost:16686"

db-down:
	docker compose down

db-psql:
	docker compose exec postgres psql -U wavepoint -d wavepoint
```

- [x] **Step 3: Document the Postgres URL in `.env.example`**

Replace the first two lines of `.env.example`:

```
# Database (production uses Postgres; tests/dev default to SQLite)
DATABASE_URL=sqlite:///./dev.db
```

with:

```
# Database. Tests and the zero-setup default use SQLite. Anything involving
# pgvector or MLflow needs the Postgres from `make db-up` — uncomment that line.
DATABASE_URL=sqlite:///./dev.db
# DATABASE_URL=postgresql+psycopg2://wavepoint:wavepoint@localhost:5433/wavepoint
```

- [x] **Step 4: Bring the stack up and verify pgvector is installable**

```bash
make db-up
sleep 5
docker compose exec -T postgres psql -U wavepoint -d wavepoint \
  -c "CREATE EXTENSION IF NOT EXISTS vector;" \
  -c "SELECT extversion FROM pg_extension WHERE extname = 'vector';"
curl -s -o /dev/null -w "jaeger:%{http_code}\n" http://localhost:16686
```

Expected: `CREATE EXTENSION`, a version row (e.g. `0.8.x`), and `jaeger:200`.

- [x] **Step 5: Document it in the README**

Add a `## Local services` section to `README.md` immediately after the "Run the webapp" section:

```markdown
## Local services (Postgres + Jaeger)

SQLite is the zero-setup default and the test backend. Postgres is required for
anything touching pgvector or MLflow:

```bash
make db-up      # Postgres on :5433, Jaeger UI on :16686
make db-psql    # psql shell
make db-down    # stop
```

Then point `DATABASE_URL` at it in `.env` (see `.env.example`) and run
`make migrate`.
```

- [x] **Step 6: Confirm nothing new needs gitignoring**

```bash
git status --short
```

Expected: only `docker-compose.yml`, `Makefile`, `.env.example`, `README.md`. The Postgres volume is a named Docker volume, not a bind mount, so nothing lands in the working tree. If anything else appears, add it to `.gitignore`.

- [x] **Step 7: Commit**

```bash
git add docker-compose.yml Makefile .env.example README.md
git commit -m "feat: add docker-compose with pgvector Postgres and local Jaeger"
```

#### Student checkpoint

**What's implemented:** A `docker-compose.yml` that runs Postgres 16 (the
`pgvector/pgvector:pg16` image, with the vector extension pre-installed) on
port 5433, plus a Jaeger all-in-one trace viewer on port 16686. `make db-up` /
`db-down` / `db-psql` wrap it, documented in the README.

**What to verify:**
- After `make db-up`, run `docker compose ps` yourself and see both
  containers actually `healthy`/`running` — don't just read the plan's
  expected output.
- Open `http://localhost:16686` in a real browser and confirm the Jaeger UI
  loads. It'll be empty until Phase 3 starts exporting spans — that's
  expected, not a bug.
- Understand *why* port 5433 was chosen (avoiding a collision with any
  Postgres already running on your machine) — you'll need to remember this
  whenever you point `DATABASE_URL` at this container.

---

### Task 4: `experiments` and `experiment_note_chunks` models

The two new tables from design §7. The `embedding` column must compile on Postgres (as `VECTOR`) and on SQLite (as `JSON`), because the whole test suite runs on SQLite.

**Files:**
- Modify: `pyproject.toml` (add `pgvector`)
- Modify: `backend/app/models.py`
- Modify: `backend/tests/test_models.py`

**Interfaces:**
- Consumes: `Base`, `_uuid`, and `Dataset` from `app/models.py`.
- Produces:
  - `EMBEDDING_DIM: int = 512`
  - `Experiment` — `id: str`, `mlflow_run_id: str`, `dataset_id: str | None`, `dataset_version: str | None`, `model_type: str`, `notes: str`, `created_at: datetime`
  - `ExperimentNoteChunk` — `id: str`, `experiment_id: str`, `chunk_text: str`, `chunk_index: int`, `embedding: list[float]`

  Phase 2 writes `Experiment`; Phase 3 writes `ExperimentNoteChunk`.

**On the 512 dimension:** the embedding provider is not chosen until Phase 3, but the column needs a width now. 512 is picked because it is a native output width for the light hosted embedding models under consideration. The table is empty until Phase 3, so if that phase picks a model with a different native width, a follow-up migration can `ALTER TABLE ... ALTER COLUMN embedding TYPE vector(N)` with no data to preserve. Do not treat 512 as load-bearing.

- [x] **Step 1: Add the pgvector dependency**

```bash
poetry add "pgvector@^0.5"
poetry run python -c "import pgvector.sqlalchemy; print('pgvector ok')"
```

Expected: `pgvector ok`, and `pyproject.toml` gains `pgvector = "^0.5"` under `[tool.poetry.dependencies]`.

- [x] **Step 2: Write the failing tests**

Append to `backend/tests/test_models.py`:

```python
def test_experiment_persists_with_nullable_dataset_fk(tmp_path):
    session = _session(tmp_path)
    dataset = Dataset(
        name="gpus.csv",
        n_rows=2,
        n_cols=2,
        profile_json={},
        data_csv="a,b\n1,2\n3,4\n",
        content_hash="c" * 64,
    )
    session.add(dataset)
    session.flush()

    linked = Experiment(
        mlflow_run_id="run-linked",
        dataset_id=dataset.id,
        model_type="ridge",
        notes="baseline on the GPU price table",
    )
    # D5: a run against data that never went through /datasets records only a
    # free-text version string, so dataset_id must be nullable.
    unlinked = Experiment(
        mlflow_run_id="run-unlinked",
        dataset_version="pc-part-dataset@2026-08-05",
        model_type="ridge",
        notes="baseline on an external snapshot",
    )
    session.add_all([linked, unlinked])
    session.commit()

    assert session.get(Experiment, linked.id).dataset_id == dataset.id
    assert session.get(Experiment, unlinked.id).dataset_id is None
    assert Experiment.__table__.c.dataset_id.nullable is True
    assert Experiment.__table__.c.dataset_id.index is True


def test_experiment_has_no_owner_column() -> None:
    # D2: single-tenant, no auth. No user/owner FK, ever.
    cols = {c.name for c in Experiment.__table__.columns}
    assert "user_id" not in cols
    assert "owner_id" not in cols


def test_note_chunk_roundtrips_an_embedding(tmp_path):
    session = _session(tmp_path)
    experiment = Experiment(mlflow_run_id="run-1", model_type="ridge", notes="n")
    session.add(experiment)
    session.flush()

    vector = [0.5] * EMBEDDING_DIM
    session.add(
        ExperimentNoteChunk(
            experiment_id=experiment.id,
            chunk_text="tried a wider alpha range",
            chunk_index=0,
            embedding=vector,
        )
    )
    session.commit()

    loaded = session.scalar(select(ExperimentNoteChunk))
    assert loaded is not None
    assert list(loaded.embedding) == vector
    assert loaded.chunk_index == 0
    assert ExperimentNoteChunk.__table__.c.experiment_id.index is True


def test_note_chunk_unique_per_experiment_and_index() -> None:
    unique_cols = {
        tuple(sorted(col.name for col in c.columns))
        for c in ExperimentNoteChunk.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    }
    assert ("chunk_index", "experiment_id") in unique_cols


def test_embedding_column_compiles_on_both_dialects() -> None:
    # The suite runs on SQLite; production runs on Postgres. One column
    # definition has to serve both.
    from sqlalchemy.dialects import postgresql, sqlite

    column = ExperimentNoteChunk.__table__.c.embedding
    assert "VECTOR(512)" in str(column.type.compile(dialect=postgresql.dialect()))
    assert "JSON" in str(column.type.compile(dialect=sqlite.dialect()))
```

Extend the import on line 2 of that file to:

```python
from app.models import (
    EMBEDDING_DIM,
    Analysis,
    Base,
    Chat,
    ChatDataset,
    ChatMessage,
    Dataset,
    DatasetColumn,
    Experiment,
    ExperimentNoteChunk,
)
```

- [x] **Step 3: Run the tests to verify they fail**

Run: `poetry run pytest backend/tests/test_models.py -q`
Expected: collection error — `ImportError: cannot import name 'EMBEDDING_DIM' from 'app.models'`.

- [x] **Step 4: Add the models**

In `backend/app/models.py`, add this import after the existing `sqlalchemy` imports (`JSON`, `ForeignKey`, `Integer`, `String`, `Text`, `UniqueConstraint`, `DateTime`, and `func` are all already imported and all are reused below):

```python
from pgvector.sqlalchemy import Vector
```

Then append to the file:

```python
# Embedding width for `experiment_note_chunks.embedding`. The provider is chosen
# in Phase 3; this width is a placeholder that the (still empty) table can be
# migrated away from cheaply if that choice implies a different one.
EMBEDDING_DIM = 512


class Experiment(Base):
    """One logged training run. Params/metrics live in MLflow, not here (D4) —
    this row carries only what MLflow can't: the link back to our dataset and
    the free-text notes that Phase 3 embeds."""

    __tablename__ = "experiments"
    __table_args__ = {"schema": "app"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    mlflow_run_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # D5: nullable. A run against a dataset that went through /datasets sets
    # this; a run against an external snapshot sets dataset_version instead.
    dataset_id: Mapped[str | None] = mapped_column(
        ForeignKey("app.datasets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    dataset_version: Mapped[str | None] = mapped_column(String, nullable=True)
    model_type: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ExperimentNoteChunk(Base):
    """A chunk of an experiment's notes plus its embedding (D6). Written by
    Phase 3's app/embeddings.py; read by the agent's search_experiments tool."""

    __tablename__ = "experiment_note_chunks"
    __table_args__ = (
        UniqueConstraint(
            "experiment_id", "chunk_index", name="uq_note_chunks_experiment_id_chunk_index"
        ),
        {"schema": "app"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("app.experiments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # pgvector's VECTOR type has no SQLite equivalent, and the whole test suite
    # runs on SQLite. with_variant keeps one column definition serving both:
    # VECTOR(512) on Postgres, JSON on SQLite. Vector *operators* (<=>) remain
    # Postgres-only — Phase 3's similarity search is tested against Postgres.
    embedding: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_DIM).with_variant(JSON(), "sqlite"), nullable=False
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

- [x] **Step 5: Run the tests to verify they pass**

Run: `poetry run pytest backend/tests/test_models.py -q`
Expected: all pass, including the five new tests.

- [x] **Step 6: Run the full check**

Run: `make check`
Expected: ruff clean, black clean, mypy strict clean over `backend/app`, all 100+ tests pass.

If mypy objects to `Vector(...).with_variant(...)` returning an untyped value, add a narrowly scoped override to `pyproject.toml` rather than loosening strict mode globally:

```toml
[[tool.mypy.overrides]]
module = "pgvector.*"
ignore_missing_imports = true
```

- [x] **Step 7: Commit**

```bash
git add pyproject.toml poetry.lock backend/app/models.py backend/tests/test_models.py
git commit -m "feat: add Experiment and ExperimentNoteChunk models with pgvector embedding"
```

#### Student checkpoint

**What's implemented:** Two new SQLAlchemy models, `Experiment` and
`ExperimentNoteChunk` (design §7), added to `backend/app/models.py`. The
tricky part is the `embedding` column —
`Vector(512).with_variant(JSON(), "sqlite")` — which compiles to a real
pgvector `VECTOR(512)` on Postgres but degrades to plain `JSON` on SQLite,
which is what the test suite runs on.

**What to verify:**
- Read through the five new tests in `test_models.py` before running them —
  each one encodes a design decision (nullable `dataset_id` per D5, no
  `user_id`/`owner_id` column per D2, the unique constraint on chunk index,
  the two-dialect compile check). Understanding the tests *is* understanding
  the schema.
- Actually watch Step 3 fail (`ImportError`) and then Step 5 pass — seeing
  red-then-green is the point of this checkpoint, not just reading that it
  happened.
- Confirm you understand why `EMBEDDING_DIM = 512` is explicitly flagged as
  "not load-bearing" — the table is empty until Phase 3, so this is a
  placeholder width, not a considered design choice yet.

---

### Task 5: Alembic migration for the new tables

**Files:**
- Create: `backend/alembic/versions/<rev>_add_experiments_and_note_chunks.py`
- Create: `backend/tests/test_migrations.py`

**Interfaces:**
- Consumes: `Experiment` / `ExperimentNoteChunk` / `EMBEDDING_DIM` from Task 4.
- Produces: an Alembic revision whose `down_revision` is `342d02b2a507`, and which becomes the new head that Task 6 chains from.

- [x] **Step 1: Write a failing test that the head matches the models**

Create `backend/tests/test_migrations.py`:

```python
"""Guards on the migration history. These run on SQLite like everything else;
the Postgres-specific upgrade/downgrade cycle is verified manually in this
task's steps, because CI has no Postgres service."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _script_directory() -> ScriptDirectory:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "backend" / "alembic"))
    return ScriptDirectory.from_config(cfg)


def test_migration_history_has_exactly_one_head() -> None:
    # Two heads means someone branched the history without merging it.
    assert len(_script_directory().get_heads()) == 1


def test_every_orm_table_is_reachable_from_the_head() -> None:
    # Cheap drift guard: a model added without a migration fails here.
    from app.models import Base

    revisions = list(_script_directory().walk_revisions())
    sources = "\n".join(
        (Path(rev.path).read_text() if rev.path else "") for rev in revisions
    )
    for table_name in Base.metadata.tables:
        bare = table_name.split(".")[-1]
        assert bare in sources, f"{bare} has no migration"
```

- [x] **Step 2: Run it to verify it fails**

Run: `poetry run pytest backend/tests/test_migrations.py -q`
Expected: `test_every_orm_table_is_reachable_from_the_head` FAILS with `AssertionError: experiments has no migration`.

- [x] **Step 3: Point the environment at Postgres and autogenerate**

```bash
make db-up
export DATABASE_URL="postgresql+psycopg2://wavepoint:wavepoint@localhost:5433/wavepoint"
poetry run alembic upgrade head       # brings a fresh DB to 342d02b2a507
poetry run alembic revision --autogenerate -m "add experiments and note chunks"
```

Expected: a new file under `backend/alembic/versions/`. Autogenerate cannot see the pgvector extension requirement, so the generated file needs hand-editing in the next step.

- [x] **Step 4: Hand-edit the generated migration**

Open the new file and make it read as follows, keeping the generated `revision` string and setting `down_revision` to `'342d02b2a507'`:

```python
"""add experiments and note chunks

Revision ID: <keep the generated value>
Revises: 342d02b2a507
Create Date: <keep the generated value>

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = '<keep the generated value>'
down_revision: str | None = '342d02b2a507'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 512


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    # pgvector ships as an extension; the VECTOR type does not exist until it is
    # created. No-op on SQLite, which uses the JSON variant of the column.
    if _is_postgres():
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "experiments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("mlflow_run_id", sa.String(), nullable=False),
        # D5: nullable FK. SET NULL rather than CASCADE — deleting a dataset must
        # not erase the experiment history that referenced it.
        sa.Column("dataset_id", sa.String(), nullable=True),
        sa.Column("dataset_version", sa.String(), nullable=True),
        sa.Column("model_type", sa.String(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["dataset_id"], ["app.datasets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        schema="app",
    )
    op.create_index(
        "ix_app_experiments_mlflow_run_id", "experiments", ["mlflow_run_id"], schema="app"
    )
    op.create_index("ix_app_experiments_dataset_id", "experiments", ["dataset_id"], schema="app")

    op.create_table(
        "experiment_note_chunks",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("experiment_id", sa.String(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column(
            "embedding",
            Vector(EMBEDDING_DIM).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["experiment_id"], ["app.experiments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "experiment_id", "chunk_index", name="uq_note_chunks_experiment_id_chunk_index"
        ),
        schema="app",
    )
    op.create_index(
        "ix_app_experiment_note_chunks_experiment_id",
        "experiment_note_chunks",
        ["experiment_id"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_app_experiment_note_chunks_experiment_id",
        table_name="experiment_note_chunks",
        schema="app",
    )
    op.drop_table("experiment_note_chunks", schema="app")
    op.drop_index("ix_app_experiments_dataset_id", table_name="experiments", schema="app")
    op.drop_index("ix_app_experiments_mlflow_run_id", table_name="experiments", schema="app")
    op.drop_table("experiments", schema="app")
    # The vector extension is intentionally NOT dropped: other objects may use
    # it, and re-creating it is free.
```

No ANN index (`ivfflat` / `hnsw`) is created here. Those need a populated table to build meaningful centroids, and the table stays empty until Phase 3 — index creation belongs to that phase's plan.

- [x] **Step 5: Verify the round trip on Postgres**

```bash
export DATABASE_URL="postgresql+psycopg2://wavepoint:wavepoint@localhost:5433/wavepoint"
poetry run alembic upgrade head
docker compose exec -T postgres psql -U wavepoint -d wavepoint -c "\d app.experiment_note_chunks"
poetry run alembic downgrade -1
poetry run alembic upgrade head
```

Expected: `\d` shows `embedding | vector(512) | not null`; the downgrade drops both tables cleanly; the re-upgrade succeeds.

- [x] **Step 6: Verify autogenerate now sees no drift**

```bash
poetry run alembic revision --autogenerate -m "drift check"
```

Expected: the generated file's `upgrade()` body is just `pass`. Delete it:

```bash
rm backend/alembic/versions/*drift_check.py
```

If it is *not* empty, the migration and the models disagree — reconcile before continuing.

- [x] **Step 7: Verify the SQLite path still works**

```bash
unset DATABASE_URL
poetry run pytest backend/tests/test_migrations.py backend/tests/test_models.py -q
```

Expected: all pass.

- [x] **Step 8: Full check and commit**

```bash
make check
git add backend/alembic/versions backend/tests/test_migrations.py
git commit -m "feat: add migration for experiments and experiment_note_chunks"
```

#### Student checkpoint

**What's implemented:** An Alembic migration that creates the `experiments`
and `experiment_note_chunks` tables on Postgres, chained after the existing
head `342d02b2a507`, with a working `downgrade()`.

**What to verify:**
- Personally run the Step 5 upgrade → downgrade → upgrade cycle and look at
  the real `\d app.experiment_note_chunks` output — confirm with your own
  eyes that it shows `embedding | vector(512) | not null`.
- Run the Step 6 "drift check" yourself: after
  `alembic revision --autogenerate`, the generated file's `upgrade()` must be
  just `pass`. That emptiness is the actual proof that `models.py` and the
  migration agree — if it's not empty, stop and reconcile before continuing
  rather than committing anyway.
- Make sure you can explain *why* both a model (Task 4) and a migration
  (this task) are needed — the ORM describes the schema, but only Alembic
  actually changes the live Postgres database.

---

### Task 6: MLflow tracking store on the shared Postgres

MLflow runs its own schema migrations in a `mlflow` schema on the same database (D4). Our Alembic env sets `include_schemas=True` with no object filter, so the very next `--autogenerate` after MLflow initialises would see MLflow's tables as "extra" and emit `op.drop_table` for every one of them. That guard is the real deliverable of this task.

**Files:**
- Modify: `pyproject.toml` (add `mlflow`)
- Modify: `backend/app/config.py`
- Modify: `backend/alembic/env.py`
- Create: `backend/tests/test_alembic_env.py`
- Modify: `.env.example`
- Modify: `.gitignore`
- Modify: `README.md`

**Interfaces:**
- Consumes: the Postgres from Task 3; the migration head from Task 5.
- Produces:
  - `settings.mlflow_tracking_uri: str` and `settings.mlflow_artifact_root: str`
  - `app_schema_only(object_, name, type_, reflected, compare_to) -> bool` in `backend/alembic/env.py` — the autogenerate filter. Phase 2's `app/training.py` reads the two settings.

- [x] **Step 1: Write the failing test for the autogenerate filter**

Create `backend/tests/test_alembic_env.py`:

```python
"""The Alembic env runs autogenerate with include_schemas=True, which makes it
consider every schema in the database. MLflow owns the `mlflow` schema (design
D4) and manages it with its own migrations — without a filter, autogenerate
would propose dropping all of MLflow's tables."""

import importlib.util
from pathlib import Path
from types import ModuleType

_ENV_PATH = Path(__file__).resolve().parents[1] / "alembic" / "env.py"


def _load_filter():
    # env.py executes migrations at import time, so load the source and exec
    # only the filter function rather than importing the module.
    source = _ENV_PATH.read_text()
    start = source.index("def app_schema_only(")
    end = source.index("\ndef ", start + 1)
    namespace: dict[str, object] = {}
    exec(compile(source[start:end], str(_ENV_PATH), "exec"), namespace)
    return namespace["app_schema_only"]


class _FakeTable:
    def __init__(self, schema: str | None) -> None:
        self.schema = schema


def test_app_schema_tables_are_included() -> None:
    keep = _load_filter()
    assert keep(_FakeTable("app"), "experiments", "table", True, None) is True


def test_mlflow_schema_tables_are_excluded() -> None:
    keep = _load_filter()
    # MLflow's own tables — autogenerate must never touch these.
    assert keep(_FakeTable("mlflow"), "runs", "table", True, None) is False
    assert keep(_FakeTable("mlflow"), "alembic_version", "table", True, None) is False


def test_sqlite_default_schema_is_included() -> None:
    # Under schema_translate_map={"app": None} our tables report schema=None.
    keep = _load_filter()
    assert keep(_FakeTable(None), "experiments", "table", True, None) is True


def test_non_table_objects_are_always_included() -> None:
    # Columns/indexes are filtered by their parent table, not individually.
    keep = _load_filter()
    assert keep(_FakeTable("mlflow"), "some_column", "column", True, None) is True
```

- [x] **Step 2: Run it to verify it fails**

Run: `poetry run pytest backend/tests/test_alembic_env.py -q`
Expected: FAIL — `ValueError: substring not found` (there is no `app_schema_only` in `env.py` yet).

- [x] **Step 3: Add the filter to `backend/alembic/env.py`**

Insert this after the `_schema_map` assignment (currently line 31) and before `def run_migrations_offline()`:

```python
# MLflow owns the `mlflow` schema and migrates it itself (design D4). With
# include_schemas=True, autogenerate would otherwise see MLflow's tables as
# tables we no longer declare and emit a drop for each one. Restrict comparison
# to our own schema. `None` is included because SQLite's schema_translate_map
# reports our tables as unschema'd.
_OWNED_SCHEMAS = {"app", None}


def app_schema_only(object_, name, type_, reflected, compare_to) -> bool:  # type: ignore[no-untyped-def]
    if type_ == "table":
        return object_.schema in _OWNED_SCHEMAS
    return True
```

Then add `include_object=app_schema_only,` to **both** `context.configure(...)` calls — the one in `run_migrations_offline()` and the one in `run_migrations_online()`, alongside the existing `include_schemas=True`.

- [x] **Step 4: Run the test to verify it passes**

Run: `poetry run pytest backend/tests/test_alembic_env.py -q`
Expected: 4 passed.

- [x] **Step 5: Add the MLflow dependency and settings**

```bash
poetry add "mlflow@^3.15"
```

In `backend/app/config.py`, add after the Anthropic block:

```python
    # MLflow (design D4). The tracking store shares the app's Postgres in its own
    # `mlflow` schema — no second database to provision. Artifacts (models, plots)
    # stay on local disk; MLflow's own UI is never publicly hosted (D10), because
    # run browsing lives in the app's own ExperimentsPage (D9).
    mlflow_tracking_uri: str = ""
    mlflow_artifact_root: str = "./mlruns"
```

An empty `mlflow_tracking_uri` means "not configured" — Phase 2 raises a clear error rather than silently writing to a stray local `mlruns/` store.

- [x] **Step 6: Add the settings to `.env.example`**

Append:

```
# MLflow (design D4). Shares the app Postgres in the `mlflow` schema.
# Leave empty when running on SQLite — training endpoints will refuse to run.
MLFLOW_TRACKING_URI=
# MLFLOW_TRACKING_URI=postgresql://wavepoint:wavepoint@localhost:5433/wavepoint?options=-csearch_path%3Dmlflow
MLFLOW_ARTIFACT_ROOT=./mlruns
```

- [x] **Step 7: Gitignore the artifact store**

Append to `.gitignore`:

```
# MLflow local artifact store (models, plots) — regenerable, often large.
mlruns/
```

- [x] **Step 8: Initialise the MLflow schema and prove the guard works**

```bash
make db-up
docker compose exec -T postgres psql -U wavepoint -d wavepoint -c "CREATE SCHEMA IF NOT EXISTS mlflow;"

export MLFLOW_URI="postgresql://wavepoint:wavepoint@localhost:5433/wavepoint?options=-csearch_path%3Dmlflow"
poetry run mlflow db upgrade "$MLFLOW_URI"

docker compose exec -T postgres psql -U wavepoint -d wavepoint \
  -c "SELECT count(*) AS mlflow_tables FROM information_schema.tables WHERE table_schema = 'mlflow';"
```

Expected: a non-zero table count (MLflow creates ~20 tables).

Now the critical check — autogenerate must ignore all of them:

```bash
export DATABASE_URL="postgresql+psycopg2://wavepoint:wavepoint@localhost:5433/wavepoint"
poetry run alembic revision --autogenerate -m "mlflow guard check"
grep -c "drop_table" backend/alembic/versions/*mlflow_guard_check.py
```

Expected: `0`. The generated `upgrade()` body must be `pass`. Delete the file:

```bash
rm backend/alembic/versions/*mlflow_guard_check.py
```

If the count is non-zero, `include_object` is not wired into both `context.configure` calls — fix it before continuing. **Do not** run that generated migration.

- [x] **Step 9: Document the MLflow setup in the README**

Add to the `## Local services` section from Task 3:

```markdown
### MLflow tracking store

MLflow shares the same Postgres, in its own `mlflow` schema (design D4). One-time
setup after `make db-up`:

```bash
make mlflow-init
```

Then set `MLFLOW_TRACKING_URI` in `.env` (see `.env.example`). MLflow's own web UI
is never deployed — run browsing lives in the app's `ExperimentsPage` (D9/D10). To
inspect runs locally: `make mlflow-ui`.
```

And add the two targets to the `Makefile` (`.PHONY` line included):

```makefile
MLFLOW_URI ?= postgresql://wavepoint:wavepoint@localhost:5433/wavepoint?options=-csearch_path%3Dmlflow

mlflow-init:
	docker compose exec -T postgres psql -U wavepoint -d wavepoint -c "CREATE SCHEMA IF NOT EXISTS mlflow;"
	poetry run mlflow db upgrade "$(MLFLOW_URI)"

mlflow-ui:
	poetry run mlflow ui --backend-store-uri "$(MLFLOW_URI)" --default-artifact-root ./mlruns
```

- [x] **Step 10: Full check and commit**

```bash
unset DATABASE_URL
make check
git add pyproject.toml poetry.lock backend/app/config.py backend/alembic/env.py \
        backend/tests/test_alembic_env.py .env.example .gitignore README.md Makefile
git commit -m "feat: add MLflow tracking store and guard autogenerate against its schema"
```

#### Student checkpoint

**What's implemented:** MLflow is pointed at an `mlflow` schema in the same
Postgres instance (design D4). The real deliverable is the `app_schema_only`
filter added to `backend/alembic/env.py` — it stops
`alembic --autogenerate` from seeing MLflow's ~20 tables as unexpected and
proposing to drop every one of them.

**What to verify:**
- This task's own description calls this out as the most subtle piece of
  engineering in the whole phase — don't skim it. Make sure you can explain
  in your own words why `include_schemas=True` on a shared Postgres is
  dangerous without this filter.
- Run Step 8's guard check yourself and confirm
  `grep -c "drop_table" ...` prints `0`. If it doesn't, treat that as a
  "stop and understand before proceeding" moment, not a "try again" one — a
  wrong filter here could silently destroy MLflow's tracking data later in
  the workshop.
- Confirm you understand the split between "MLflow owns its schema" (never
  modeled in `app/models.py`, never queried through our ORM) and "our app
  owns its schema" (Alembic-managed) — this distinction recurs through
  Phase 2 and 3.

---

### Task 7: Ingest the computer-component dataset

Design §2 sets the domain as computer-component pricing and demand. Phase 2's training module needs a real table to fit against, and D5's `dataset_id` FK needs a real `datasets` row to point at. This loads one through the **existing** upload endpoint — no new ingest path.

Source: [`docyx/pc-part-dataset`](https://github.com/docyx/pc-part-dataset), MIT licensed, plain CSV over HTTPS with no API credentials. Chosen over the §2.1 Kaggle entries because Kaggle downloads need per-account API tokens, and over PCPartPicker/Newegg/Amazon because §2.1 explicitly rules out scraping those.

`data/csv/video-card.csv` — 6,636 rows, columns `name,price,chipset,memory,core_clock,boost_clock,color,length`. `price` is the Phase 2 regression target; the rest are features.

**Files:**
- Create: `scripts/fetch_component_data.sh`
- Modify: `Makefile`
- Modify: `.gitignore`
- Modify: `doc/project-2-ml-experiment-tracker-design.md` (§2.1 + §13 amendment)

**Interfaces:**
- Consumes: `POST /datasets` (existing, idempotent by SHA-256 content hash).
- Produces: two `app.datasets` rows named `pc-part-video-card.csv` and `pc-part-cpu.csv`. Phase 2's training endpoint takes their `dataset_id`.

- [x] **Step 1: Write the fetch script**

Create `scripts/fetch_component_data.sh`:

```bash
#!/usr/bin/env bash
# Fetch the computer-component pricing tables that Project 2 trains on
# (design §2). Source: github.com/docyx/pc-part-dataset (MIT).
#
# Static snapshots only — §2.1 rules out scraping PCPartPicker/Newegg/Amazon.
set -euo pipefail

BASE="https://raw.githubusercontent.com/docyx/pc-part-dataset/main/data/csv"
DEST="data/pc-parts"
API="${API:-http://localhost:8000}"

mkdir -p "$DEST"

for part in video-card cpu; do
  echo "downloading ${part}.csv"
  curl -fsSL "${BASE}/${part}.csv" -o "${DEST}/${part}.csv"
  rows=$(( $(wc -l < "${DEST}/${part}.csv") - 1 ))
  echo "  ${rows} rows"
done

echo
echo "uploading to ${API}/datasets"
for part in video-card cpu; do
  # The upload endpoint is idempotent on a SHA-256 of the content, so re-running
  # this script returns the existing row instead of creating a duplicate.
  curl -fsS -X POST "${API}/datasets" \
    -F "file=@${DEST}/${part}.csv;filename=pc-part-${part}.csv" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(f"  {d[\"name\"]}: id={d[\"id\"]} rows={d[\"n_rows\"]} cols={d[\"n_cols\"]}")'
done
```

```bash
chmod +x scripts/fetch_component_data.sh
```

- [x] **Step 2: Add a Make target**

Add `data-fetch` to `.PHONY` in the `Makefile` and append:

```makefile
# Download + ingest the component pricing data (design §2). Needs `make dev` running.
data-fetch:
	./scripts/fetch_component_data.sh
```

- [x] **Step 3: Keep the downloaded CSVs out of git**

Append to `.gitignore`:

```
# Downloaded component pricing snapshots — refetch with `make data-fetch`.
data/pc-parts/
```

The existing `data/census/` files stay tracked; these are refetchable from a stable URL, so committing them adds weight for nothing.

- [x] **Step 4: Run the ingest against a live server**

In one terminal:

```bash
make db-up
export DATABASE_URL="postgresql+psycopg2://wavepoint:wavepoint@localhost:5433/wavepoint"
make migrate
make dev
```

In another:

```bash
make data-fetch
```

Expected output resembling:

```
downloading video-card.csv
  6636 rows
downloading cpu.csv
  1413 rows

uploading to http://localhost:8000/datasets
  pc-part-video-card.csv: id=<uuid> rows=6636 cols=8
  pc-part-cpu.csv: id=<uuid> rows=1413 cols=8
```

- [x] **Step 5: Verify idempotency and inspect the profile**

```bash
make data-fetch                     # second run
curl -s http://localhost:8000/datasets | python3 -m json.tool
```

Expected: the same two ids as the first run (the content hash short-circuits the upload), and exactly two rows in the list — not four.

```bash
curl -s "http://localhost:8000/datasets/<video-card-id>" | python3 -m json.tool
```

Expected: `n_rows` 6636, `n_cols` 8.

- [x] **Step 6: Record the source in the design doc**

In `doc/project-2-ml-experiment-tracker-design.md` §2.1, add to the source list:

```markdown
- [docyx/pc-part-dataset](https://github.com/docyx/pc-part-dataset) (GitHub, **MIT**) —
  PCPartPicker component tables as plain CSV: `video-card.csv` (6,636 rows) and
  `cpu.csv` (1,413 rows), each with `price` plus spec columns. **This is the
  dataset Phase 1 actually ingests** (`make data-fetch`) and Phase 2 trains on;
  the entries above remain reference alternatives. No API credentials needed, and
  the MIT license makes redistribution unambiguous.
```

Add to §13 Amendments:

```markdown
- **2026-08-05:** Phase 1 selected `docyx/pc-part-dataset` (MIT) as the working
  dataset over the §2.1 Kaggle entries — Kaggle needs per-account API tokens,
  which no script or CI job can assume. Recorded in §2.1.
```

- [x] **Step 7: Full check and commit**

```bash
unset DATABASE_URL
make check
git add scripts/fetch_component_data.sh Makefile .gitignore \
        doc/project-2-ml-experiment-tracker-design.md
git commit -m "feat: add component pricing data fetch and ingest script"
```

#### Student checkpoint

**What's implemented:** A shell script
(`scripts/fetch_component_data.sh`) that downloads two CSVs (video-card and
CPU pricing data) from a public GitHub repo and uploads them through Project
1's *existing* `/datasets` endpoint — no new ingestion code was written.

**What to verify:**
- Run `make data-fetch` twice and confirm you get the *same* dataset ids
  both times — that's the content-hash idempotency guarantee working, not a
  fluke.
- Look at the actual `GET /datasets/<id>` response yourself and sanity-check
  `n_rows`/`n_cols` against the plan's numbers (6,636 rows / 8 cols for
  video cards, 1,413 rows / 8 cols for CPUs).
- Notice this task deliberately reused Project 1's upload pipeline instead
  of building a new one — worth re-reading that endpoint's code now if you
  haven't already, since Phase 2's training module will read this data back
  out the same way.

---

### Task 8: Close out Phase 1

**Files:**
- Modify: `CLAUDE.md`
- Modify: `doc/plans/2026-08-05-project-2-overall-implementation-plan.md`

- [x] **Step 1: Document the new decisions in CLAUDE.md**

Add to the decisions section (alongside the existing `**Alembic owns Postgres.**` entry):

```markdown
**MLflow owns the `mlflow` schema; Alembic must never see it (Project 2 D4).**
The tracking store shares the app's Postgres. `backend/alembic/env.py` runs with
`include_schemas=True`, so without the `app_schema_only` `include_object` filter,
`--autogenerate` proposes dropping every MLflow table. Never model MLflow tables
in `app/models.py` — read them through the `mlflow` SDK, joined on
`experiments.mlflow_run_id`.

**The embedding column is dialect-split.** `experiment_note_chunks.embedding` is
`Vector(512).with_variant(JSON(), "sqlite")` — `VECTOR(512)` on Postgres, `JSON`
on SQLite, because the whole test suite runs on SQLite. Vector *operators*
(`<=>`) are Postgres-only, so Phase 3's similarity search cannot be tested on
SQLite; test its SQL against Postgres and unit-test the merge logic separately.

**Postgres runs on port 5433, not 5432** (`docker compose`), to avoid colliding
with a system Postgres. `make db-up` / `make db-down` / `make db-psql`.
```

- [x] **Step 2: Mark Phase 1 complete in the program plan**

In `doc/plans/2026-08-05-project-2-overall-implementation-plan.md` §9 Amendments, append:

```markdown
- **2026-08-05** (or the actual completion date): Phase 1 complete. Detailed plan:
  `doc/plans/2026-08-05-project-2-phase-1-foundations.md`. Two decisions the plan
  forced and resolved: the embedding column width is pinned at 512 with the
  provider still open (the table is empty, so it is cheap to change), and
  `docyx/pc-part-dataset` (MIT) was selected over the §2.1 Kaggle sources.
```

- [x] **Step 3: Verify every Phase 1 exit criterion**

```bash
make check                                          # backend green
cd frontend && npm run type-check && npm test -- --run && npm run build && cd ..
make db-up
export DATABASE_URL="postgresql+psycopg2://wavepoint:wavepoint@localhost:5433/wavepoint"
poetry run alembic upgrade head && poetry run alembic downgrade -1 && poetry run alembic upgrade head
docker compose exec -T postgres psql -U wavepoint -d wavepoint \
  -c "SELECT extversion FROM pg_extension WHERE extname='vector';" \
  -c "SELECT count(*) FROM app.experiments;" \
  -c "SELECT name, n_rows FROM app.datasets;"
curl -s -o /dev/null -w "jaeger:%{http_code}\n" http://localhost:16686
unset DATABASE_URL
```

Expected: everything green; a pgvector version; `experiments` present and empty; two `pc-part-*` dataset rows; `jaeger:200`.

- [x] **Step 4: Commit and open the PR**

```bash
git add CLAUDE.md doc/plans/2026-08-05-project-2-overall-implementation-plan.md
git commit -m "docs: record Phase 1 decisions and mark the phase complete"
git push
gh pr create --title "Phase 1: Project 2 foundations and domain data" --body "$(cat <<'EOF'
Implements Phase 1 of `doc/plans/2026-08-05-project-2-overall-implementation-plan.md`.

- CI on every push/PR (backend `make check`, frontend type-check/test/build)
- Docs reframed as Project 2; stale "Project 2 adds auth" claims removed (D2)
- `docker compose`: Postgres 16 + pgvector on :5433, Jaeger on :16686
- `experiments` + `experiment_note_chunks` models and migration
- MLflow tracking store on the shared Postgres, with an `include_object` guard so
  `--autogenerate` can never propose dropping MLflow's tables
- Component pricing data (`docyx/pc-part-dataset`, MIT) ingested via the existing
  idempotent upload endpoint

No training, embedding, or agent code — that is Phases 2 and 3.
EOF
)"
```

Expected: CI green on the PR.

#### Student checkpoint

**What's implemented:** Records this phase's two most subtle decisions (the
MLflow schema guard, the dialect-split embedding column) into `CLAUDE.md` for
future reference, marks Phase 1 complete in the overall program plan, and
opens the PR.

**What to verify:**
- Before approving/merging the PR, walk through the **Phase 1 exit criteria**
  below yourself, end to end — don't just trust that each task's own
  "Expected" output was correct in isolation.
- Make sure you can explain, without looking anything up, why
  `pc-part-dataset` was chosen over the §2.1 Kaggle sources (Task 7), and why
  the 512-dimension embedding column isn't a firm commitment yet (Task 4).
  If you can't, that's a signal to re-read those two tasks before this phase
  closes out.

---

## Phase 1 exit criteria

- CI runs and passes on every push and PR to `main`.
- `make db-up` yields a Postgres with pgvector installable and a reachable Jaeger UI.
- `make migrate` applies cleanly and `alembic downgrade -1` reverses cleanly on Postgres.
- `alembic revision --autogenerate` produces an empty migration — no model/migration drift, and no proposed drops of MLflow's tables.
- `app.experiments` and `app.experiment_note_chunks` exist with the design §7 columns.
- Two real component-pricing datasets are queryable via `GET /datasets`.
- No stale "Project 2 adds auth" claim remains in any doc.

## What Phase 2 picks up

`app/training.py` fits against the `pc-part-video-card.csv` dataset row from Task 7, logs to the MLflow store from Task 6, and writes `Experiment` rows from Task 4. The `Experiment.notes` it writes are what Phase 3 embeds into the (still empty) `experiment_note_chunks` table.
