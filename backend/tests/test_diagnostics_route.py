import app.routes.runs as runs_route
import numpy as np
import pandas as pd
import pytest
from app import experiment_log, training
from app.dataset_io import load_csv
from app.loop import LoopResult
from app.models import Experiment, Run

_CSV = pd.DataFrame(
    {
        "quarter_end": pd.date_range("2015-03-31", periods=40, freq="QE").astype(str),
        "ticker": ["AAPL", "MSFT"] * 20,
        "revenue": np.arange(40, dtype=float) * 100.0,
        "revenue_next": np.arange(40, dtype=float) * 100.0 + 50.0,
    }
).to_csv(index=False)


def _upload(client) -> str:
    return client.post("/datasets", files={"file": ("panel.csv", _CSV, "text/csv")}).json()["id"]


def _run(db_session, dataset_id, status="FINISHED", task_type="regression") -> str:
    # NOTE: brief used `app.main.app.dependency_overrides[get_session]`, but the
    # `client` fixture builds its own `create_app()` instance per test (see
    # conftest.py) — the module-level `app.main.app` singleton is a different
    # object with its own (unoverridden) dependency graph, so that would not
    # share a database with `client`. Using the `db_session` fixture instead,
    # which binds to the same `db_engine` the `client` fixture uses.
    #
    # dataset_id/task_type moved to the parent Experiment (D34) and were
    # dropped from Run entirely once experiment_id became NOT NULL (D37) — a
    # Run can no longer carry them directly, so this helper creates its parent
    # experiment first.
    experiment = Experiment(
        name="exp",
        dataset_id=dataset_id,
        target_column="revenue_next",
        task_type=task_type,
    )
    db_session.add(experiment)
    db_session.commit()
    row = Run(
        mlflow_run_id="run-1",
        experiment_id=experiment.id,
        model_type="ridge",
    )
    db_session.add(row)
    db_session.commit()
    return row.id


def _fake_mlflow(monkeypatch, status="FINISHED", model=None, load_raises=None) -> None:
    """Stub the MLflow boundary: the run's metadata and its logged model."""
    run = experiment_log.RunData(
        run_id="run-1",
        status=status,
        params={
            # Deliberately WRONG and different from experiment.target_column:
            # since D34 the route sources the target from the Experiment, not
            # from this logged param. If it ever regresses to the old per-run
            # fallback, training.prepare gets a column the frame does not have
            # and these tests fail instead of silently passing.
            "target_column": "stale_param_not_the_target",
            "feature_columns": "revenue,ticker",
            "time_column": "quarter_end",
        },
        metrics={"rmse": 42.0},
    )
    monkeypatch.setattr(runs_route.experiment_log, "fetch_runs", lambda ids: {"run-1": run})

    def fake_load(uri):
        if load_raises is not None:
            raise load_raises
        return model

    monkeypatch.setattr(runs_route, "load_logged_model", fake_load)


def _fitted_model():
    frame = load_csv(_CSV)
    x, y = training.prepare(frame, "revenue_next", ["revenue", "ticker"], "quarter_end")
    pipeline = training.build_pipeline("ridge", {}, ["revenue"], ["ticker"])
    x_train, _, y_train, _ = training.split_frame(x, y, chronological=True)
    pipeline.fit(x_train, y_train)
    return pipeline


def _fake_loop(monkeypatch, text="Residuals grow in the last four quarters.") -> None:
    def fake_run_loop(datasets, dfs, prior_messages, question, *, client=None):
        # Both derived frames must reach the loop, and neither may be a dataset row.
        assert len(datasets) == 2
        assert {d["name"] for d in datasets} == {"residuals", "learning_curve"}
        return LoopResult(interpretation=text, pass_count=2, judge_score=90)

    monkeypatch.setattr(runs_route, "run_loop", fake_run_loop)


def test_diagnostics_creates_a_draft_finding(client, db_session, monkeypatch) -> None:
    dataset_id = _upload(client)
    run_id = _run(db_session, dataset_id)
    _fake_mlflow(monkeypatch, model=_fitted_model())
    _fake_loop(monkeypatch)

    resp = client.post(f"/runs/{run_id}/diagnostics")
    assert resp.status_code == 201
    body = resp.json()
    assert body["source_type"] == "diagnostic"
    assert body["source_id"] == run_id
    assert body["status"] == "draft"


def test_diagnostics_on_an_unknown_run_is_404(client, monkeypatch) -> None:
    resp = client.post("/runs/no-such-id/diagnostics")
    assert resp.status_code == 404


def test_diagnostics_on_a_failed_run_is_409(client, db_session, monkeypatch) -> None:
    """There is no logged model to load."""
    dataset_id = _upload(client)
    run_id = _run(db_session, dataset_id)
    _fake_mlflow(monkeypatch, status="FAILED", model=None)
    resp = client.post(f"/runs/{run_id}/diagnostics")
    assert resp.status_code == 409
    assert "FAILED" in resp.json()["detail"]


def test_diagnostics_with_a_missing_artifact_is_409_naming_the_run(
    client, db_session, monkeypatch
) -> None:
    dataset_id = _upload(client)
    run_id = _run(db_session, dataset_id)
    _fake_mlflow(monkeypatch, model=None, load_raises=OSError("no such artifact"))
    resp = client.post(f"/runs/{run_id}/diagnostics")
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "run-1" in detail and "model" in detail


def test_diagnostics_on_a_classification_run_is_409(client, db_session, monkeypatch) -> None:
    """Residuals are regression-only; 2b scopes to the panel."""
    dataset_id = _upload(client)
    run_id = _run(db_session, dataset_id, task_type="classification")
    _fake_mlflow(monkeypatch, model=_fitted_model())
    resp = client.post(f"/runs/{run_id}/diagnostics")
    assert resp.status_code == 409
    assert "regression" in resp.json()["detail"].lower()


def test_diagnostics_when_mlflow_is_unreachable_is_503(client, db_session, monkeypatch) -> None:
    dataset_id = _upload(client)
    run_id = _run(db_session, dataset_id)

    def boom(ids):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(runs_route.experiment_log, "fetch_runs", boom)
    resp = client.post(f"/runs/{run_id}/diagnostics")
    assert resp.status_code == 503


def test_diagnostics_writes_no_finding_when_the_loop_fails(client, db_session, monkeypatch) -> None:
    dataset_id = _upload(client)
    run_id = _run(db_session, dataset_id)
    _fake_mlflow(monkeypatch, model=_fitted_model())

    def boom(datasets, dfs, prior_messages, question, *, client=None):
        raise RuntimeError("anthropic exploded")

    monkeypatch.setattr(runs_route, "run_loop", boom)
    with pytest.raises(RuntimeError):
        client.post(f"/runs/{run_id}/diagnostics")
    assert client.get("/findings").json() == []


def test_diagnostics_does_not_insert_the_derived_frames_as_datasets(
    client, db_session, monkeypatch
) -> None:
    """D13: `datasets` is the single SOURCE-data path. A residual frame is not
    source data and must never appear there."""
    dataset_id = _upload(client)
    run_id = _run(db_session, dataset_id)
    _fake_mlflow(monkeypatch, model=_fitted_model())
    _fake_loop(monkeypatch)
    client.post(f"/runs/{run_id}/diagnostics")
    assert len(client.get("/datasets").json()) == 1
