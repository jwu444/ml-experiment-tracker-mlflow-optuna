import pytest
from app import experiment_log
from app.models import Experiment, Run
from mlflow.tracking import MlflowClient

# Every test here logs to MLflow, so the store fixture applies module-wide.
pytestmark = pytest.mark.usefixtures("mlflow_store")


def _create_experiment(client, dataset_id, target_column, task_type="regression"):
    resp = client.post(
        "/experiments",
        json={
            "name": "exp",
            "target_column": target_column,
            "dataset_id": dataset_id,
            "task_type": task_type,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_train_returns_ids_and_metrics(client, dataset_id):
    exp_id = _create_experiment(client, dataset_id, "price")
    resp = client.post(f"/experiments/{exp_id}/train", json={"model_type": "ridge"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "FINISHED"
    assert body["mlflow_run_id"]
    assert body["task_type"] == "regression"
    assert body["metrics"]["rmse"] >= 0


def test_a_classifier_returns_classification_metrics(client, dataset_id):
    # `chipset` is the 3-class label; `memory` and `price` are the features.
    exp_id = _create_experiment(client, dataset_id, "chipset", task_type="classification")
    resp = client.post(f"/experiments/{exp_id}/train", json={"model_type": "logistic_regression"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["task_type"] == "classification"
    assert "f1_macro" in body["metrics"]
    assert "rmse" not in body["metrics"]


def test_a_time_column_records_a_chronological_split(client, panel_id, db_session):
    exp_id = _create_experiment(client, panel_id, "price")
    resp = client.post(
        f"/experiments/{exp_id}/train",
        json={"model_type": "ridge", "time_column": "as_of"},
    )
    assert resp.status_code == 200
    run_id = resp.json()["mlflow_run_id"]
    params = experiment_log.fetch_runs([run_id])[run_id].params
    assert params["split"] == "chronological"
    assert params["time_column"] == "as_of"
    # The split axis must never also be a feature.
    assert "as_of" not in params["feature_columns"].split(",")


def test_omitting_the_time_column_falls_back_to_a_random_split(client, panel_id):
    exp_id = _create_experiment(client, panel_id, "price")
    resp = client.post(f"/experiments/{exp_id}/train", json={"model_type": "ridge"})
    run_id = resp.json()["mlflow_run_id"]
    assert experiment_log.fetch_runs([run_id])[run_id].params["split"] == "random"


def test_an_unknown_time_column_is_422_not_a_silent_random_split(client, panel_id):
    # The dangerous failure mode is a typo'd time_column quietly producing a
    # leaky random split that still returns 200 with flattering metrics.
    exp_id = _create_experiment(client, panel_id, "price")
    resp = client.post(
        f"/experiments/{exp_id}/train",
        json={"model_type": "ridge", "time_column": "as_off"},
    )
    assert resp.status_code == 422


def test_train_persists_a_run_row_with_the_dataset_hash(client, dataset_id, db_session):
    exp_id = _create_experiment(client, dataset_id, "price")
    resp = client.post(
        f"/experiments/{exp_id}/train",
        json={"model_type": "ridge", "notes": "baseline"},
    )
    row = db_session.get(Run, resp.json()["run_id"])
    assert row is not None
    assert row.experiment_id == exp_id
    assert row.model_type == "ridge"
    assert row.notes == "baseline"
    # dataset_id/dataset_version moved to the parent Experiment (D34) and were
    # dropped from Run entirely (D37) — the per-run content-hash pin (D13/D5)
    # now lives only in MLflow, as the `dataset_version` tag `log_run` sets.
    tags = MlflowClient().get_run(row.mlflow_run_id).data.tags
    assert len(tags.get("dataset_version", "")) == 64  # the dataset's SHA-256 content hash


def test_a_new_run_starts_as_an_unreviewed_draft(client, dataset_id, db_session):
    # D20: nothing the machine writes may present itself as reviewed. Even a note
    # typed by hand at train time is a draft — the route is not a review.
    exp_id = _create_experiment(client, dataset_id, "price")
    resp = client.post(
        f"/experiments/{exp_id}/train",
        json={"model_type": "ridge", "notes": "typed by a human, still unreviewed"},
    )
    row = db_session.get(Run, resp.json()["run_id"])
    assert row is not None
    assert row.notes_status == "draft"


def test_the_first_run_records_which_mlflow_experiment_it_landed_in(client, dataset_id, db_session):
    """D35 pairs one app experiment with one MLflow experiment, but the column
    that records the pairing went unwritten for a whole phase — leaving the two
    joined only by name, which a rename of either side would quietly break."""
    exp_id = _create_experiment(client, dataset_id, "price")
    row = db_session.get(Experiment, exp_id)
    assert row is not None
    assert row.mlflow_experiment_id is None, "creation must not need a reachable store"

    resp = client.post(f"/experiments/{exp_id}/train", json={"model_type": "ridge"})
    db_session.expire_all()
    row = db_session.get(Experiment, exp_id)
    assert row is not None and row.mlflow_experiment_id is not None
    # It must be the experiment the run actually went into, not just any id.
    assert MlflowClient().get_run(resp.json()["mlflow_run_id"]).info.experiment_id == (
        row.mlflow_experiment_id
    )


def test_a_renamed_experiment_keeps_filing_runs_into_the_same_mlflow_experiment(
    client, dataset_id, db_session
):
    """The recorded id has to be USED, not merely stored. Resolving by name on
    every run means a rename forks the history in two, and nothing errors — the
    later runs simply stop appearing beside the earlier ones."""
    exp_id = _create_experiment(client, dataset_id, "price")
    first = client.post(f"/experiments/{exp_id}/train", json={"model_type": "ridge"})
    db_session.expire_all()
    recorded = db_session.get(Experiment, exp_id)
    assert recorded is not None and recorded.mlflow_experiment_id is not None

    assert client.patch(f"/experiments/{exp_id}", json={"name": "renamed"}).status_code == 200
    second = client.post(f"/experiments/{exp_id}/train", json={"model_type": "ridge"})

    client_ = MlflowClient()
    ids = {client_.get_run(r.json()["mlflow_run_id"]).info.experiment_id for r in (first, second)}
    assert ids == {recorded.mlflow_experiment_id}


def test_a_failed_fit_is_200_and_still_recorded(client, dataset_id, db_session):
    exp_id = _create_experiment(client, dataset_id, "price")
    resp = client.post(
        f"/experiments/{exp_id}/train",
        json={"model_type": "random_forest", "hyperparams": {"n_estimators": -1}},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "FAILED"
    assert db_session.get(Run, resp.json()["run_id"]) is not None


def test_unknown_model_type_is_422(client, dataset_id):
    exp_id = _create_experiment(client, dataset_id, "price")
    resp = client.post(f"/experiments/{exp_id}/train", json={"model_type": "nope"})
    assert resp.status_code == 422


def test_train_inside_an_unknown_experiment_is_404(client):
    resp = client.post("/experiments/nope/train", json={"model_type": "ridge"})
    assert resp.status_code == 404


def test_training_in_an_experiment_with_no_dataset_is_409(client):
    # dataset_id is no longer part of the train request (D34) — it is fixed at
    # experiment-creation time, so a missing dataset can only be discovered on
    # an experiment that was created without one. This replaces the old
    # test_missing_dataset_is_404: that test posted a bogus dataset_id directly
    # in the train body, a shape that no longer exists post-contraction.
    resp = client.post(
        "/experiments",
        json={"name": "no-dataset", "target_column": "price"},
    )
    assert resp.status_code == 201
    exp_id = resp.json()["id"]
    resp = client.post(f"/experiments/{exp_id}/train", json={"model_type": "ridge"})
    assert resp.status_code == 409


def test_train_rejects_a_model_whose_metric_disagrees_with_the_experiment(client, dataset_id):
    # The experiment ranks on rmse (regression); logistic_regression is ranked
    # on f1_macro. A mixed-metric leaderboard renders as a normal table, so
    # this is checked rather than assumed (§3.1).
    exp_id = _create_experiment(client, dataset_id, "price")
    resp = client.post(f"/experiments/{exp_id}/train", json={"model_type": "logistic_regression"})
    assert resp.status_code == 422


def test_a_trained_run_belongs_to_its_experiment(client, dataset_id, db_session):
    exp_id = _create_experiment(client, dataset_id, "price")
    resp = client.post(f"/experiments/{exp_id}/train", json={"model_type": "ridge"})
    row = db_session.get(Run, resp.json()["run_id"])
    assert row is not None
    assert row.experiment_id == exp_id


def test_target_not_a_column_is_422_at_creation_not_at_train(client, dataset_id):
    # The target is fixed on the experiment, so it is checked there. Letting the
    # 201 through and failing at train would leave an experiment that can never
    # run and that no PATCH can repair.
    resp = client.post(
        "/experiments",
        json={"name": "exp", "target_column": "nope", "dataset_id": dataset_id},
    )
    assert resp.status_code == 422


def train_with_features(client, dataset_id, features):
    exp_id = _create_experiment(client, dataset_id, "price")
    return client.post(
        f"/experiments/{exp_id}/train",
        json={"model_type": "ridge", "feature_columns": features},
    )


# Every case below reaches training.prepare()'s own guards if the route lets it
# through — but fit_and_score turns those into status="FAILED", so the mistake
# would be answered with a 200 and persisted as a failed run instead of rejected.
def test_an_unknown_feature_column_is_422(client, dataset_id):
    assert train_with_features(client, dataset_id, ["memory", "nope"]).status_code == 422


def test_the_target_as_an_explicit_feature_is_422(client, dataset_id):
    assert train_with_features(client, dataset_id, ["memory", "price"]).status_code == 422


def test_duplicate_explicit_features_are_422(client, dataset_id):
    assert train_with_features(client, dataset_id, ["memory", "memory"]).status_code == 422


def test_an_empty_feature_list_is_422_not_a_silent_inference(client, dataset_id):
    # Omitting feature_columns means "infer"; sending [] is a caller bug, and
    # inferring anyway would train a model on columns nobody asked for.
    assert train_with_features(client, dataset_id, []).status_code == 422


def test_a_rejected_feature_list_writes_no_run_row(client, dataset_id, db_session):
    train_with_features(client, dataset_id, ["memory", "price"])
    assert db_session.query(Run).count() == 0


def test_naming_the_time_column_as_a_feature_drops_it_rather_than_failing(client, panel_id):
    exp_id = _create_experiment(client, panel_id, "price")
    resp = client.post(
        f"/experiments/{exp_id}/train",
        json={
            "model_type": "ridge",
            "feature_columns": ["as_of", "memory"],
            "time_column": "as_of",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "FINISHED"


def test_train_logs_the_cross_validation_band(client, panel_id):
    """3.0/D32: a trained run reports cv_<metric> and cv_std, as a tuned one does.

    Without this the persistence baseline — trained and never tuned (D25) — is
    the only run on the leaderboard with no noise band, and it is the reference
    every other run is compared against.
    """
    exp_id = _create_experiment(client, panel_id, "price")
    resp = client.post(
        f"/experiments/{exp_id}/train",
        json={"model_type": "ridge", "hyperparams": {"alpha": 1.0}, "time_column": "as_of"},
    )
    assert resp.status_code == 200
    metrics = resp.json()["metrics"]
    assert "rmse" in metrics
    assert "cv_rmse" in metrics
    assert "cv_std" in metrics
    assert metrics["cv_std"] >= 0.0


def test_train_logs_the_band_for_the_persistence_baseline(client, panel_id):
    """The baseline is the run that most needs a band, and the one that had none."""
    exp_id = _create_experiment(client, panel_id, "price")
    resp = client.post(
        f"/experiments/{exp_id}/train",
        json={
            "model_type": "persistence",
            "hyperparams": {"prior_column": "memory"},
            "time_column": "as_of",
        },
    )
    assert resp.status_code == 200
    metrics = resp.json()["metrics"]
    assert "cv_rmse" in metrics
    assert "cv_std" in metrics


def test_a_failed_fit_gets_no_band_and_is_still_recorded(client, panel_id, db_session):
    """A cross-validation failure must not turn a recorded FAILED run into a 500,
    and must not invent a band for a run that never fit (§8: failures are data)."""
    exp_id = _create_experiment(client, panel_id, "price")
    resp = client.post(
        f"/experiments/{exp_id}/train",
        json={"model_type": "random_forest", "hyperparams": {"n_estimators": -1}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "FAILED"
    assert "cv_std" not in body["metrics"]
    assert db_session.get(Run, body["run_id"]) is not None
