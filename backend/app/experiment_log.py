from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import mlflow
import mlflow.sklearn
from mlflow.entities import Run

from app.config import settings
from app.training import TrainResult


@dataclass(frozen=True)
class RunData:
    run_id: str
    status: str
    params: dict[str, str]  # MLflow stores every param as a string
    metrics: dict[str, float]


def _require_uri() -> str:
    """MLflow 3.x refuses a filesystem backend, so an unset URI is not a
    silent fallback to ./mlruns — it is a confusing library-internal error.
    Turn it into a clear one."""
    if not settings.mlflow_tracking_uri:
        raise RuntimeError(
            "MLFLOW_TRACKING_URI is not set. Run `make db-up && make mlflow-init`, "
            "then set mlflow_tracking_uri in .env."
        )
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    return settings.mlflow_tracking_uri


def _experiment_id(name: str) -> str:
    existing = mlflow.get_experiment_by_name(name)
    if existing is not None:
        return str(existing.experiment_id)
    return str(mlflow.create_experiment(name, artifact_location=settings.mlflow_artifact_root))


def resolve_experiment_id(name: str) -> str:
    """The MLflow experiment id `log_run` files a run of this name into.

    D35 pairs one `app.experiments` row with one MLflow experiment, but the two
    are joined only by name until someone records the id — which is what
    `app.experiments.mlflow_experiment_id` is for. The train and tune routes
    call this once per experiment, when that column is still null, so the join
    survives a later rename of either side.
    """
    _require_uri()
    return _experiment_id(name)


# Param names log_run writes itself to describe HOW a run was set up. Caller
# hyperparams are spread into the same flat namespace, so a search space that
# happened to name a knob `split` would overwrite the provenance rather than sit
# beside it — and the run would then claim a split it never used. MLflow has no
# namespacing to lean on here, so the collision is caught instead.
RESERVED_PARAMS = frozenset(
    {
        "model_type",
        "task_type",
        "target_column",
        "feature_columns",
        "n_features",
        "time_column",
        "split",
    }
)


# Ceiling on a single search_runs fetch. mlflow's own default is 100k, which for
# an unfiltered call means materialising the whole store into memory in one go.
SEARCH_MAX_RESULTS = 1000


def _to_run_data(run: Run) -> RunData:
    return RunData(
        run_id=str(run.info.run_id),
        status=str(run.info.status),
        params={str(k): str(v) for k, v in run.data.params.items()},
        metrics={str(k): float(v) for k, v in run.data.metrics.items()},
    )


