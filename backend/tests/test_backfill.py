"""The backfill reconciles the index against what is currently approved (5.3).

The reaping case is the one an append-only implementation passes every other
test without, and it is the case D28 rests on.
"""

import logging

import pytest
from app import embeddings
from app.models import Dataset, Experiment, ExperimentNoteChunk, Finding, Run
from sqlalchemy import select


def _chunks(session, source_type, source_id):
    return list(
        session.execute(
            select(ExperimentNoteChunk)
            .where(ExperimentNoteChunk.source_type == source_type)
            .where(ExperimentNoteChunk.source_id == source_id)
            .order_by(ExperimentNoteChunk.chunk_index)
        ).scalars()
    )


def _seed_run(session, *, notes, notes_status):
    dataset = Dataset(
        name="d.csv",
        data_csv="a,b\n1,2\n",
        content_hash=f"h-{id(notes)}",
        n_rows=1,
        n_cols=2,
        profile_json={},
    )
    session.add(dataset)
    session.flush()
    experiment = Experiment(
        name=f"exp-{notes_status}-{id(notes)}",
        dataset_id=dataset.id,
        target_column="b",
        task_type="regression",
        primary_metric="rmse",
    )
    session.add(experiment)
    session.flush()
    run = Run(
        mlflow_run_id=f"mlf-{id(notes)}",
        experiment_id=experiment.id,
        model_type="ridge",
        notes=notes,
        notes_status=notes_status,
    )
    session.add(run)
    session.commit()
    return dataset, experiment, run


def test_an_approved_note_is_indexed(db_session, fake_voyage):
    _, _, run = _seed_run(db_session, notes="Ridge beat the baseline.", notes_status="approved")
    report = embeddings.backfill(db_session, client=fake_voyage)
    assert report.indexed == 1
    rows = _chunks(db_session, "note", run.id)
    assert len(rows) == 1
    assert rows[0].chunk_text == "Ridge beat the baseline."
    assert rows[0].status == "approved"
    assert rows[0].chunk_index == 0


def test_a_draft_note_is_not_indexed(db_session, fake_voyage):
    """D28: drafts in the index make Phase 4's precision a measurement of
    unreviewed output against itself, and the numbers look entirely normal."""
    _, _, run = _seed_run(db_session, notes="Not reviewed yet.", notes_status="draft")
    report = embeddings.backfill(db_session, client=fake_voyage)
    assert report.indexed == 0
    assert _chunks(db_session, "note", run.id) == []


def test_an_approved_but_empty_note_is_not_indexed(db_session, fake_voyage):
    _, _, run = _seed_run(db_session, notes="   ", notes_status="approved")
    embeddings.backfill(db_session, client=fake_voyage)
    assert _chunks(db_session, "note", run.id) == []


def test_a_second_run_is_a_no_op(db_session, fake_voyage):
    _, _, run = _seed_run(db_session, notes="Ridge beat the baseline.", notes_status="approved")
    embeddings.backfill(db_session, client=fake_voyage)
    report = embeddings.backfill(db_session, client=fake_voyage)
    assert report.unchanged == 1
    assert report.indexed == 0
    assert report.reindexed == 0
    assert len(_chunks(db_session, "note", run.id)) == 1


def test_a_second_run_does_not_re_embed(db_session, fake_voyage):
    """The no-op has to be free, not merely idempotent. Re-embedding every
    approved document on every run is a bill and a rate limit, and the row count
    stays right either way — so nothing about it looks wrong."""
    _seed_run(db_session, notes="Ridge beat the baseline.", notes_status="approved")
    embeddings.backfill(db_session, client=fake_voyage)
    calls_after_first = len(fake_voyage.calls)
    embeddings.backfill(db_session, client=fake_voyage)
    assert len(fake_voyage.calls) == calls_after_first


