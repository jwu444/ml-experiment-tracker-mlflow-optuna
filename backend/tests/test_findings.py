import pytest
from app import findings
from app.models import Dataset, Experiment, Finding, Run
from sqlalchemy import select


def _dataset(db_session) -> Dataset:
    row = Dataset(
        name="d.csv",
        data_csv="a,b\n1,2\n",
        profile_json={},
        content_hash="h1",
        n_rows=1,
        n_cols=2,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _run(db_session) -> Run:
    # experiment_id is now required (D37) and task_type moved to the parent
    # Experiment (D34) — a Run can no longer carry it directly.
    experiment = Experiment(name="exp", target_column="t", task_type="regression")
    db_session.add(experiment)
    db_session.commit()
    row = Run(mlflow_run_id="run-1", experiment_id=experiment.id, model_type="ridge")
    db_session.add(row)
    db_session.flush()
    return row


def test_create_eda_finding_freezes_original_text(db_session) -> None:
    dataset = _dataset(db_session)
    row = findings.create_finding(db_session, "eda", dataset.id, "revenue is right-skewed")
    assert row.status == "draft"
    assert row.text == "revenue is right-skewed"
    assert row.original_text == "revenue is right-skewed"


def test_create_diagnostic_finding_validates_against_runs(db_session) -> None:
    run = _run(db_session)
    row = findings.create_finding(db_session, "diagnostic", run.id, "residuals drift late")
    assert row.source_type == "diagnostic"
    assert row.source_id == run.id


def test_create_rejects_unknown_source_type(db_session) -> None:
    with pytest.raises(findings.FindingError) as exc:
        findings.create_finding(db_session, "guess", "whatever", "text")
    assert exc.value.status_code == 422


def test_eda_source_id_must_exist_in_datasets(db_session) -> None:
    run = _run(db_session)
    # A run id is a real id — but not a dataset id. The missing FK is
    # exactly what makes this silently insertable without the check.
    with pytest.raises(findings.FindingError) as exc:
        findings.create_finding(db_session, "eda", run.id, "text")
    assert exc.value.status_code == 404


def test_diagnostic_source_id_must_exist_in_runs(db_session) -> None:
    dataset = _dataset(db_session)
    with pytest.raises(findings.FindingError) as exc:
        findings.create_finding(db_session, "diagnostic", dataset.id, "text")
    assert exc.value.status_code == 404


def test_update_text_alone_is_never_an_approval(db_session) -> None:
    dataset = _dataset(db_session)
    row = findings.create_finding(db_session, "eda", dataset.id, "draft text")
    updated = findings.update_finding(db_session, row.id, text="edited text")
    assert updated.text == "edited text"
    assert updated.status == "draft"
    assert updated.original_text == "draft text"


def test_approving_empty_text_is_422(db_session) -> None:
    dataset = _dataset(db_session)
    row = findings.create_finding(db_session, "eda", dataset.id, "   ")
    with pytest.raises(findings.FindingError) as exc:
        findings.update_finding(db_session, row.id, status="approved")
    assert exc.value.status_code == 422


def test_rejecting_empty_text_is_allowed(db_session) -> None:
    dataset = _dataset(db_session)
    row = findings.create_finding(db_session, "eda", dataset.id, "")
    updated = findings.update_finding(db_session, row.id, status="rejected")
    assert updated.status == "rejected"


def test_update_rejects_unknown_status(db_session) -> None:
    dataset = _dataset(db_session)
    row = findings.create_finding(db_session, "eda", dataset.id, "text")
    with pytest.raises(findings.FindingError) as exc:
        findings.update_finding(db_session, row.id, status="blessed")
    assert exc.value.status_code == 422


def test_update_unknown_finding_is_404(db_session) -> None:
    with pytest.raises(findings.FindingError) as exc:
        findings.update_finding(db_session, "no-such-id", text="x")
    assert exc.value.status_code == 404


def test_list_filters_by_status_and_source_type(db_session) -> None:
    dataset = _dataset(db_session)
    run = _run(db_session)
    a = findings.create_finding(db_session, "eda", dataset.id, "a")
    findings.create_finding(db_session, "diagnostic", run.id, "b")
    findings.update_finding(db_session, a.id, status="approved")

    assert [r.id for r in findings.list_findings(db_session, status="draft")] == [
        r.id for r in db_session.execute(select(Finding).where(Finding.status == "draft")).scalars()
    ]
    assert len(findings.list_findings(db_session, source_type="eda")) == 1
    assert len(findings.list_findings(db_session, status="approved")) == 1


def test_note_chunk_carries_source_type_and_status(db_session) -> None:
    """Phase 3 must be able to tell a note chunk from an EDA finding chunk
    from a diagnostic chunk without joining anything (D21)."""
    from app.models import EMBEDDING_DIM, ExperimentNoteChunk

    run = _run(db_session)
    chunk = ExperimentNoteChunk(
        source_type="note",
        source_id=run.id,
        chunk_text="ridge beat the baseline on rmse",
        chunk_index=0,
        status="approved",
        embedding=[0.0] * EMBEDDING_DIM,
    )
    db_session.add(chunk)
    db_session.flush()
    assert chunk.source_type == "note"
    assert chunk.status == "approved"


def test_note_chunk_status_defaults_to_draft(db_session) -> None:
    from app.models import EMBEDDING_DIM, ExperimentNoteChunk

    run = _run(db_session)
    chunk = ExperimentNoteChunk(
        source_type="note",
        source_id=run.id,
        chunk_text="text",
        chunk_index=0,
        embedding=[0.0] * EMBEDDING_DIM,
    )
    db_session.add(chunk)
    db_session.commit()
    db_session.refresh(chunk)
    assert chunk.status == "draft"
