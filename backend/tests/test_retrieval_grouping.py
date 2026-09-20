"""Stage 2: grouping chunks into sources, and the run-detail lookup (3.4).

`_rank_chunks` is monkeypatched throughout — it is the one function that emits
pgvector's `<=>`, which SQLite cannot execute. Its real SQL is covered by
test_retrieval_postgres.py.
"""

import pytest
from app import retrieval
from app.models import Dataset, Experiment, ExperimentNoteChunk, Run


def _seed_run(db_session, *, model_type="ridge", notes="Ridge beat the baseline."):
    dataset = Dataset(
        name="d.csv",
        data_csv="a,b\n1,2\n",
        content_hash="h",
        n_rows=1,
        n_cols=2,
        profile_json={},
    )
    db_session.add(dataset)
    db_session.flush()
    experiment = Experiment(
        name="nowcast",
        objective="Beat the baseline.",
        dataset_id=dataset.id,
        target_column="b",
        task_type="regression",
        primary_metric="rmse",
    )
    db_session.add(experiment)
    db_session.flush()
    run = Run(
        mlflow_run_id="mlf-1",
        experiment_id=experiment.id,
        model_type=model_type,
        notes=notes,
        notes_status="approved",
    )
    db_session.add(run)
    db_session.commit()
    return dataset, experiment, run