def test_edited_text_is_reindexed_and_leaves_no_orphan_chunks(db_session, fake_voyage):
    """Delete-then-insert, never upsert: text edited from four chunks down to one
    would otherwise leave chunk_index 1..3 behind, still ranking."""
    long_text = "The residual spread widens in the upper quartile. " * 90
    _, _, run = _seed_run(db_session, notes=long_text, notes_status="approved")
    embeddings.backfill(db_session, client=fake_voyage)
    assert len(_chunks(db_session, "note", run.id)) > 1

    run.notes = "Short after edit."
    db_session.commit()
    report = embeddings.backfill(db_session, client=fake_voyage)

    assert report.reindexed == 1
    rows = _chunks(db_session, "note", run.id)
    assert len(rows) == 1
    assert rows[0].chunk_text == "Short after edit."


def test_un_approving_a_note_reaps_its_chunks(db_session, fake_voyage):
    """THE test. An append-only backfill passes every other test in this file and
    leaves rejected text in the index carrying status='approved'."""
    _, _, run = _seed_run(db_session, notes="Ridge beat the baseline.", notes_status="approved")
    embeddings.backfill(db_session, client=fake_voyage)
    assert _chunks(db_session, "note", run.id) != []

    run.notes_status = "rejected"
    db_session.commit()
    report = embeddings.backfill(db_session, client=fake_voyage)

    assert report.reaped == 1
    assert _chunks(db_session, "note", run.id) == []


def test_emptying_an_approved_note_reaps_its_chunks(db_session, fake_voyage):
    """The other way text stops being approved: the row keeps its status and
    loses its content. Reaping only on notes_status would leave the old text
    indexed and reachable after the reviewer deleted it."""
    _, _, run = _seed_run(db_session, notes="Ridge beat the baseline.", notes_status="approved")
    embeddings.backfill(db_session, client=fake_voyage)

    run.notes = ""
    db_session.commit()
    report = embeddings.backfill(db_session, client=fake_voyage)

    assert report.reaped == 1
    assert _chunks(db_session, "note", run.id) == []


def test_an_approved_eda_finding_is_keyed_to_its_dataset(db_session, fake_voyage):
    """D30: eda chunks key on datasets.id, not on any run."""
    dataset, _, _ = _seed_run(db_session, notes="", notes_status="draft")
    db_session.add(
        Finding(
            source_type="eda",
            source_id=dataset.id,
            text="Revenue is right-skewed.",
            original_text="Revenue is right-skewed.",
            status="approved",
        )
    )
    db_session.commit()

    embeddings.backfill(db_session, client=fake_voyage)
    rows = _chunks(db_session, "eda", dataset.id)
    assert len(rows) == 1
    assert rows[0].chunk_text == "Revenue is right-skewed."


def test_an_approved_diagnostic_finding_is_keyed_to_its_run(db_session, fake_voyage):
    """D37: a diagnostic is scored against one trained run, not the investigation."""
    _, _, run = _seed_run(db_session, notes="", notes_status="draft")
    db_session.add(
        Finding(
            source_type="diagnostic",
            source_id=run.id,
            text="Residuals fan out above the median.",
            original_text="Residuals fan out above the median.",
            status="approved",
        )
    )
    db_session.commit()

    embeddings.backfill(db_session, client=fake_voyage)
    assert len(_chunks(db_session, "diagnostic", run.id)) == 1


def test_a_draft_finding_is_not_indexed(db_session, fake_voyage):
    """The finding half of D28. Run notes and findings are separate tables with
    separate review states, so approving one says nothing about the other."""
    dataset, _, _ = _seed_run(db_session, notes="", notes_status="draft")
    db_session.add(
        Finding(
            source_type="eda",
            source_id=dataset.id,
            text="Not reviewed yet.",
            original_text="Not reviewed yet.",
            status="draft",
        )
    )
    db_session.commit()

    report = embeddings.backfill(db_session, client=fake_voyage)
    assert report.indexed == 0
    assert _chunks(db_session, "eda", dataset.id) == []


def test_two_approved_findings_on_one_key_are_concatenated(db_session, fake_voyage):
    """POST /datasets/{id}/eda can be run twice. Both write ("eda", dataset_id),
    and the chunk table's unique constraint does not allow two documents there —
    so all reviewed EDA text about a dataset is chunked as one document (§5.3)."""
    dataset, _, _ = _seed_run(db_session, notes="", notes_status="draft")
    for text in ("First pass observation.", "Second pass observation."):
        db_session.add(
            Finding(
                source_type="eda",
                source_id=dataset.id,
                text=text,
                original_text=text,
                status="approved",
            )
        )
    db_session.commit()

    embeddings.backfill(db_session, client=fake_voyage)
    joined = " ".join(c.chunk_text for c in _chunks(db_session, "eda", dataset.id))
    assert "First pass observation." in joined
    assert "Second pass observation." in joined


