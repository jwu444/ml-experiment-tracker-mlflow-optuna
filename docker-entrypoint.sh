#!/bin/sh
# Free-tier Render services do not support a pre-deploy command, so the MLflow
# store is prepared here instead, before uvicorn binds the port.
#
# The prepare script prints the tracking URI carrying MLflow's search_path, and
# that value replaces MLFLOW_TRACKING_URI for the exec'd server — otherwise the
# app would read the bare `fromDatabase` string and resolve to `public` while
# the store it just prepared lives in `mlflow`.
set -eu

PREPARED_URI="$(python scripts/prepare_mlflow_store.py)"
if [ -n "${PREPARED_URI}" ]; then
  MLFLOW_TRACKING_URI="${PREPARED_URI}"
  export MLFLOW_TRACKING_URI
fi

exec uvicorn app.main:create_app --factory --app-dir backend --host 0.0.0.0 --port 8000
