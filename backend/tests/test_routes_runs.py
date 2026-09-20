import pytest
from app.models import Experiment, Run

pytestmark = pytest.mark.usefixtures("mlflow_store")


@pytest.fixture
def run_id(db_session, dataset_id):
    exp = Experiment(
        id="e1",
        name="n",
        target_column="price",
        dataset_id=dataset_id,
        task_type="regression",
        primary_metric="rmse",
        metric_direction="minimize",
    )
    db_session.add(exp)
    db_session.add(
        Run(
            id="r1",
            mlflow_run_id="m1",
            experiment_id="e1",
            model_type="ridge",
            notes="",
            notes_status="draft",
        )
    )
    db_session.commit()
    return "r1"


def test_get_run_inherits_the_experiments_fields(client, run_id, dataset_id):
    body = client.get(f"/runs/{run_id}").json()
    assert body["dataset_id"] == dataset_id, "inherited from the parent (D34)"
    assert body["task_type"] == "regression"
    # The link back UP the hierarchy. A run has no page of its own, so without
    # this a client holding only a run id (a diagnostic finding keys on one) has
    # no way to reach the leaderboard it belongs to.
    assert body["experiment_id"] == "e1"


def test_patch_writes_a_note_without_approving_it(client, run_id):
    """Writing a note is NOT approving it (D20) — the seeding script goes
    through this route, and an implicit approval would pre-bless every draft."""
    body = client.patch(f"/runs/{run_id}", json={"notes": "looks fine"}).json()
    assert body["notes"] == "looks fine"
    assert body["notes_status"] == "draft"


def test_an_empty_note_cannot_be_approved(client, run_id):
    resp = client.patch(f"/runs/{run_id}", json={"notes_status": "approved"})
    assert resp.status_code == 422


def test_an_empty_note_can_be_rejected(client, run_id):
    resp = client.patch(f"/runs/{run_id}", json={"notes_status": "rejected"})
    assert resp.status_code == 200


def test_list_filters_by_experiment(client, db_session, run_id):
    db_session.add(
        Experiment(
            id="e2",
            name="other",
            target_column="price",
            task_type="regression",
            primary_metric="rmse",
            metric_direction="minimize",
        )
    )
    db_session.add(
        Run(
            id="r2",
            mlflow_run_id="m2",
            experiment_id="e2",
            model_type="ridge",
            notes="",
            notes_status="draft",
        )
    )
    db_session.commit()
    body = client.get("/runs", params={"experiment_id": "e1"}).json()
    assert [r["id"] for r in body] == ["r1"]


def test_unknown_run_is_404(client):
    assert client.get("/runs/nope").status_code == 404
