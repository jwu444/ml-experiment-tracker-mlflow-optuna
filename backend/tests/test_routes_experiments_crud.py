import pytest
from app.models import Experiment, Run

pytestmark = pytest.mark.usefixtures("mlflow_store")


def _make_experiment(client, dataset_id, **over):
    body = {"name": "nowcast", "target_column": "price", "dataset_id": dataset_id}
    body.update(over)
    resp = client.post("/experiments", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_defaults_the_metric_from_the_task_type(client, dataset_id):
    body = _make_experiment(client, dataset_id)
    assert body["primary_metric"] == "rmse"
    assert body["metric_direction"] == "minimize"
    assert body["n_runs"] == 0


def test_create_classification_defaults_to_f1_macro(client, dataset_id):
    body = _make_experiment(client, dataset_id, task_type="classification")
    assert body["primary_metric"] == "f1_macro"
    assert body["metric_direction"] == "maximize"


def test_create_rejects_an_unknown_dataset(client):
    resp = client.post(
        "/experiments",
        json={"name": "x", "target_column": "price", "dataset_id": "nope"},
    )
    assert resp.status_code == 404


def test_a_target_column_that_is_not_in_the_dataset_is_422(client, dataset_id):
    """target_column is fixed at creation and no PATCH can change it, so a typo
    would otherwise produce an experiment that 422s on every train call forever
    with no API route to repair it."""
    resp = client.post(
        "/experiments",
        json={"name": "typo", "target_column": "pirce", "dataset_id": dataset_id},
    )
    assert resp.status_code == 422


def test_the_dataset_version_is_pinned_from_the_dataset_not_the_request(client, dataset_id):
    """It is the content hash of the dataset named above (D5/D13) — the same one
    log_run tags each run with. A caller-supplied value could disagree with the
    bytes actually scored, and nothing downstream would notice."""
    resp = client.post(
        "/experiments",
        json={
            "name": "pinned",
            "target_column": "price",
            "dataset_id": dataset_id,
            "dataset_version": "not-the-real-hash",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["dataset_version"] != "not-the-real-hash"
    assert len(resp.json()["dataset_version"]) == 64


def test_a_duplicate_name_is_409(client, dataset_id):
    """MLflow resolves an experiment by name (D35), so two investigations sharing
    one would file their runs into a single MLflow experiment while presenting
    as separate leaderboards here."""
    _make_experiment(client, dataset_id, name="nowcast")
    resp = client.post(
        "/experiments",
        json={"name": "nowcast", "target_column": "price", "dataset_id": dataset_id},
    )
    assert resp.status_code == 409


def test_renaming_onto_an_existing_name_is_409(client, dataset_id):
    _make_experiment(client, dataset_id, name="taken")
    other = _make_experiment(client, dataset_id, name="free")
    assert client.patch(f"/experiments/{other['id']}", json={"name": "taken"}).status_code == 409
    # Renaming to its own name is not a conflict with itself.
    assert client.patch(f"/experiments/{other['id']}", json={"name": "free"}).status_code == 200


def test_list_and_get_round_trip(client, dataset_id):
    created = _make_experiment(client, dataset_id)
    assert client.get("/experiments").json()[0]["id"] == created["id"]
    assert client.get(f"/experiments/{created['id']}").json()["name"] == "nowcast"


def test_get_unknown_experiment_is_404(client):
    assert client.get("/experiments/nope").status_code == 404


def test_the_dataset_is_reported_by_name_not_only_by_id(client, dataset_id):
    """The UI renders this column, and a raw uuid tells a reader nothing about
    which data the investigation is over."""
    created = _make_experiment(client, dataset_id)
    assert created["dataset_name"] == client.get(f"/datasets/{dataset_id}").json()["name"]
    assert client.get("/experiments").json()[0]["dataset_name"] == created["dataset_name"]


def test_an_experiment_with_no_dataset_reports_no_dataset_name(client):
    created = _make_experiment(client, None)
    assert created["dataset_id"] is None
    assert created["dataset_name"] is None


def test_patch_edits_name_and_objective(client, dataset_id):
    created = _make_experiment(client, dataset_id)
    resp = client.patch(f"/experiments/{created['id']}", json={"objective": "beat persistence"})
    assert resp.status_code == 200
    assert resp.json()["objective"] == "beat persistence"
    assert resp.json()["name"] == "nowcast", "an omitted field is left alone"


def test_leaderboard_ranks_and_flags_the_best(client, db_session, dataset_id, monkeypatch):
    from app import experiment_log
    from app.routes import experiments as routes

    created = _make_experiment(client, dataset_id)
    for run_id, mlflow_id in [("r1", "m1"), ("r2", "m2")]:
        db_session.add(
            Run(
                id=run_id,
                mlflow_run_id=mlflow_id,
                model_type="ridge",
                experiment_id=created["id"],
                notes="",
                notes_status="draft",
            )
        )
    db_session.commit()

    monkeypatch.setattr(
        routes.experiment_log,
        "fetch_runs",
        lambda ids: {
            "m1": experiment_log.RunData("m1", "FINISHED", {}, {"rmse": 9.0}),
            "m2": experiment_log.RunData("m2", "FINISHED", {}, {"rmse": 3.0}),
        },
    )
    body = client.get(f"/experiments/{created['id']}/runs").json()
    assert body["ranked"] is True
    assert [row["run"]["id"] for row in body["rows"]] == ["r2", "r1"]
    assert body["rows"][0]["is_best"] is True


def test_the_leaderboard_shows_only_this_experiments_runs(client, db_session, dataset_id):
    """D38: ranking happens WITHIN one experiment and never across them, because
    runs of different investigations are not on a common scale. Dropping the
    experiment filter leaves every other test in the suite green."""
    mine = _make_experiment(client, dataset_id)
    theirs = _make_experiment(client, dataset_id, name="unrelated")
    for run_id, exp in [("r1", mine), ("r2", theirs)]:
        db_session.add(
            Run(
                id=run_id,
                mlflow_run_id=f"m-{run_id}",
                model_type="ridge",
                experiment_id=exp["id"],
                notes="",
                notes_status="draft",
            )
        )
    db_session.commit()

    body = client.get(f"/experiments/{mine['id']}/runs").json()
    assert [row["run"]["id"] for row in body["rows"]] == ["r1"]
    assert client.get("/runs", params={"experiment_id": theirs["id"]}).json()[0]["id"] == "r2"


def test_leaderboard_degrades_when_mlflow_is_down(client, db_session, dataset_id, monkeypatch):
    """A read must not 500 on a down tracking store (§7.4)."""
    from app.routes import experiments as routes

    created = _make_experiment(client, dataset_id)
    db_session.add(
        Run(
            id="r1",
            mlflow_run_id="m1",
            model_type="ridge",
            experiment_id=created["id"],
            notes="",
            notes_status="draft",
        )
    )
    db_session.commit()

    def boom(ids):
        raise RuntimeError("store down")

    monkeypatch.setattr(routes.experiment_log, "fetch_runs", boom)
    resp = client.get(f"/experiments/{created['id']}/runs")
    assert resp.status_code == 200
    assert resp.json()["ranked"] is False
    assert resp.json()["mlflow_available"] is False
    assert resp.json()["rows"][0]["rank"] is None


def _unrepaired_experiment(db_session, dataset_id, target=""):
    """An investigation as the backfill leaves it when no tracking store was
    reachable: everything set except the target.

    `POST /experiments` cannot produce this — it validates the target against the
    dataset — which is exactly why the migration is the only way in and why the
    repair has to exist.
    """
    row = Experiment(
        name="recovered",
        dataset_id=dataset_id,
        target_column=target,
        task_type="regression",
        primary_metric="rmse",
        metric_direction="minimize",
    )
    db_session.add(row)
    db_session.commit()
    return row.id


def test_patch_fills_an_empty_target_column(client, db_session, dataset_id):
    """Without this the backfill's unknowable case is terminal: the investigation
    exists, lists, and looks ordinary, but /train and /tune both 422 forever and no
    route can supply the missing field."""
    experiment_id = _unrepaired_experiment(db_session, dataset_id)

    resp = client.patch(f"/experiments/{experiment_id}", json={"target_column": "price"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["target_column"] == "price"


def test_patch_cannot_change_a_target_that_is_already_set(client, dataset_id):
    """Filling a gap and re-pointing a live investigation are different operations.
    Runs are comparable because they answer one question (D34); silently re-aiming
    the target would leave a leaderboard ranking two questions against each other
    with every row still looking valid."""
    created = _make_experiment(client, dataset_id)

    resp = client.patch(f"/experiments/{created['id']}", json={"target_column": "quantity"})

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"].startswith("target_column is already set")


def test_patch_rejects_a_target_that_is_not_a_dataset_column(client, db_session, dataset_id):
    """The repair goes through the same column check as creation — a repair that
    accepted a typo would just re-create the dead investigation it is fixing."""
    experiment_id = _unrepaired_experiment(db_session, dataset_id)

    resp = client.patch(f"/experiments/{experiment_id}", json={"target_column": "nope"})

    assert resp.status_code == 422, resp.text


def test_patch_rejects_an_empty_target_column(client, db_session, dataset_id):
    """Explicitly writing "" is the state being repaired, not a way to request it."""
    experiment_id = _unrepaired_experiment(db_session, dataset_id)

    resp = client.patch(f"/experiments/{experiment_id}", json={"target_column": "  "})

    assert resp.status_code == 422, resp.text
