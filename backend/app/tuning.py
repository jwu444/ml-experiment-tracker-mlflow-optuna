from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import optuna
import pandas as pd

from app import training
from app.config import settings

logger = logging.getLogger(__name__)

# Optuna's own logging is chatty at INFO and says nothing our trial records don't.
optuna.logging.set_verbosity(optuna.logging.WARNING)


@dataclass(frozen=True)
class TrialRecord:
    number: int
    params: dict[str, Any]
    value: float | None  # the objective's mean across CV folds
    std: float | None  # its standard deviation across those folds
    status: str  # "FINISHED" | "FAILED"
    error: str | None = None


@dataclass
class StudyResult:
    best_params: dict[str, Any]
    best_value: float | None
    direction: str  # copied from the registry entry, for the caller to record
    trials: list[TrialRecord] = field(default_factory=list)


def _spec(model_type: str) -> training.ModelSpec:
    if model_type not in training.MODEL_REGISTRY:
        raise ValueError(f"unknown model_type {model_type!r}")
    return training.MODEL_REGISTRY[model_type]


def _search_space(model_type: str) -> training.SearchSpace:
    return _spec(model_type).search_space


def suggest_params(trial: optuna.Trial, model_type: str) -> dict[str, Any]:
    """Draw one point from the registry's search space, so /train and /tune
    always agree on what a hyperparameter means.

    Lives here, not in training.py: this is the one function that needs an
    optuna.Trial, and keeping it out of training.py is what lets that module
    stay importable and testable without optuna.
    """
    params: dict[str, Any] = {}
    for name, (kind, low, high, log) in _search_space(model_type).items():
        if kind == "int":
            params[name] = trial.suggest_int(name, int(low), int(high), log=log)
        else:
            params[name] = trial.suggest_float(name, low, high, log=log)
    return params


def run_study(
    model_type: str,
    df: pd.DataFrame,
    target: str,
    features: list[str],
    n_trials: int,
    time_column: str | None = None,
    on_trial: Callable[[TrialRecord], None] | None = None,
) -> StudyResult:
    """Run a bounded, in-memory Optuna study.

    No `storage=`: MLflow is the durable record of every trial, so there is no
    third schema. The study object lives only for this call.

    `on_trial` lets the caller persist each trial without this module importing
    MLflow or the DB — that separation is what keeps it unit-testable.

    The direction is the registry entry's, not a constant. `cv_objective`
    already normalises sklearn's `neg_*` sign, so the value optimised here is
    the metric as a human reads it: rmse minimised, f1_macro maximised.
    """
    spec = _spec(model_type)  # fail fast on an unknown model_type
    records: list[TrialRecord] = []

    def objective(trial: optuna.Trial) -> float:
        params = suggest_params(trial, model_type)
        try:
            value, std = training.cv_objective(
                model_type, params, df, target, features, time_column
            )
        except Exception as exc:  # noqa: BLE001 — a bad draw is data, not a crash
            record = TrialRecord(
                trial.number, params, None, None, "FAILED", f"{type(exc).__name__}: {exc}"
            )
            records.append(record)
            if on_trial is not None:
                on_trial(record)
            raise optuna.TrialPruned() from exc
        record = TrialRecord(trial.number, params, float(value), float(std), "FINISHED")
        records.append(record)
        if on_trial is not None:
            on_trial(record)
        return float(value)

    study = optuna.create_study(direction=spec.direction)
    # No `catch=`. A bad hyperparameter draw is already handled above — it becomes
    # `TrialPruned`, which Optuna honours regardless of `catch`. The only thing
    # `catch=(Exception,)` added was swallowing failures of `on_trial`, i.e. the
    # caller's persistence. That is not a survivable error: `records` has already
    # been appended to, so the study's own best trial would keep a run the caller
    # never stored, and the route's response could then name one trial in
    # `best_experiment_id` and another in `best_metrics`. Let it propagate and
    # surface as a 500, matching how a `log_run` failure behaves in /train.
    study.optimize(
        objective,
        n_trials=n_trials,
        timeout=settings.optuna_study_timeout_s,
    )

    finished = [r for r in records if r.status == "FINISHED" and r.value is not None]
    if not finished:
        return StudyResult({}, None, spec.direction, records)
    pick = max if spec.direction == "maximize" else min
    best = pick(finished, key=lambda r: r.value if r.value is not None else float("nan"))
    return StudyResult(dict(best.params), best.value, spec.direction, records)