def log_run(
    experiment_name: str,
    model_type: str,
    task_type: str,
    params: dict[str, Any],
    result: TrainResult,
    dataset_id: str | None,
    dataset_version: str | None,
    target: str,
    features: list[str],
    time_column: str | None = None,
    experiment_id: str | None = None,
) -> str:
    """Write one run. Returns its mlflow_run_id.

    target/features are logged as params, not tags: without them "which model
    performed best" would compare runs trained against different targets.
    `task_type` joins them for the same reason — an rmse and an f1_macro are not
    on a common scale, so a leaderboard that mixes them is meaningless.
    `time_column` records HOW the run was split; a run logged without it was
    split randomly, and that distinction must survive into the history.
    """
    _require_uri()
    collisions = sorted(RESERVED_PARAMS & set(params))
    if collisions:
        raise ValueError(
            f"hyperparams may not use the reserved param names {collisions}; "
            "they describe how the run was set up, not what was tuned"
        )
    # nested=True when a run is already open. Task 7's Optuna study opens a
    # parent run and logs one child per trial; without this mlflow raises
    # "Run with UUID ... is already active" and the study dies on trial one.
    # Prefer the id the caller recorded on its first run over re-resolving the
    # name (D35). Names are mutable and not unique: renaming an investigation, or
    # two of them sharing a name, silently forks or merges MLflow experiments,
    # and neither shows up as an error — the runs just land somewhere else.
    run = mlflow.start_run(
        experiment_id=experiment_id or _experiment_id(experiment_name),
        nested=mlflow.active_run() is not None,
    )
    status = "FAILED"
    try:
        mlflow.log_params(
            {
                "model_type": model_type,
                "task_type": task_type,
                "target_column": target,
                "feature_columns": ",".join(features),
                # mlflow truncates a param value at 6000 chars (it warns, but
                # still stores the short version), so on a wide dataset
                # feature_columns silently stops describing what was trained.
                # The count is the cheap cross-check that keeps that detectable.
                "n_features": str(len(features)),
                "time_column": time_column or "",
                "split": "chronological" if time_column else "random",
                **{k: str(v) for k, v in params.items()},
            }
        )
        mlflow.set_tags({"dataset_id": dataset_id or "", "dataset_version": dataset_version or ""})
        if result.status == "FINISHED":
            mlflow.log_metrics(result.metrics)
            if result.model is not None:
                # mlflow 3.15 serialises with skops, which refuses to save any
                # type not on a trust list — safer than pickle, which executes
                # arbitrary code on load. Every pipeline we build carries
                # numpy.dtype (the ColumnTransformer records its column dtypes),
                # and the persistence baseline (D25) adds our own estimator
                # class. Declaring both keeps the skops guarantee rather than
                # falling back to cloudpickle.
                #
                # A MODEL_REGISTRY entry whose estimator is not a stock sklearn
                # class MUST be added here, or its runs 500 at log time — and
                # only against a real tracking store, so the unit tests stay
                # green. test_experiment_log.py::test_every_registry_model_logs
                # is what actually catches it.
                mlflow.sklearn.log_model(
                    result.model,
                    name="model",
                    skops_trusted_types=["numpy.dtype", "app.training.PriorValueRegressor"],
                )
            status = "FINISHED"
        else:
            mlflow.set_tag("error", result.error or "")
    finally:
        mlflow.end_run(status=status)
    return str(run.info.run_id)


def fetch_runs(run_ids: list[str]) -> dict[str, RunData]:
    """Params and metrics for many runs in ONE search call.

    Verified against mlflow 3.15.1: `attributes.run_id IN (...)` is supported.
    A per-id get_run loop here would be an N+1 across a process boundary.
    """
    if not run_ids:
        return {}
    _require_uri()
    quoted = ",".join(f"'{r}'" for r in run_ids)
    runs = mlflow.search_runs(
        search_all_experiments=True,
        filter_string=f"attributes.run_id IN ({quoted})",
        output_format="list",
    )
    return {str(r.info.run_id): _to_run_data(r) for r in runs}


def search_runs(
    metric_filters: list[str] | None,
    param_filters: list[str] | None,
    statuses: list[str] | None,
    max_results: int = SEARCH_MAX_RESULTS,
) -> list[str]:
    """Run ids matching MLflow-side filters. This is D15's structured stage —
    Phase 3's agent calls it too, rather than reaching for the SDK itself.

    Called with no filters this asks for every run in the store, so the result is
    bounded. The bound truncates *before* the status filter below, so a store
    larger than `max_results` can return fewer status matches than exist — the
    honest trade against an unbounded fetch, and the reason the cap is an
    argument rather than a constant.
    """
    _require_uri()
    clauses = [*(metric_filters or []), *(param_filters or [])]
    runs = mlflow.search_runs(
        search_all_experiments=True,
        filter_string=" and ".join(clauses) if clauses else "",
        output_format="list",
        max_results=max_results,
    )
    # Status is filtered here, not in the filter string. mlflow 3.15 rejects
    # `attributes.status IN (...)` — run_id is the ONLY attribute that accepts a
    # list — and its filter grammar has no OR, so a multi-status query cannot be
    # expressed server-side at all. Status already rides along on every run
    # returned, so this costs no extra call. Metric and param filters still go
    # MLflow-side, which is the part that actually bounds the result set.
    if statuses:
        wanted = set(statuses)
        runs = [r for r in runs if str(r.info.status) in wanted]
    return [str(r.info.run_id) for r in runs]
