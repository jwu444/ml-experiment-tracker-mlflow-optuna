from __future__ import annotations

import datetime as dt
import logging

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from mlflow.tracking import MlflowClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import experiment_log, training, tuning
from app.config import settings
from app.db import get_session
from app.leaderboard import ExperimentNotFound, build_leaderboard
from app.models import Dataset, DatasetColumn, Experiment, Run
from app.routes.shared import load_training_frame
from app.schemas import (
    ExperimentCreateRequest,
    ExperimentOut,
    ExperimentPatchRequest,
    LeaderboardOut,
    RunOut,
    TrainRequest,
    TrialOut,
    TuneOut,
    TuneRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/experiments", tags=["experiments"])


def _resolve_features(
    request_features: list[str] | None,
    df: pd.DataFrame,
    target: str,
    time_column: str | None,
) -> list[str]:
    """Explicit features win; otherwise infer them from the DataFrame.

    Inference reads the frame, not `dataset.profile_json` — the profile carries
    no per-column cardinality and empties its categorical summary when it
    degrades (Task 4).
    """
    if request_features is not None:
        return _validate_features(request_features, df, target, time_column)
    try:
        return training.infer_feature_columns(
            df, target, settings.feature_max_cardinality, time_column
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _validate_features(
    requested: list[str], df: pd.DataFrame, target: str, time_column: str | None
) -> list[str]:
    """422 the same caller mistakes the inference path already 422s.

    `training.prepare()` catches all of these, but it runs inside
    `fit_and_score`, which turns every exception into `status="FAILED"`. So
    without this, `feature_columns: ["price"]` against `target_column: "price"`
    does not get rejected — it trains, fails, and is persisted as a failed
    experiment row plus a failed MLflow run. A caller typo is not history worth
    keeping, and the 404/422 checks around it already establish that malformed
    requests are rejected before anything is written.
    """
    # The time column is the split axis, never a feature. Dropped rather than
    # rejected: naming it is a reasonable thing for a caller to do.
    features = [f for f in requested if f != time_column]
    unknown = [f for f in features if f not in df.columns]
    if unknown:
        raise HTTPException(
            status_code=422, detail=f"feature columns not in the dataset: {sorted(set(unknown))}"
        )
    if target in features:
        raise HTTPException(
            status_code=422, detail=f"target column {target!r} cannot also be a feature"
        )
    duplicates = sorted({f for f in features if features.count(f) > 1})
    if duplicates:
        raise HTTPException(status_code=422, detail=f"duplicate feature columns: {duplicates}")
    if not features:
        raise HTTPException(
            status_code=422,
            detail="feature_columns is empty; omit it entirely to infer features",
        )
    return features


def _validate_columns(df: pd.DataFrame, target: str, time_column: str | None) -> None:
    if target not in df.columns:
        raise HTTPException(
            status_code=422, detail=f"target column {target!r} is not in the dataset"
        )
    if time_column is not None and time_column not in df.columns:
        raise HTTPException(
            status_code=422, detail=f"time column {time_column!r} is not in the dataset"
        )


def _require_model(model_type: str) -> training.ModelSpec:
    if model_type not in training.MODEL_REGISTRY:
        raise HTTPException(status_code=422, detail=f"unknown model_type {model_type!r}")
    return training.MODEL_REGISTRY[model_type]


def _require_metric_agreement(
    model_type: str, spec: training.ModelSpec, experiment: Experiment
) -> None:
    """A leaderboard is coherent only if every run on it was ranked on the same
    metric. task_type on the experiment already forces agreement in practice, so
    this rejects a genuine mismatch — but it is checked rather than assumed,
    because the failure renders as a perfectly normal-looking table (§3.1)."""
    if spec.objective_metric != experiment.primary_metric:
        raise HTTPException(
            status_code=422,
            detail=(
                f"model {model_type!r} is ranked on "
                f"{spec.objective_metric!r}, but this experiment ranks on "
                f"{experiment.primary_metric!r}"
            ),
        )


def _name_taken(session: Session, name: str, exclude_id: str | None) -> bool:
    """Whether another experiment already answers to this name (D35)."""
    stmt = select(Experiment.id).where(Experiment.name == name)
    if exclude_id is not None:
        stmt = stmt.where(Experiment.id != exclude_id)
    return session.execute(stmt).first() is not None


def _record_mlflow_experiment(experiment: Experiment) -> None:
    """Pin down which MLflow experiment this investigation's runs land in (D35).

    Set once, on the first run logged, rather than at creation: `POST
    /experiments` is a database write and must not start failing because the
    tracking store is unreachable. Until then the two sides are joined only by
    name, which a rename of either would quietly break.
    """
    if experiment.mlflow_experiment_id is None:
        experiment.mlflow_experiment_id = experiment_log.resolve_experiment_id(experiment.name)


def _require_experiment_dataset(experiment: Experiment) -> str:
    if experiment.dataset_id is None:
        raise HTTPException(
            status_code=409, detail="this experiment has no dataset_id; runs cannot be trained"
        )
    return experiment.dataset_id


def _attach_cv_metrics(
    result: training.TrainResult,
    model_type: str,
    df: pd.DataFrame,
    target: str,
    features: list[str],
    time_column: str | None,
) -> None:
    """Add `cv_<objective_metric>` and `cv_std` to a finished run's metrics (3.0).

    /tune has always logged the spread; /train logging only the holdout is why
    the persistence baseline — trained and never tuned (D25) — is the one run on
    every leaderboard with no noise band, and it is the reference every other run
    is compared against. The holdout is ~30 rows at this data size, so a point
    estimate cannot separate two models.

    A cross-validation failure is not a training failure: the fit already
    succeeded and is worth logging, so the bands are simply absent rather than
    the run being lost. `cv_std` stays optional everywhere downstream for the
    same reason runs logged before this task have none.

    Cost, stated rather than hidden: this refits the pipeline once per fold, so
    POST /train now does K+1 fits synchronously inside the request instead of 1.
    At this data size (~224 rows) that is milliseconds; on a larger panel it is
    the first thing to move off the request path.
    """
    if result.status != "FINISHED":
        return
    try:
        mean, std = training.cv_objective(
            model_type, result.params, df, target, features, time_column
        )
    except Exception:  # noqa: BLE001 — a missing band must never lose a good fit
        # Logged, not swallowed silently: `cv_std` is optional everywhere
        # downstream, so an absent band is indistinguishable from a run logged
        # before this existed. Without this line there is nothing to look at.
        logger.warning("cross-validation band unavailable for %s", model_type, exc_info=True)
        return
    result.metrics[f"cv_{training.MODEL_REGISTRY[model_type].objective_metric}"] = mean
    result.metrics["cv_std"] = std


@router.post("/{experiment_id}/train", response_model=RunOut)
def train_run(
    experiment_id: str, request: TrainRequest, session: Session = Depends(get_session)
) -> RunOut:
    experiment = _require_experiment(session, experiment_id)
    spec = _require_model(request.model_type)
    _require_metric_agreement(request.model_type, spec, experiment)
    dataset_id = _require_experiment_dataset(experiment)
    df, dataset = load_training_frame(session, dataset_id)
    _validate_columns(df, experiment.target_column, request.time_column)
    features = _resolve_features(
        request.feature_columns, df, experiment.target_column, request.time_column
    )

    result = training.fit_and_score(
        request.model_type,
        request.hyperparams,
        df,
        experiment.target_column,
        features,
        request.time_column,
    )
    # Before log_run: the tracking store is written from result.metrics.
    _attach_cv_metrics(
        result,
        request.model_type,
        df,
        experiment.target_column,
        features,
        request.time_column,
    )
    run_id = experiment_log.log_run(
        experiment.name,  # D35: the parent's name, never "adhoc"
        request.model_type,
        experiment.task_type,
        result.params,
        result,
        dataset.id,
        dataset.content_hash,  # D13/D5: pins the run to the exact bytes it trained on
        experiment.target_column,
        features,
        request.time_column,
        experiment.mlflow_experiment_id,
    )
    _record_mlflow_experiment(experiment)
    # §8: a failed fit is history, not an error — the row is written either way.
    run = Run(
        mlflow_run_id=run_id,
        experiment_id=experiment.id,
        model_type=request.model_type,
        notes=request.notes,
        notes_status="draft",  # D20: unreviewed until a human says otherwise
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return RunOut(
        run_id=run.id,
        mlflow_run_id=run_id,
        status=result.status,
        task_type=experiment.task_type,
        metrics=result.metrics,
    )


@router.post("/{experiment_id}/tune", response_model=TuneOut)
def tune_run(
    experiment_id: str, request: TuneRequest, session: Session = Depends(get_session)
) -> TuneOut:
    experiment = _require_experiment(session, experiment_id)
    spec = _require_model(request.model_type)
    _require_metric_agreement(request.model_type, spec, experiment)
    if not 1 <= request.n_trials <= settings.optuna_max_trials:
        raise HTTPException(
            status_code=422,
            detail=f"n_trials must be between 1 and {settings.optuna_max_trials}",
        )
    if not spec.search_space:
        raise HTTPException(
            status_code=422,
            detail=f"{request.model_type!r} has an empty search space; there is nothing to tune",
        )
    dataset_id = _require_experiment_dataset(experiment)
    df, dataset = load_training_frame(session, dataset_id)
    _validate_columns(df, experiment.target_column, request.time_column)
    features = _resolve_features(
        request.feature_columns, df, experiment.target_column, request.time_column
    )

    stamp = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    study_name = f"tune-{request.model_type}-{stamp}"
    trials_out: list[TrialOut] = []

    def persist(record: tuning.TrialRecord) -> None:
        # Refit at the trial's params so the logged run carries holdout metrics,
        # not just the CV score Optuna optimised. Both are recorded, distinctly.
        result = training.fit_and_score(
            request.model_type,
            record.params,
            df,
            experiment.target_column,
            features,
            request.time_column,
        )
        # `cv_<metric>` is the score Optuna ranked on; `cv_std` is its spread
        # across folds. On a ~180-row train split the spread routinely exceeds
        # the gap between trials, so shipping the mean alone invites a
        # leaderboard that is mostly noise (Global Constraints).
        if record.value is not None:
            result.metrics[f"cv_{spec.objective_metric}"] = record.value
        if record.std is not None:
            result.metrics["cv_std"] = record.std
        run_id = experiment_log.log_run(
            experiment.name,  # D35: the parent's name — the study is a tag, not
            request.model_type,  # a grouping level, per below.
            experiment.task_type,
            record.params,
            result,
            dataset.id,
            dataset.content_hash,
            experiment.target_column,
            features,
            request.time_column,
            experiment.mlflow_experiment_id,
        )
        # D35: an Optuna study is one hyperparameter search WITHIN an
        # investigation, not an investigation. It is a tag, not an MLflow
        # experiment — log_run has already closed this run, so the tag is set
        # via the client rather than the (active-run-only) fluent API.
        MlflowClient().set_tag(run_id, "optuna_study", study_name)
        _record_mlflow_experiment(experiment)
        run = Run(
            mlflow_run_id=run_id,
            experiment_id=experiment.id,
            model_type=request.model_type,
            notes=request.notes,
            notes_status="draft",  # D20, same as Flow A
        )
        session.add(run)
        session.flush()
        trials_out.append(
            TrialOut(
                number=record.number,
                run_id=run.id,
                mlflow_run_id=run_id,
                params=record.params,
                value=record.value,
                std=record.std,
                status=record.status,
            )
        )

    study = tuning.run_study(
        request.model_type,
        df,
        experiment.target_column,
        features,
        request.n_trials,
        request.time_column,
        persist,
    )
    session.commit()

    # Pick with the study's own direction. `min` here regardless would report
    # the worst classifier as best — the exact bug a per-entry direction exists
    # to prevent.
    scored = [t for t in trials_out if t.value is not None]
    pick = max if study.direction == "maximize" else min
    best = pick(scored, key=lambda t: t.value or 0.0) if scored else None

    best_metrics: dict[str, float] = {}
    if study.best_value is not None:
        best_metrics[f"cv_{spec.objective_metric}"] = study.best_value
    if best is not None and best.std is not None:
        best_metrics["cv_std"] = best.std

    return TuneOut(
        n_trials=len(trials_out),
        task_type=experiment.task_type,
        objective_metric=spec.objective_metric,
        direction=study.direction,
        best_run_id=best.run_id if best else None,
        best_metrics=best_metrics,
        trials=trials_out,
    )


_METRIC_DEFAULTS = {"regression": ("rmse", "minimize"), "classification": ("f1_macro", "maximize")}


def _require_dataset_column(session: Session, dataset_id: str, column: str) -> None:
    """422 unless `column` is a profiled column of `dataset_id`.

    A dataset with no profiled columns is not evidence against the target, so the
    check is skipped there rather than rejecting every value.
    """
    names = {
        c
        for (c,) in session.execute(
            select(DatasetColumn.name).where(DatasetColumn.dataset_id == dataset_id)
        ).all()
    }
    if names and column not in names:
        raise HTTPException(
            status_code=422,
            detail=f"target_column {column!r} is not a column of this dataset",
        )


@router.post("", status_code=201, response_model=ExperimentOut)
def create_experiment(
    request: ExperimentCreateRequest, session: Session = Depends(get_session)
) -> ExperimentOut:
    dataset = None
    if request.dataset_id is not None:
        dataset = session.get(Dataset, request.dataset_id)
        if dataset is None:
            raise HTTPException(status_code=404, detail="Dataset not found")
        # A typo here produces an experiment that 422s on every train call, and
        # PATCH only accepts a target while the stored one is EMPTY (see
        # update_experiment), so a wrong-but-present value is not repairable
        # through the API. Catch it while it is still cheap.
        _require_dataset_column(session, dataset.id, request.target_column)
    # MLflow resolves an experiment BY NAME (D35), so two investigations sharing
    # one would file their runs into the same MLflow experiment while looking
    # separate here — and the leaderboards would silently disagree with the
    # tracking store. There is no DB constraint behind this: `name` is editable
    # and the check has to hold for PATCH too, so it lives in one place.
    if _name_taken(session, request.name, exclude_id=None):
        raise HTTPException(status_code=409, detail=f"An experiment named {request.name!r} exists")
    metric, direction = _METRIC_DEFAULTS[request.task_type]
    row = Experiment(
        name=request.name,
        objective=request.objective,
        dataset_id=request.dataset_id,
        # Pinned from the dataset, never from the request. This is the hash
        # `log_run` tags each run with (D5/D13); accepting a client-supplied
        # value lets the recorded provenance disagree with what was scored.
        dataset_version=dataset.content_hash if dataset is not None else None,
        target_column=request.target_column,
        task_type=request.task_type,
        primary_metric=metric,
        metric_direction=direction,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _experiment_out(session, row)


@router.get("", response_model=list[ExperimentOut])
def list_experiments(
    dataset_id: str | None = None,
    task_type: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> list[ExperimentOut]:
    query = select(Experiment).order_by(Experiment.created_at.desc())
    if dataset_id:
        query = query.where(Experiment.dataset_id == dataset_id)
    if task_type:
        query = query.where(Experiment.task_type == task_type)
    rows = list(session.execute(query.limit(limit).offset(offset)).scalars())
    return [_experiment_out(session, row) for row in rows]


@router.get("/{experiment_id}", response_model=ExperimentOut)
def get_experiment(experiment_id: str, session: Session = Depends(get_session)) -> ExperimentOut:
    row = _require_experiment(session, experiment_id)
    return _experiment_out(session, row)


@router.patch("/{experiment_id}", response_model=ExperimentOut)
def update_experiment(
    experiment_id: str,
    request: ExperimentPatchRequest,
    session: Session = Depends(get_session),
) -> ExperimentOut:
    row = _require_experiment(session, experiment_id)
    if request.name is not None:
        if _name_taken(session, request.name, exclude_id=row.id):
            raise HTTPException(
                status_code=409, detail=f"An experiment named {request.name!r} exists"
            )
        row.name = request.name
    if request.objective is not None:
        row.objective = request.objective
    if request.target_column is not None:
        # A target may be FILLED but never CHANGED. Runs inside an investigation
        # are comparable because they all answer one question (D34); re-pointing
        # the target once runs exist would leave the leaderboard ranking two
        # different questions against each other, with every row still looking
        # valid. Empty is the single repairable state, and it arises only where
        # the backfill migration had no MLflow schema to read a target from.
        if row.target_column:
            raise HTTPException(
                status_code=409,
                detail="target_column is already set; every run in an experiment is "
                "scored against the same target",
            )
        if not request.target_column.strip():
            raise HTTPException(status_code=422, detail="target_column cannot be empty")
        if row.dataset_id is not None:
            _require_dataset_column(session, row.dataset_id, request.target_column)
        row.target_column = request.target_column
    session.commit()
    session.refresh(row)
    return _experiment_out(session, row)


@router.get("/{experiment_id}/runs", response_model=LeaderboardOut)
def leaderboard(experiment_id: str, session: Session = Depends(get_session)) -> LeaderboardOut:
    """The leaderboard: runs ranked WITHIN one investigation (D38).

    Ranking the whole table would compare a revenue rmse against a GPU-price
    rmse — two numbers on unrelated scales. An experiment is what defines the
    comparable set. The ranking logic itself lives in `app.leaderboard`, so
    Task 10's agent tool can call it without going through HTTP.
    """
    try:
        return build_leaderboard(session, experiment_id)
    except ExperimentNotFound:
        raise HTTPException(status_code=404, detail="Experiment not found") from None


def _require_experiment(session: Session, experiment_id: str) -> Experiment:
    row = session.get(Experiment, experiment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return row


def _experiment_out(session: Session, row: Experiment) -> ExperimentOut:
    n = session.execute(
        select(func.count()).select_from(Run).where(Run.experiment_id == row.id)
    ).scalar_one()
    # Name, not the whole Dataset: this runs once per row in the list response,
    # and `datasets.data_csv` holds the entire uploaded file (D5).
    dataset_name = None
    if row.dataset_id:
        dataset_name = session.execute(
            select(Dataset.name).where(Dataset.id == row.dataset_id)
        ).scalar_one_or_none()
    return ExperimentOut(
        id=row.id,
        name=row.name,
        objective=row.objective,
        dataset_id=row.dataset_id,
        dataset_name=dataset_name,
        dataset_version=row.dataset_version,
        target_column=row.target_column,
        task_type=row.task_type,
        primary_metric=row.primary_metric,
        metric_direction=row.metric_direction,
        n_runs=n,
        created_at=row.created_at,
    )
