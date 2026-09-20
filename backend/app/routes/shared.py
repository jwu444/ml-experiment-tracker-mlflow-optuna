"""Route-layer helpers shared by routes/experiments.py and routes/runs.py.

`load_training_frame` backs training and tuning (routes/experiments.py) and
diagnostics (routes/runs.py); `merge_runs` backs the run-level GET/PATCH
routes (routes/runs.py) and the experiment-scoped leaderboard
(routes/experiments.py). Both used to live in one of the two routers with the
other importing it by its private name, which meant a fix to diagnostics (D37)
needed a function-scoped import to dodge the resulting
experiments.py <-> runs.py cycle. Housing both here, imported by each router
at module scope, removes the cycle instead of routing around it.
"""

from __future__ import annotations

import logging

import pandas as pd
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import experiment_log
from app.dataset_io import load_csv
from app.models import Dataset, Run
from app.schemas import RunDetailOut

logger = logging.getLogger(__name__)


def load_training_frame(session: Session, dataset_id: str) -> tuple[pd.DataFrame, Dataset]:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    # load_csv is the canonical parser (CLAUDE.md) — training must see exactly
    # the dtypes the profiler saw at upload.
    return load_csv(dataset.data_csv), dataset


def merge_runs(rows: list[Run]) -> list[RunDetailOut]:
    """Join our columns to MLflow's params/metrics in ONE fetch.

    A GET must not 500 because the tracking store is down: the structured
    fields are ours and always available, so degrade rather than fail.

    `dataset_id`/`dataset_version`/`task_type` moved to `Experiment` (D34) and
    were dropped from `Run` once every row had a (now NOT NULL) `experiment_id`
    to inherit them from (D37 contraction) — each row reads them off its own
    `run.experiment` relationship, which is always populated. Reading per-row
    rather than taking one shared `Experiment` parameter is what lets this same
    helper serve both `GET /runs`, which spans experiments, and the
    experiment-scoped leaderboard, where every run shares one.
    """
    runs: dict[str, experiment_log.RunData] = {}
    available = True
    try:
        runs = experiment_log.fetch_runs([r.mlflow_run_id for r in rows])
    except Exception:  # noqa: BLE001
        logger.warning("MLflow tracking store unavailable; returning structured fields only")
        available = False
    out = []
    for row in rows:
        run = runs.get(row.mlflow_run_id)
        exp = row.experiment
        out.append(
            RunDetailOut(
                id=row.id,
                mlflow_run_id=row.mlflow_run_id,
                experiment_id=row.experiment_id,
                dataset_id=exp.dataset_id,
                dataset_version=exp.dataset_version,
                model_type=row.model_type,
                task_type=exp.task_type,
                notes=row.notes,
                notes_status=row.notes_status,
                created_at=row.created_at,
                status=run.status if run else None,
                params=run.params if run else {},
                metrics=run.metrics if run else {},
                mlflow_available=available,
            )
        )
    return out
