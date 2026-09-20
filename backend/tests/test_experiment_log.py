import mlflow
import pandas as pd
import pytest
from app import experiment_log
from app.training import MODEL_REGISTRY, TrainResult, fit_and_score


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A real MLflow tracking store, per test.

    Must be sqlite:// — MLflow 3.15 refuses a file:// backend outright.
    """
    uri = f"sqlite:///{tmp_path}/mlflow.db"
    monkeypatch.setattr(experiment_log.settings, "mlflow_tracking_uri", uri)
    monkeypatch.setattr(experiment_log.settings, "mlflow_artifact_root", str(tmp_path / "art"))
    return uri


def frame():
    return pd.DataFrame({"memory": [4, 8, 12, 16, 20, 24] * 5, "price": [1.0, 2, 3, 4, 5, 6] * 5})


def test_a_hyperparam_cannot_overwrite_the_run_provenance(store):
    # Spread last, an incoming `split` would replace the one log_run wrote and
    # the run would then claim a chronological split it never ran.
    result = fit_and_score("ridge", {"alpha": 0.5}, frame(), "price", ["memory"])
    with pytest.raises(ValueError, match="reserved param names"):
        experiment_log.log_run(
            "adhoc",
            "ridge",
            "regression",
            {"alpha": 0.5, "split": "whatever"},
            result,
            "ds-1",
            "hash-abc",
            "price",
            ["memory"],
        )
    assert mlflow.active_run() is None  # rejected before a run was ever opened


def test_log_run_records_params_metrics_and_target(store):
    result = fit_and_score("ridge", {"alpha": 0.5}, frame(), "price", ["memory"])
    run_id = experiment_log.log_run(
        "adhoc",
        "ridge",
        "regression",
        {"alpha": 0.5},
        result,
        "ds-1",
        "hash-abc",
        "price",
        ["memory"],
    )
    fetched = experiment_log.fetch_runs([run_id])[run_id]
    assert fetched.status == "FINISHED"
    assert fetched.params["model_type"] == "ridge"
    assert fetched.params["task_type"] == "regression"
    assert fetched.params["target_column"] == "price"
    assert fetched.params["feature_columns"] == "memory"
    assert fetched.metrics["rmse"] >= 0


def test_a_random_split_is_recorded_as_such(store):
    result = fit_and_score("ridge", {}, frame(), "price", ["memory"])
    run_id = experiment_log.log_run(
        "adhoc", "ridge", "regression", {}, result, None, None, "price", ["memory"]
    )
    assert experiment_log.fetch_runs([run_id])[run_id].params["split"] == "random"


def test_a_chronological_split_is_recorded_with_its_time_column(store):
    result = fit_and_score("ridge", {}, frame(), "price", ["memory"])
    run_id = experiment_log.log_run(
        "adhoc",
        "ridge",
        "regression",
        {},
        result,
        None,
        None,
        "price",
        ["memory"],
        time_column="as_of",
    )
    params = experiment_log.fetch_runs([run_id])[run_id].params
    assert params["split"] == "chronological"
    assert params["time_column"] == "as_of"


def test_failed_result_is_logged_as_a_failed_run(store):
    failed = TrainResult("FAILED", {}, {"alpha": 1}, "ValueError: boom", None)
    run_id = experiment_log.log_run(
        "adhoc", "ridge", "regression", {"alpha": 1}, failed, None, None, "price", ["memory"]
    )
    fetched = experiment_log.fetch_runs([run_id])[run_id]
    assert fetched.status == "FAILED"
    assert fetched.metrics == {}


def test_fetch_runs_is_one_call_for_many_ids(store):
    ids = [
        experiment_log.log_run(
            "adhoc",
            "ridge",
            "regression",
            {"alpha": a},
            fit_and_score("ridge", {"alpha": a}, frame(), "price", ["memory"]),
            None,
            None,
            "price",
            ["memory"],
        )
        for a in (0.1, 0.2, 0.3)
    ]
    fetched = experiment_log.fetch_runs(ids)
    assert set(fetched) == set(ids)


def test_fetch_runs_of_nothing_makes_no_call(store):
    assert experiment_log.fetch_runs([]) == {}


def test_search_runs_filters_by_status(store):
    ok = experiment_log.log_run(
        "adhoc",
        "ridge",
        "regression",
        {},
        fit_and_score("ridge", {}, frame(), "price", ["memory"]),
        None,
        None,
        "price",
        ["memory"],
    )
    experiment_log.log_run(
        "adhoc",
        "ridge",
        "regression",
        {},
        TrainResult("FAILED", {}, {}, "boom", None),
        None,
        None,
        "price",
        ["memory"],
    )
    assert experiment_log.search_runs(None, None, ["FINISHED"]) == [ok]


def test_log_run_works_inside_an_active_parent_run(store):
    # Task 7's Optuna study opens a parent run and logs one child run per
    # trial. Without nested=True mlflow raises "Run with UUID ... is already
    # active" and the whole study dies on its first trial.
    import mlflow

    mlflow.set_tracking_uri(store)
    with mlflow.start_run() as parent:
        run_id = experiment_log.log_run(
            "adhoc",
            "ridge",
            "regression",
            {},
            fit_and_score("ridge", {}, frame(), "price", ["memory"]),
            None,
            None,
            "price",
            ["memory"],
        )
    assert run_id != parent.info.run_id
    assert experiment_log.fetch_runs([run_id])[run_id].status == "FINISHED"


def test_n_features_survives_mlflow_truncating_the_feature_list(store):
    # mlflow silently TRUNCATES a param value at 6000 chars rather than
    # raising, so a wide dataset's `feature_columns` no longer describes what
    # was trained. n_features is the cheap cross-check that makes that
    # detectable instead of silent.
    features = [f"col_{i:04d}" for i in range(700)]
    run_id = experiment_log.log_run(
        "adhoc",
        "ridge",
        "regression",
        {},
        TrainResult("FINISHED", {"rmse": 1.0}, {}, None, None),
        None,
        None,
        "price",
        features,
    )
    params = experiment_log.fetch_runs([run_id])[run_id].params
    assert params["n_features"] == "700"
    assert len(params["feature_columns"].split(",")) < 700  # truncated by mlflow


def test_empty_tracking_uri_fails_fast(monkeypatch):
    monkeypatch.setattr(experiment_log.settings, "mlflow_tracking_uri", "")
    with pytest.raises(RuntimeError, match="MLFLOW_TRACKING_URI"):
        experiment_log.fetch_runs(["anything"])


@pytest.mark.parametrize("model_type", sorted(MODEL_REGISTRY))
def test_every_registry_model_logs(store, model_type):
    """Every MODEL_REGISTRY entry must survive skops serialisation.

    log_run passes an explicit skops_trusted_types list. A registry entry built
    on a non-sklearn estimator (the D25 persistence baseline is the first) is
    untrusted unless it is named there, and the failure is a 500 at log time
    that only reproduces against a real tracking store. Parametrising over the
    registry means adding a model to it also tests it here.
    """
    spec = MODEL_REGISTRY[model_type]
    if spec.task_type == "classification":
        df = pd.DataFrame({"memory": [4, 8, 12, 16, 20, 24] * 5, "tier": ["lo", "hi"] * 15})
        target, params = "tier", {}
    else:
        df = frame()
        target = "price"
        params = {"prior_column": "memory"} if model_type == "persistence" else {}

    result = fit_and_score(model_type, params, df, target, ["memory"])
    assert result.status == "FINISHED", result.error

    run_id = experiment_log.log_run(
        "adhoc",
        model_type,
        spec.task_type,
        params,
        result,
        "ds-1",
        "hash-abc",
        target,
        ["memory"],
    )
    assert experiment_log.fetch_runs([run_id])[run_id].status == "FINISHED"

    # D24 reads this back; logging it is only half the contract.
    mlflow.set_tracking_uri(store)
    assert mlflow.sklearn.load_model(f"runs:/{run_id}/model") is not None