def _chunk(db_session, source_type, source_id, index, text):
    row = ExperimentNoteChunk(
        source_type=source_type,
        source_id=source_id,
        chunk_text=text,
        chunk_index=index,
        status="approved",
        embedding=[0.0] * 512,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _ranked(pairs):
    """Build a _rank_chunks stub returning (chunk_row, distance) pairs."""

    def stub(session, vector, keys, limit):
        return list(pairs)[:limit]

    return stub


def test_k_counts_sources_not_chunks(db_session, monkeypatch, fake_voyage):
    """A four-chunk finding must not consume the whole budget: the agent would
    answer from one source while sounding like it surveyed the history."""
    _, _, run = _seed_run(db_session)
    fat = [_chunk(db_session, "diagnostic", run.id, i, f"chunk {i}") for i in range(4)]
    lean = _chunk(db_session, "note", run.id, 0, "the note")
    monkeypatch.setattr(
        retrieval,
        "_rank_chunks",
        _ranked([(c, 0.1 + 0.01 * i) for i, c in enumerate(fat)] + [(lean, 0.5)]),
    )

    hits, _ = retrieval.search_runs(db_session, "q", k=2, client=fake_voyage)
    assert {h.source_type for h in hits} == {"diagnostic", "note"}
    assert len(hits) == 2


def test_a_source_is_scored_by_its_single_best_chunk(db_session, monkeypatch, fake_voyage):
    """Averaging punishes a long, thorough write-up for its own breadth — the
    exact document most worth surfacing."""
    _, _, run = _seed_run(db_session)
    best = _chunk(db_session, "diagnostic", run.id, 0, "bullseye")
    worst = _chunk(db_session, "diagnostic", run.id, 1, "tangent")
    monkeypatch.setattr(retrieval, "_rank_chunks", _ranked([(best, 0.05), (worst, 0.95)]))

    hits, _ = retrieval.search_runs(db_session, "q", k=5, client=fake_voyage)
    assert len(hits) == 1
    assert hits[0].score == pytest.approx(0.95)
    assert hits[0].snippet == "bullseye"


def test_hits_are_ordered_by_score_descending(db_session, monkeypatch, fake_voyage):
    _, _, run = _seed_run(db_session)
    near = _chunk(db_session, "note", run.id, 0, "near")
    far = _chunk(db_session, "diagnostic", run.id, 0, "far")
    monkeypatch.setattr(retrieval, "_rank_chunks", _ranked([(far, 0.8), (near, 0.2)]))

    hits, _ = retrieval.search_runs(db_session, "q", k=5, client=fake_voyage)
    assert [h.snippet for h in hits] == ["near", "far"]
    assert hits[0].score > hits[1].score


def test_a_hit_carries_the_ids_the_ui_deep_links_with(db_session, monkeypatch, fake_voyage):
    """3.6: an eda hit links to /datasets/{dataset_id}, a note or diagnostic hit
    to /experiments/{experiment_id}. Resolved here, where the join is already
    open, rather than by an N+1 in the route."""
    dataset, experiment, run = _seed_run(db_session)
    note = _chunk(db_session, "note", run.id, 0, "the note")
    eda = _chunk(db_session, "eda", dataset.id, 0, "the eda")
    monkeypatch.setattr(retrieval, "_rank_chunks", _ranked([(note, 0.1), (eda, 0.2)]))

    hits, _ = retrieval.search_runs(db_session, "q", k=5, client=fake_voyage)
    by_type = {h.source_type: h for h in hits}
    assert by_type["note"].run_id == run.id
    assert by_type["note"].experiment_id == experiment.id
    assert by_type["eda"].dataset_id == dataset.id
    assert by_type["eda"].run_id is None


def test_an_empty_index_returns_no_hits_and_no_error(db_session, monkeypatch, fake_voyage):
    """Before `make embed` has ever run this is the normal state. It must be an
    empty list the agent can report, not an exception."""
    monkeypatch.setattr(retrieval, "_rank_chunks", _ranked([]))
    hits, warnings = retrieval.search_runs(db_session, "q", k=5, client=fake_voyage)
    assert hits == []
    assert warnings == []


def test_filters_matching_nothing_skip_the_vector_query(db_session, monkeypatch, fake_voyage):
    """keys == () means stage 1 excluded everything. Running the similarity
    search anyway would return the whole corpus, ignoring the filter."""
    _seed_run(db_session)
    called = []
    monkeypatch.setattr(retrieval, "_rank_chunks", lambda *a, **k: called.append(1) or [])

    hits, _ = retrieval.search_runs(
        db_session, "q", filters=retrieval.Filters(model_type="nope"), client=fake_voyage
    )
    assert hits == []
    assert called == []


def test_the_query_is_embedded_with_the_query_input_type(db_session, monkeypatch, fake_voyage):
    monkeypatch.setattr(retrieval, "_rank_chunks", _ranked([]))
    retrieval.search_runs(db_session, "q", client=fake_voyage)
    assert fake_voyage.calls[0]["input_type"] == "query"


def test_stage_one_warnings_are_passed_through(db_session, monkeypatch, fake_voyage):
    _seed_run(db_session)

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(retrieval.experiment_log, "fetch_runs", boom)
    monkeypatch.setattr(retrieval, "_rank_chunks", _ranked([]))

    _, warnings = retrieval.search_runs(
        db_session, "q", filters=retrieval.Filters(status="FINISHED"), client=fake_voyage
    )
    assert warnings and "status" in warnings[0]


def test_get_run_detail_merges_postgres_and_mlflow(db_session, monkeypatch):
    _, experiment, run = _seed_run(db_session)
    monkeypatch.setattr(
        retrieval.experiment_log,
        "fetch_runs",
        lambda ids: {
            "mlf-1": retrieval.experiment_log.RunData(
                run_id="mlf-1",
                status="FINISHED",
                params={"alpha": "1.0"},
                metrics={"rmse": 12.5, "cv_rmse": 13.0, "cv_std": 0.4},
            )
        },
    )

    detail = retrieval.get_run_detail(db_session, run.id)
    assert detail.model_type == "ridge"
    assert detail.experiment_name == "nowcast"
    assert detail.experiment_objective == "Beat the baseline."
    assert detail.params["alpha"] == "1.0"
    assert detail.metrics["rmse"] == 12.5
    assert detail.cv_std == 0.4
    assert detail.notes_status == "approved"
    assert detail.experiment_id == experiment.id


def test_get_run_detail_reports_a_missing_cv_std_as_none(db_session, monkeypatch):
    """3.0 backfills the band, but runs logged before it have none. None is what
    lets the agent say "unquantified" instead of inventing a number."""
    _, _, run = _seed_run(db_session)
    monkeypatch.setattr(
        retrieval.experiment_log,
        "fetch_runs",
        lambda ids: {
            "mlf-1": retrieval.experiment_log.RunData(
                run_id="mlf-1", status="FINISHED", params={}, metrics={"rmse": 12.5}
            )
        },
    )
    assert retrieval.get_run_detail(db_session, run.id).cv_std is None


def test_get_run_detail_on_an_unknown_run_is_a_key_error(db_session):
    with pytest.raises(KeyError):
        retrieval.get_run_detail(db_session, "no-such-run")


def test_get_run_detail_raises_when_the_store_is_unreachable(db_session, monkeypatch):
    """Unlike the status FILTER, this one has no partial answer to give: the
    whole point of the call is the params and metrics MLflow holds."""
    _, _, run = _seed_run(db_session)

    def boom(ids):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(retrieval.experiment_log, "fetch_runs", boom)
    with pytest.raises(retrieval.TrackingStoreUnavailable):
        retrieval.get_run_detail(db_session, run.id)
