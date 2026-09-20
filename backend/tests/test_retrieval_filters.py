"""The structured stage: relational filters resolved before any vector work (D15).

Runs entirely on SQLite — nothing here touches pgvector.
"""

from app import retrieval
from app.experiment_log import RunData
from app.models import Dataset, Experiment, Run


def _store(**statuses):
    """A fake `experiment_log.fetch_runs`: maps mlflow run id -> status, and
    honours the id list it is handed, so a test can assert on the scoping."""

    def fetch_runs(run_ids):
        return {
            run_id: RunData(run_id=run_id, status=statuses[run_id], params={}, metrics={})
            for run_id in run_ids
            if run_id in statuses
        }

    return fetch_runs


def _seed(db_session, *, dataset_name, model_type, task_type="regression", notes="n"):
    dataset = Dataset(
        name=dataset_name,
        data_csv="a,b\n1,2\n",
        content_hash=dataset_name,
        n_rows=1,
        n_cols=2,
        profile_json={},
    )
    db_session.add(dataset)
    db_session.flush()
    experiment = Experiment(
        name=f"{dataset_name}-{model_type}-{task_type}",
        dataset_id=dataset.id,
        target_column="b",
        task_type=task_type,
        primary_metric="rmse",
    )
    db_session.add(experiment)
    db_session.flush()
    run = Run(
        mlflow_run_id=f"mlf-{dataset_name}-{model_type}",
        experiment_id=experiment.id,
        model_type=model_type,
        notes=notes,
        notes_status="approved",
    )
    db_session.add(run)
    db_session.commit()
    return dataset, experiment, run


def test_no_filters_means_unrestricted(db_session):
    """keys=None is 'search everything'. Returning every key instead would put an
    IN list of the whole corpus into the vector query for the common case."""
    _seed(db_session, dataset_name="panel", model_type="ridge")
    candidates = retrieval.candidate_runs(db_session, retrieval.Filters())
    assert candidates.keys is None
    assert candidates.warnings == ()


def test_model_type_filters_on_the_run(db_session):
    _, _, ridge = _seed(db_session, dataset_name="panel", model_type="ridge")
    _seed(db_session, dataset_name="panel2", model_type="random_forest")

    candidates = retrieval.candidate_runs(db_session, retrieval.Filters(model_type="ridge"))
    assert ("note", ridge.id) in candidates.keys
    assert not any(key[0] == "note" and key[1] != ridge.id for key in candidates.keys)


def test_dataset_id_filters_on_the_parent_experiment(db_session):
    """D37: dataset_id lives on app.experiments, not on app.runs. A filter that
    looked for runs.dataset_id would not compile, but one written against a
    stale mental model of the schema silently matches nothing."""
    dataset, _, run = _seed(db_session, dataset_name="panel", model_type="ridge")
    _seed(db_session, dataset_name="other", model_type="ridge")

    candidates = retrieval.candidate_runs(db_session, retrieval.Filters(dataset_id=dataset.id))
    assert ("note", run.id) in candidates.keys
    assert ("eda", dataset.id) in candidates.keys


def test_task_type_filters_on_the_parent_experiment(db_session):
    _, _, clf = _seed(
        db_session, dataset_name="c", model_type="logistic_regression", task_type="classification"
    )
    _seed(db_session, dataset_name="r", model_type="ridge", task_type="regression")

    candidates = retrieval.candidate_runs(db_session, retrieval.Filters(task_type="classification"))
    assert {key for key in candidates.keys if key[0] == "note"} == {("note", clf.id)}


def test_experiment_id_filters_on_the_run(db_session):
    _, experiment, run = _seed(db_session, dataset_name="panel", model_type="ridge")
    _seed(db_session, dataset_name="other", model_type="ridge")

    candidates = retrieval.candidate_runs(
        db_session, retrieval.Filters(experiment_id=experiment.id)
    )
    assert {key for key in candidates.keys if key[0] == "note"} == {("note", run.id)}


def test_a_matching_run_expands_to_three_chunk_keys(db_session):
    """One run makes its own note and diagnostic reachable, plus the EDA on the
    dataset its experiment was run against (D30). Without the expansion, 'what
    do we know about this data' finds run notes and never the EDA."""
    dataset, _, run = _seed(db_session, dataset_name="panel", model_type="ridge")
    candidates = retrieval.candidate_runs(db_session, retrieval.Filters(model_type="ridge"))
    assert set(candidates.keys) == {
        ("note", run.id),
        ("diagnostic", run.id),
        ("eda", dataset.id),
    }