def test_concatenation_order_is_stable_across_runs(db_session, fake_voyage):
    """Two findings committed together share a created_at to the second on
    SQLite. Without a tiebreaker their join order can flip between runs, and
    every `make embed` then reindexes text nobody edited — churn that reports
    itself as `reindexed` and looks like real work."""
    dataset, _, _ = _seed_run(db_session, notes="", notes_status="draft")
    for text in ("First pass observation.", "Second pass observation."):
        db_session.add(
            Finding(
                source_type="eda",
                source_id=dataset.id,
                text=text,
                original_text=text,
                status="approved",
            )
        )
    db_session.commit()

    first = [s.text for s in embeddings.approved_sources(db_session)]
    second = [s.text for s in embeddings.approved_sources(db_session)]
    assert first == second

    embeddings.backfill(db_session, client=fake_voyage)
    report = embeddings.backfill(db_session, client=fake_voyage)
    assert report.reindexed == 0
    assert report.unchanged == 1


def test_a_note_and_a_diagnostic_on_the_same_run_do_not_collide(db_session, fake_voyage):
    """Both key on runs.id; only source_type separates them."""
    _, _, run = _seed_run(db_session, notes="The note.", notes_status="approved")
    db_session.add(
        Finding(
            source_type="diagnostic",
            source_id=run.id,
            text="The diagnostic.",
            original_text="The diagnostic.",
            status="approved",
        )
    )
    db_session.commit()

    embeddings.backfill(db_session, client=fake_voyage)
    assert _chunks(db_session, "note", run.id)[0].chunk_text == "The note."
    assert _chunks(db_session, "diagnostic", run.id)[0].chunk_text == "The diagnostic."


def test_reaping_one_key_leaves_the_others_alone(db_session, fake_voyage):
    """Deletion is by source. A reap that over-reached would empty the index on
    the first rejection and report a plausible-looking `reaped` count."""
    _, _, kept = _seed_run(db_session, notes="Kept.", notes_status="approved")
    _, _, dropped = _seed_run(db_session, notes="Dropped.", notes_status="approved")
    embeddings.backfill(db_session, client=fake_voyage)

    dropped.notes_status = "rejected"
    db_session.commit()
    report = embeddings.backfill(db_session, client=fake_voyage)

    assert report.reaped == 1
    assert report.unchanged == 1
    assert _chunks(db_session, "note", dropped.id) == []
    assert _chunks(db_session, "note", kept.id)[0].chunk_text == "Kept."


def test_indexing_uses_the_document_input_type(db_session, fake_voyage):
    _seed_run(db_session, notes="Ridge beat the baseline.", notes_status="approved")
    embeddings.backfill(db_session, client=fake_voyage)
    assert fake_voyage.calls
    assert all(call["input_type"] == "document" for call in fake_voyage.calls)


def test_a_failing_source_is_named_and_rolls_the_whole_run_back(db_session, fake_voyage, caplog):
    """One transaction per run, so a bad source loses every key before it.

    That is the right atomicity — a half-reconciled index is worse than an
    unchanged one — but it makes the failing key the only thing the operator
    needs and the one thing a provider traceback does not contain.
    """
    _, _, good = _seed_run(db_session, notes="A note worth indexing.", notes_status="approved")
    _, _, bad = _seed_run(db_session, notes="The one that blows up.", notes_status="approved")

    class Exploding:
        def __init__(self, inner):
            self.inner = inner

        def embed(self, texts, **kwargs):
            if any("blows up" in t for t in texts):
                raise RuntimeError("provider said no")
            return self.inner.embed(texts, **kwargs)

    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError):
        embeddings.backfill(db_session, client=Exploding(fake_voyage))

    db_session.rollback()
    assert list(db_session.execute(select(ExperimentNoteChunk)).scalars()) == []
    assert bad.id in caplog.text
    assert good.id not in caplog.text
