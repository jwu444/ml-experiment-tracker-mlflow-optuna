# The API service only. The SPA is a separate Render static site (§7.1).
FROM python:3.12-slim

# POETRY_VERSION must track the Poetry that generated poetry.lock, not an
# arbitrary pin: this repo's lock is lock-version = "2.1" (Poetry 2.4.1), and
# Poetry 1.8.3 cannot read that lock file at all.
ENV PYTHONUNBUFFERED=1 \
    POETRY_VERSION=2.4.1 \
    POETRY_VIRTUALENVS_CREATE=false

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir "poetry==${POETRY_VERSION}"

WORKDIR /app

# Dependencies first, so a source-only change does not reinstall them.
COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root --no-interaction

COPY backend/ ./backend/
COPY prompts/ ./prompts/
COPY scripts/ ./scripts/
COPY alembic.ini docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

# No secrets and no training-artifact directory copied in. Keys arrive as
# Render environment variables, and artifacts live in R2 (Task 13) — 126 MB of
# models in an image would be baked in at build time and stale by the first
# run logged after it.
EXPOSE 8000
# The entrypoint prepares the MLflow store, then execs the same uvicorn command
# this CMD used to run directly. See docker-entrypoint.sh.
CMD ["./docker-entrypoint.sh"]
