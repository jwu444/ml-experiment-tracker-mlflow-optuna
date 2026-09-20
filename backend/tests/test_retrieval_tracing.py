"""Retrieval emits spans, and they carry no payloads (3.1).

The Jaeger acceptance criterion for Phase 3 names three kinds of span under one
trace: LLM, tool and RETRIEVAL. The first two shipped with the agent loop; this
covers the third, and pins the rule that makes exporting them safe — attributes
are ids, counts and durations, never the query, the filter values or the text
that came back.
"""

from app import retrieval
from app.models import Dataset, Experiment, ExperimentNoteChunk, Run

# Anything here appearing in an attribute means a payload reached the exporter.
SECRET_QUERY = "what did the heteroscedastic residuals say about revenue"
SECRET_TEXT = "Ridge beat persistence by 4% on the holdout."


def _seed(db_session):
    dataset = Dataset(
        name="d.csv", data_csv="a,b\n1,2\n", content_hash="h", n_rows=1, n_cols=2, profile_json={}
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
        experiment_id=experiment.id,
        mlflow_run_id="m1",
        model_type="ridge",
        notes=SECRET_TEXT,
        notes_status="approved",
    )
    db_session.add(run)
    db_session.flush()
    chunk = ExperimentNoteChunk(
        source_type="note",
        source_id=run.id,
        chunk_index=0,
        chunk_text=SECRET_TEXT,
        embedding=[0.1] * 512,
        status="approved",
    )
    db_session.add(chunk)
    db_session.commit()
    return dataset, experiment, run, chunk


def _by_name(spans):
    return {s.name: s for s in spans.get_finished_spans()}


def test_a_search_emits_nested_retrieval_spans(db_session, monkeypatch, spans, fake_voyage):
    _, _, _, chunk = _seed(db_session)
    monkeypatch.setattr(retrieval, "_rank_chunks", lambda *a, **k: [(chunk, 0.1)])

    retrieval.search_runs(db_session, SECRET_QUERY, k=3, client=fake_voyage)

    found = _by_name(spans)
    assert "retrieval.search" in found
    assert "retrieval.embed_query" in found
    assert "retrieval.rank_chunks" in found
    search = found["retrieval.search"]
    assert search.attributes["k"] == 3
    assert search.attributes["sources"] == 1
    assert search.attributes["chunks"] == 1


def test_the_unrestricted_flag_distinguishes_no_filters_from_no_matches(
    db_session, monkeypatch, spans, fake_voyage
):
    """keys=None means "search everything"; keys=() means "the filters matched
    nothing". Reading candidate_keys=0 alone cannot tell those apart, and the
    difference is the whole point of the distinction (3.4a)."""
    _, _, _, chunk = _seed(db_session)
    monkeypatch.setattr(retrieval, "_rank_chunks", lambda *a, **k: [(chunk, 0.1)])

    retrieval.search_runs(db_session, SECRET_QUERY, client=fake_voyage)
    assert _by_name(spans)["retrieval.search"].attributes["unrestricted"] is True

    spans.clear()
    hits, _ = retrieval.search_runs(
        db_session,
        SECRET_QUERY,
        filters=retrieval.Filters(model_type="no-such-model"),
        client=fake_voyage,
    )
    search = _by_name(spans)["retrieval.search"]
    assert hits == []
    assert search.attributes["unrestricted"] is False
    assert search.attributes["candidate_keys"] == 0
    assert search.attributes["sources"] == 0


def test_a_filtered_search_records_how_many_filters_not_which(
    db_session, monkeypatch, spans, fake_voyage
):
    """A filter VALUE is the model's own query text. Counting them is a metric;
    exporting them is a payload."""
    _, _, run, chunk = _seed(db_session)
    monkeypatch.setattr(retrieval, "_rank_chunks", lambda *a, **k: [(chunk, 0.1)])

    retrieval.search_runs(
        db_session,
        SECRET_QUERY,
        filters=retrieval.Filters(model_type="ridge", task_type="regression"),
        client=fake_voyage,
    )
    assert _by_name(spans)["retrieval.search"].attributes["filters"] == 2


def test_run_detail_emits_a_span_carrying_the_id_only(db_session, spans, mlflow_store):
    _, _, run, _ = _seed(db_session)
    retrieval.get_run_detail(db_session, run.id)

    detail = _by_name(spans)["retrieval.run_detail"]
    assert detail.attributes["run_id"] == run.id
    assert SECRET_TEXT not in str(dict(detail.attributes))


def test_no_span_attribute_carries_the_query_or_the_retrieved_text(
    db_session, monkeypatch, spans, fake_voyage
):
    """An exporter is a place data leaves the process from (3.1). A trace is for
    finding where the time and the calls went — the note text, the query and the
    embedding vector have no business in one."""
    _, _, _, chunk = _seed(db_session)
    monkeypatch.setattr(retrieval, "_rank_chunks", lambda *a, **k: [(chunk, 0.1)])

    hits, _ = retrieval.search_runs(
        db_session,
        SECRET_QUERY,
        filters=retrieval.Filters(model_type="ridge"),
        client=fake_voyage,
    )
    assert hits and SECRET_TEXT in hits[0].snippet  # the text IS returned...

    for span in spans.get_finished_spans():  # ...and never exported
        rendered = f"{span.name} {dict(span.attributes)}"
        assert SECRET_TEXT not in rendered
        assert SECRET_QUERY not in rendered
        assert "heteroscedastic" not in rendered
        assert "ridge" not in rendered