def test_an_experiment_with_no_dataset_contributes_no_eda_key(db_session):
    """experiments.dataset_id is nullable. ("eda", None) is not a key."""
    experiment = Experiment(
        name="orphan",
        dataset_id=None,
        target_column="b",
        task_type="regression",
        primary_metric="rmse",
    )
    db_session.add(experiment)
    db_session.flush()
    run = Run(
        mlflow_run_id="mlf-orphan",
        experiment_id=experiment.id,
        model_type="ridge",
        notes="n",
        notes_status="approved",
    )
    db_session.add(run)
    db_session.commit()

    candidates = retrieval.candidate_runs(db_session, retrieval.Filters(model_type="ridge"))
    assert all(key[1] is not None for key in candidates.keys)
    assert ("eda", None) not in candidates.keys


def test_a_filter_matching_nothing_returns_empty_not_unrestricted(db_session):
    """() and None are different answers. Collapsing them turns 'no ridge runs
    exist' into 'here is everything', which reads as a confident wrong answer."""
    _seed(db_session, dataset_name="panel", model_type="ridge")
    candidates = retrieval.candidate_runs(
        db_session, retrieval.Filters(model_type="does_not_exist")
    )
    assert candidates.keys == ()
    assert candidates.run_ids == ()


def test_status_intersects_with_the_tracking_store(db_session, monkeypatch):
    _, _, finished = _seed(db_session, dataset_name="a", model_type="ridge")
    _, _, failed = _seed(db_session, dataset_name="b", model_type="ridge")
    monkeypatch.setattr(
        retrieval.experiment_log,
        "fetch_runs",
        _store(**{finished.mlflow_run_id: "FINISHED", failed.mlflow_run_id: "FAILED"}),
    )

    candidates = retrieval.candidate_runs(db_session, retrieval.Filters(status="FINISHED"))
    assert ("note", finished.id) in candidates.keys
    assert ("note", failed.id) not in candidates.keys


def test_an_unreachable_tracking_store_warns_rather_than_failing(db_session, monkeypatch):
    """The store being down must not take retrieval with it: notes and findings
    live in Postgres and are still answerable. A 503 here would make the whole
    agent unavailable because of an optional filter."""
    _, _, run = _seed(db_session, dataset_name="a", model_type="ridge")

    def boom(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(retrieval.experiment_log, "fetch_runs", boom)

    candidates = retrieval.candidate_runs(db_session, retrieval.Filters(status="FINISHED"))
    assert ("note", run.id) in candidates.keys  # the other filters still applied
    assert len(candidates.warnings) == 1
    assert "status" in candidates.warnings[0]


def test_status_alone_still_filters_relationally(db_session, monkeypatch):
    """status is the only filter with no relational column, so on its own it has
    to carry the whole query. An implementation that applied it only as a
    refinement of other filters would return every run here."""
    _, _, finished = _seed(db_session, dataset_name="a", model_type="ridge")
    _, _, other = _seed(db_session, dataset_name="b", model_type="ridge")
    monkeypatch.setattr(
        retrieval.experiment_log,
        "fetch_runs",
        _store(**{finished.mlflow_run_id: "FINISHED", other.mlflow_run_id: "FAILED"}),
    )

    candidates = retrieval.candidate_runs(db_session, retrieval.Filters(status="FINISHED"))
    assert candidates.run_ids == (finished.id,)


def test_the_status_query_is_scoped_to_the_relational_candidates(db_session, monkeypatch):
    """The MLflow side must be asked only about the runs the SQL stage admitted.

    The version this replaces called `search_runs(None, None, [status])`, which
    asks for the whole store capped at SEARCH_MAX_RESULTS and truncates BEFORE
    applying the status filter — so past that cap the filter silently returned
    fewer candidates than exist, which is the failure `keys=None` vs `()` was
    built to make impossible.
    """
    _, _, wanted = _seed(db_session, dataset_name="a", model_type="ridge")
    _, _, unrelated = _seed(db_session, dataset_name="b", model_type="random_forest")
    asked: list[list[str]] = []

    def fetch_runs(run_ids):
        asked.append(list(run_ids))
        return {wanted.mlflow_run_id: RunData(wanted.mlflow_run_id, "FINISHED", {}, {})}

    monkeypatch.setattr(retrieval.experiment_log, "fetch_runs", fetch_runs)

    retrieval.candidate_runs(db_session, retrieval.Filters(model_type="ridge", status="FINISHED"))
    assert asked == [[wanted.mlflow_run_id]]
    assert unrelated.mlflow_run_id not in asked[0]


def test_filters_are_anded_not_ored(db_session):
    """Two filters narrow. A caller asking for classification ridge runs and
    getting every ridge run plus every classifier gets a plausible answer built
    from the wrong rows."""
    _seed(db_session, dataset_name="a", model_type="ridge", task_type="regression")
    _seed(
        db_session,
        dataset_name="b",
        model_type="logistic_regression",
        task_type="classification",
    )

    candidates = retrieval.candidate_runs(
        db_session, retrieval.Filters(model_type="ridge", task_type="classification")
    )
    assert candidates.keys == ()
