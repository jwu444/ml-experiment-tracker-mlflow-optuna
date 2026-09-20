import pytest

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


def test_tune_creates_one_run_row_per_trial(client, dataset_id, db_session):
    from app.models import Run

    exp_id = _create_experiment(client, dataset_id, "price")
    resp = client.post(
        f"/experiments/{exp_id}/tune",
        json={"model_type": "ridge", "n_trials": 3},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["n_trials"] == 3
    assert len(body["trials"]) == 3
    assert body["best_run_id"]
    assert db_session.query(Run).count() == 3


def test_n_trials_above_the_cap_is_422(client, dataset_id):
    exp_id = _create_experiment(client, dataset_id, "price")
    resp = client.post(
        f"/experiments/{exp_id}/tune",
        json={"model_type": "ridge", "n_trials": 9999},
    )
    assert resp.status_code == 422


def test_tuning_a_model_with_an_empty_search_space_is_422(client, dataset_id):
    """Eight identical trials is not a search. Rejected rather than run."""
    exp_id = _create_experiment(client, dataset_id, "price")
    resp = client.post(
        f"/experiments/{exp_id}/tune",
        json={"model_type": "persistence", "n_trials": 8},
    )
    assert resp.status_code == 422
    assert "search space" in resp.json()["detail"].lower()
