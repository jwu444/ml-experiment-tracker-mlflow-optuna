from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import diagnostics, experiment_log, findings
from app.db import get_session
from app.loop import run_loop
from app.models import Experiment, Run
from app.profiler import profile_dataframe
from app.routes.shared import load_training_frame, merge_runs
from app.schemas import FindingCreatedOut, RunDetailOut, RunPatchRequest

router = APIRouter(prefix="/runs", tags=["runs"])

DIAGNOSTICS_QUESTION = (
    "These two frames describe one trained model. `residuals` holds the model's holdout "
    "predictions with actual, predicted, residual and abs_error, plus the identifying "
    "columns. If `residuals` has a `time_index` column, that is the numeric time axis — "
    "a 0-based row ordinal over the holdout sorted by time — and it is what you must plot "
    "residuals against to judge drift, because the raw time column is stored as text and "
    "the chart tools take a numeric x. Note it is a row position, not a time value: when "
    "several entities share one period the rows within that period take consecutive "
    "indices, so read the trend across the series and do not treat short-range zigzag as "
    "drift, and describe movement in terms of the real time column. `learning_curve` "
    "holds train and validation score "
    "at increasing training "
    "sizes. Interpret the model's behaviour: where the errors concentrate, whether they "
    "drift over time, which groups are predicted worst, and whether the learning curve "
    "indicates underfitting, overfitting, or that more data would help. Be quantitative "
    "and say plainly if the model looks unusable."
)


@router.get("", response_model=list[RunDetailOut])
def list_runs(
    model_type: str | None = None,
    task_type: str | None = None,
    dataset_id: str | None = None,
    experiment_id: str | None = None,
    notes_status: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> list[RunDetailOut]:
    query = select(Run).order_by(Run.created_at.desc())
    if model_type:
        query = query.where(Run.model_type == model_type)
    if task_type or dataset_id:
        # task_type and dataset_id now live on the parent Experiment (D34) —
        # every run has one (experiment_id is NOT NULL), so an inner join
        # neither drops nor duplicates a row.
        query = query.join(Experiment, Run.experiment_id == Experiment.id)
        if task_type:
            query = query.where(Experiment.task_type == task_type)
        if dataset_id:
            query = query.where(Experiment.dataset_id == dataset_id)
    if experiment_id:
        query = query.where(Run.experiment_id == experiment_id)
    if notes_status:
        query = query.where(Run.notes_status == notes_status)
    if status:
        # `status` has no column of ours — it lives in MLflow. Resolve it to a
        # run-id set first (D15's structured stage), then intersect. This is the
        # one filter that cannot be answered without the tracking store.
        try:
            run_ids = experiment_log.search_runs(None, None, [status])
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=503, detail="MLflow tracking store unavailable"
            ) from exc
        if not run_ids:
            return []
        query = query.where(Run.mlflow_run_id.in_(run_ids))
    rows = list(session.execute(query.limit(limit).offset(offset)).scalars())
    return merge_runs(rows)


@router.get("/{run_id}", response_model=RunDetailOut)
def get_run(run_id: str, session: Session = Depends(get_session)) -> RunDetailOut:
    row = session.get(Run, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return merge_runs([row])[0]


@router.patch("/{run_id}", response_model=RunDetailOut)
def update_run(
    run_id: str,
    request: RunPatchRequest,
    session: Session = Depends(get_session),
) -> RunDetailOut:
    """Edit a note, move its review status, or both (D20).

    Writing a note is NOT approving it: the seeding script in Task 10 goes
    through this route, and an implicit approval on write would mean every
    generated note arrives pre-blessed. `notes_status` only moves when the
    caller names it.
    """
    row = session.get(Run, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if request.notes is not None:
        row.notes = request.notes
    if request.notes_status is not None:
        if request.notes_status == "approved" and not row.notes.strip():
            raise HTTPException(status_code=422, detail="an empty note cannot be approved")
        row.notes_status = request.notes_status
    session.commit()
    session.refresh(row)
    return merge_runs([row])[0]


def load_logged_model(model_uri: str) -> Any:
    """Seam for the MLflow model loader, so tests can stub it (D24).

    Loading the LOGGED model is the point: refitting from logged params yields a
    close-but-different model reported as the one that was scored, and nothing
    about that failure looks wrong.
    """
    import mlflow.sklearn

    return mlflow.sklearn.load_model(model_uri)


@router.post("/{run_id}/diagnostics", status_code=201, response_model=FindingCreatedOut)
def run_diagnostics(run_id: str, session: Session = Depends(get_session)) -> FindingCreatedOut:
    """Generate a reviewable diagnostic interpretation for one run (2b.2)."""
    row = session.get(Run, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    experiment = row.experiment
    if experiment.task_type != "regression":
        raise HTTPException(
            status_code=409,
            detail="diagnostics are regression-only; residuals are undefined for a "
            f"{experiment.task_type} run",
        )
    if experiment.dataset_id is None:
        raise HTTPException(
            status_code=409, detail="this run has no dataset_id; its rows cannot be reloaded"
        )

    try:
        runs = experiment_log.fetch_runs([row.mlflow_run_id])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="MLflow tracking store unavailable") from exc
    run = runs.get(row.mlflow_run_id)
    if run is None:
        raise HTTPException(
            status_code=409, detail=f"run {row.mlflow_run_id} is not in the tracking store"
        )
    if run.status != "FINISHED":
        raise HTTPException(
            status_code=409,
            detail=f"run {row.mlflow_run_id} is {run.status}; there is no logged model to load",
        )

    model_uri = f"runs:/{row.mlflow_run_id}/model"
    try:
        model = load_logged_model(model_uri)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=409,
            detail=f"no loadable model for run {row.mlflow_run_id} at {model_uri}: {exc}",
        ) from exc

    # D34: the target is a column now, not an MLflow param behind a ""-fallback.
    target = experiment.target_column
    # `features` and `time_column` still come from MLflow params — they are
    # per-run, not per-experiment.
    features = [f for f in run.params.get("feature_columns", "").split(",") if f]
    time_column = run.params.get("time_column") or None
    frame, _ = load_training_frame(session, experiment.dataset_id)

    try:
        residuals = diagnostics.residual_frame(
            model, frame, target, features, time_column, id_columns=("ticker",)
        )
        curve = diagnostics.learning_curve_frame(model, frame, target, features, time_column)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=f"cannot diagnose this run: {exc}") from exc

    # Ephemeral ids: these frames go to the loop in memory and are NEVER
    # inserted into `datasets` — D13 makes that table the single source-data
    # path, and a derived diagnostic frame is not source data.
    derived = {f"residuals-{row.id}": residuals, f"learning_curve-{row.id}": curve}
    names = {f"residuals-{row.id}": "residuals", f"learning_curve-{row.id}": "learning_curve"}
    # Unwrapped, as on /chats and /datasets/{id}/eda (§6). create_finding is
    # below the loop, so a failure writes no partial finding.
    result = run_loop(
        [
            {"id": key, "name": names[key], "profile": profile_dataframe(df)}
            for key, df in derived.items()
        ],
        derived,
        [],
        DIAGNOSTICS_QUESTION,
    )

    finding = findings.create_finding(session, "diagnostic", row.id, result.interpretation)
    session.commit()
    session.refresh(finding)
    return FindingCreatedOut(
        finding_id=finding.id,
        source_type=finding.source_type,
        source_id=finding.source_id,
        status=finding.status,
        text=finding.text,
    )
