import uuid

import pytest
from app import experiment_log

# Every test trains, which logs to MLflow.
pytestmark = pytest.mark.usefixtures("mlflow_store")


def _train(client, dataset_id, model_type="ridge", target="price", task_type="regression", **extra):
    # dataset_id/target_column/task_type moved to the parent Experiment (D34) —
    # a run can no longer be launched without one, so every call here creates a
    # fresh experiment to train inside. Each test still gets the run-level
    # fields it asserts on; the ones that filter across two runs on differing
    # task_type/target now do so across two experiments instead of one.
    resp = client.post(
        "/experiments",
        json={
            # Distinct per call: an experiment name is unique (D35 — MLflow
            # resolves by it), so a shared literal makes the second call 409.
            "name": f"exp-{uuid.uuid4()}",
            "target_column": target,
            "dataset_id": dataset_id,
            "task_type": task_type,
        },
    )
    assert resp.status_code == 201, resp.text
    exp_id = resp.json()["id"]
    return client.post(
        f"/experiments/{exp_id}/train",
        json={"model_type": model_type, **extra},
    ).json()


def test_list_merges_mlflow_params_and_metrics(client, dataset_id):
    _train(client, dataset_id)
    body = client.get("/runs").json()
    assert len(body) == 1
    assert body[0]["params"]["model_type"] == "ridge"
    assert "rmse" in body[0]["metrics"]
    assert body[0]["mlflow_available"] is True


def test_list_reports_the_task_type_and_the_review_status(client, dataset_id):
    _train(client, dataset_id, notes="baseline")
    row = client.get("/runs").json()[0]
    assert row["task_type"] == "regression"
    assert row["notes_status"] == "draft"


def test_list_filters_by_model_type(client, dataset_id):
    for m in ("ridge", "random_forest"):
        _train(client, dataset_id, model_type=m)
    assert len(client.get("/runs?model_type=ridge").json()) == 1


def test_list_filters_by_task_type(client, dataset_id):
    # A regression rmse and a classification f1_macro do not belong in one
    # leaderboard, so the page must be able to ask for one task type at a time.
    _train(client, dataset_id)
    _train(
        client,
        dataset_id,
        model_type="logistic_regression",
        target="chipset",
        task_type="classification",
    )
    rows = client.get("/runs?task_type=classification").json()
    assert [r["model_type"] for r in rows] == ["logistic_regression"]


def test_list_filters_by_notes_status(client, dataset_id):
    # Notes are required to approve — see test_an_empty_note_cannot_be_approved.
    a = _train(client, dataset_id, notes="worth keeping")
    _train(client, dataset_id, model_type="random_forest")
    client.patch(f"/runs/{a['run_id']}", json={"notes_status": "approved"})
    assert len(client.get("/runs?notes_status=draft").json()) == 1
    assert len(client.get("/runs?notes_status=approved").json()) == 1


def test_list_degrades_when_mlflow_is_unreachable(client, dataset_id, monkeypatch):
    _train(client, dataset_id)

    def boom(*a, **k):
        raise RuntimeError("store down")

    monkeypatch.setattr("app.routes.runs.experiment_log.fetch_runs", boom)
    body = client.get("/runs").json()
    assert body[0]["mlflow_available"] is False
    assert body[0]["metrics"] == {}
    assert body[0]["model_type"] == "ridge"  # our own columns still resolve
    assert body[0]["notes_status"] == "draft"


def test_status_filter_is_503_when_mlflow_is_unreachable(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("store down")

    monkeypatch.setattr("app.routes.runs.experiment_log.search_runs", boom)
    assert client.get("/runs?status=FINISHED").status_code == 503


def test_detail_404s_on_unknown_id(client):
    assert client.get("/runs/nope").status_code == 404


def test_patch_updates_the_notes(client, dataset_id):
    created = _train(client, dataset_id)
    resp = client.patch(f"/runs/{created['run_id']}", json={"notes": "observed X"})
    assert resp.status_code == 200
    assert resp.json()["notes"] == "observed X"
    assert client.get(f"/runs/{created['run_id']}").json()["notes"] == "observed X"


def test_editing_the_notes_alone_does_not_approve_them(client, dataset_id):
    # The seeding script in Task 10 writes through this route. If a write were an
    # implicit approval, every generated note would arrive pre-blessed and D20
    # would mean nothing.
    created = _train(client, dataset_id)
    body = client.patch(f"/runs/{created['run_id']}", json={"notes": "generated"}).json()
    assert body["notes_status"] == "draft"


def test_approving_a_note_is_an_explicit_transition(client, dataset_id):
    created = _train(client, dataset_id, notes="a real observation")
    body = client.patch(f"/runs/{created['run_id']}", json={"notes_status": "approved"}).json()
    assert body["notes_status"] == "approved"


def test_a_worthless_note_can_be_rejected_without_being_rewritten(client, dataset_id):
    # D20's third state. Rejection needs no text — the whole point is that there
    # was nothing worth keeping — so the empty-note guard must not apply here.
    created = _train(client, dataset_id)
    body = client.patch(f"/runs/{created['run_id']}", json={"notes_status": "rejected"}).json()
    assert body["notes_status"] == "rejected"


def test_an_empty_note_cannot_be_approved(client, dataset_id):
    # "Approved" has to mean a human read something. Approving an empty note is
    # the one way to get an approved-but-meaningless row into Phase 3's index.
    created = _train(client, dataset_id)
    resp = client.patch(f"/runs/{created['run_id']}", json={"notes_status": "approved"})
    assert resp.status_code == 422


def test_an_unknown_notes_status_is_rejected(client, dataset_id):
    created = _train(client, dataset_id)
    resp = client.patch(f"/runs/{created['run_id']}", json={"notes_status": "blessed"})
    assert resp.status_code == 422


def test_patch_404s_on_unknown_id(client):
    assert client.patch("/runs/nope", json={"notes": "x"}).status_code == 404


def test_the_page_size_has_a_ceiling(client):
    # Finding 4 from the #36 review: without le=, one request can ask for the
    # whole table. 422 rather than a silent clamp, matching every other bad
    # parameter on this router.
    assert client.get("/runs?limit=100000").status_code == 422
    assert client.get("/runs?limit=0").status_code == 422
    assert client.get("/runs?offset=-1").status_code == 422


def test_search_runs_asks_mlflow_for_a_bounded_page(monkeypatch):
    # The other half of Finding 4: an unfiltered search_runs asks for every run
    # in the store, so the request itself has to carry a ceiling.
    seen = {}

    def fake_search_runs(**kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr(experiment_log.mlflow, "search_runs", fake_search_runs)
    monkeypatch.setattr(experiment_log.settings, "mlflow_tracking_uri", "sqlite:///unused.db")
    experiment_log.search_runs(None, None, None)
    assert seen["max_results"] == experiment_log.SEARCH_MAX_RESULTS
