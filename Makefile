.PHONY: install lint format format-check type-check test check dev eval migrate migration db-up db-down db-psql mlflow-init mlflow-ui data-fetch prepare-data seed-history embed

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

migrate:
	poetry run alembic upgrade head

# Autogenerate a migration from model changes: make migration m="add foo column"
migration:
	poetry run alembic revision --autogenerate -m "$(m)"

eval:
	poetry run python -m eval.runner $(ARGS)

# Local dev services (docker-compose.yml). SQLite remains the zero-setup default
# and the test backend; Postgres is only needed for pgvector and MLflow work.
db-up:
	docker compose up -d
	@echo "Postgres  -> postgresql+psycopg2://wavepoint:wavepoint@localhost:5433/wavepoint"
	@echo "Jaeger UI -> http://localhost:16686"

db-down:
	docker compose down

db-psql:
	docker compose exec postgres psql -U wavepoint -d wavepoint

# MLflow tracking store (design D4). Shares the Postgres above in its own
# `mlflow` schema; MLflow creates and migrates those tables itself.
MLFLOW_URI ?= postgresql://wavepoint:wavepoint@localhost:5433/wavepoint?options=-csearch_path%3Dmlflow

mlflow-init:
	docker compose exec -T postgres psql -U wavepoint -d wavepoint -c "CREATE SCHEMA IF NOT EXISTS mlflow;"
	poetry run mlflow db upgrade "$(MLFLOW_URI)"

mlflow-ui:
	poetry run mlflow ui --backend-store-uri "$(MLFLOW_URI)" --default-artifact-root ./mlruns

# Ingest the committed CSVs into `datasets` (D13/D18). Needs `make dev` running.
data-fetch:
	./scripts/fetch_component_data.sh

prepare-data:  ## regenerate data-sources/prepared/ from the committed snapshots
	poetry run python scripts/prepare_dataset.py revenue_nowcast

# Seed real experiment history (2.10). Needs `make dev` running against Postgres
# with MLflow initialised, the datasets uploaded, and ANTHROPIC_API_KEY set — the
# notes are written by Claude. Every note lands as a draft awaiting review (D20).
seed-history:
	poetry run python scripts/seed_experiment_history.py

# Reconcile the retrieval index against approved notes and findings (3.3).
# Needs VOYAGE_API_KEY and a DATABASE_URL pointing at the Postgres from db-up.
# Not a route by design (D17): an approval must not fail because Voyage is down.
embed:
	poetry run python scripts/backfill_embeddings.py
