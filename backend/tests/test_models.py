import pytest
from app.models import (
    EMBEDDING_DIM,
    Analysis,
    Base,
    Chat,
    ChatDataset,
    ChatMessage,
    Dataset,
    DatasetColumn,
    Experiment,
    ExperimentNoteChunk,
    Run,
)
from sqlalchemy import Numeric, create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker


def _session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}", future=True).execution_options(
        schema_translate_map={"app": None}
    )

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_dataset_persists_profile_and_csv(tmp_path):
    session = _session(tmp_path)
    dataset = Dataset(
        name="sales.csv",
        n_rows=3,
        n_cols=2,
        profile_json={"n_rows": 3, "columns": ["a", "b"]},
        data_csv="a,b\n1,2\n3,4\n5,6\n",
        content_hash="a" * 64,
    )
    session.add(dataset)
    session.commit()

    loaded = session.scalar(select(Dataset).where(Dataset.name == "sales.csv"))
    assert loaded is not None
    assert loaded.profile_json["n_rows"] == 3
    assert loaded.data_csv == "a,b\n1,2\n3,4\n5,6\n"


def test_chat_message_defaults(tmp_path):
    session = _session(tmp_path)
    dataset = Dataset(
        name="d.csv", n_rows=1, n_cols=1, profile_json={}, data_csv="x\n1\n", content_hash="b" * 64
    )
    session.add(dataset)
    session.flush()
    chat = Chat()
    session.add(chat)
    session.flush()
    session.add(ChatDataset(chat_id=chat.id, dataset_id=dataset.id, ordinal_position=0))
    msg = ChatMessage(chat_id=chat.id, role="user", content="hello")
    session.add(msg)
    session.commit()

    assert msg.tool_calls == []
    assert msg.tokens_in == 0
    assert msg.cost_usd == 0.0
    assert msg.latency_ms == 0


def test_analysis_uses_message_id_and_result_stats() -> None:
    cols = {c.name for c in Analysis.__table__.columns}
    assert "message_id" in cols
    assert "chat_message_id" not in cols
    assert "result_stats" in cols
    assert Analysis.__table__.c.result_stats.nullable is True


def test_dataset_columns_ordinal_and_unique() -> None:
    cols = {c.name for c in DatasetColumn.__table__.columns}
    assert "ordinal_position" in cols
    assert DatasetColumn.__table__.c.ordinal_position.nullable is False
    unique_cols = {
        tuple(sorted(col.name for col in c.columns))
        for c in DatasetColumn.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    }
    assert ("dataset_id", "name") in unique_cols


def test_chat_datasets_ordinal_and_unique() -> None:
    cols = {c.name for c in ChatDataset.__table__.columns}
    assert "ordinal_position" in cols
    assert ChatDataset.__table__.c.ordinal_position.nullable is False
    unique_cols = {
        tuple(sorted(col.name for col in c.columns))
        for c in ChatDataset.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    }
    assert ("chat_id", "dataset_id") in unique_cols


def test_chat_no_longer_has_dataset_id() -> None:
    assert "dataset_id" not in {c.name for c in Chat.__table__.columns}


def test_cost_usd_is_numeric() -> None:
    assert isinstance(ChatMessage.__table__.c.cost_usd.type, Numeric)


def test_chat_message_has_loop_metadata_columns(tmp_path) -> None:
    session = _session(tmp_path)
    chat = Chat()
    session.add(chat)
    session.flush()
    msg = ChatMessage(chat_id=chat.id, role="assistant", content="ok", pass_count=3, judge_score=85)
    session.add(msg)
    session.flush()

    fetched = session.get(ChatMessage, msg.id)
    assert fetched.pass_count == 3
    assert fetched.judge_score == 85


def test_fk_columns_are_indexed() -> None:
    assert DatasetColumn.__table__.c.dataset_id.index is True
    assert ChatMessage.__table__.c.chat_id.index is True
    assert Analysis.__table__.c.message_id.index is True
    assert ChatDataset.__table__.c.chat_id.index is True
    assert ChatDataset.__table__.c.dataset_id.index is True


def test_content_hash_unique_constraint(tmp_path):
    session = _session(tmp_path)
    session.add(
        Dataset(
            name="a.csv",
            n_rows=1,
            n_cols=1,
            profile_json={},
            data_csv="x\n1\n",
            content_hash="h" * 64,
        )
    )
    session.commit()
    session.add(
        Dataset(
            name="b.csv",
            n_rows=1,
            n_cols=1,
            profile_json={},
            data_csv="y\n2\n",
            content_hash="h" * 64,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_run_requires_an_experiment(tmp_path):
    # D34/D37: dataset_id/dataset_version/task_type moved onto the parent
    # Experiment and were dropped from Run entirely once every row had a
    # (now NOT NULL) experiment_id to inherit them from. This replaces
    # test_run_persists_with_nullable_dataset_fk, which asserted the exact
    # opposite of the current shape (a nullable Run.dataset_id that no longer
    # exists as a column at all).
    session = _session(tmp_path)
    dataset = Dataset(
        name="gpus.csv",
        n_rows=2,
        n_cols=2,
        profile_json={},
        data_csv="a,b\n1,2\n3,4\n",
        content_hash="c" * 64,
    )
    session.add(dataset)
    session.flush()

    experiment = Experiment(
        name="gpu-price",
        dataset_id=dataset.id,
        target_column="price",
        task_type="regression",
    )
    session.add(experiment)
    session.flush()

    run = Run(
        mlflow_run_id="run-linked",
        experiment_id=experiment.id,
        model_type="ridge",
        notes="baseline on the GPU price table",
    )
    session.add(run)
    session.commit()

    assert session.get(Run, run.id).experiment_id == experiment.id
    cols = {c.name for c in Run.__table__.columns}
    assert {"dataset_id", "dataset_version", "task_type"} & cols == set()
    assert Run.__table__.c.experiment_id.nullable is False

    orphan = Run(mlflow_run_id="run-orphan", model_type="ridge")
    session.add(orphan)
    with pytest.raises(IntegrityError):
        session.commit()


def test_run_has_no_owner_column() -> None:
    # D2: single-tenant, no auth. No user/owner FK, ever.
    cols = {c.name for c in Run.__table__.columns}
    assert "user_id" not in cols
    assert "owner_id" not in cols


def test_note_chunk_roundtrips_an_embedding(tmp_path):
    session = _session(tmp_path)
    experiment = Experiment(name="exp", target_column="t", task_type="regression")
    session.add(experiment)
    session.flush()
    run = Run(mlflow_run_id="run-1", experiment_id=experiment.id, model_type="ridge", notes="n")
    session.add(run)
    session.flush()

    vector = [0.5] * EMBEDDING_DIM
    session.add(
        ExperimentNoteChunk(
            source_type="note",
            source_id=run.id,
            chunk_text="tried a wider alpha range",
            chunk_index=0,
            embedding=vector,
        )
    )
    session.commit()

    loaded = session.scalar(select(ExperimentNoteChunk))
    assert loaded is not None
    assert list(loaded.embedding) == vector
    assert loaded.chunk_index == 0
    assert ExperimentNoteChunk.__table__.c.source_type.index is True
    assert ExperimentNoteChunk.__table__.c.source_id.index is True


def test_note_chunk_unique_per_source_and_index() -> None:
    unique_cols = {
        tuple(sorted(col.name for col in c.columns))
        for c in ExperimentNoteChunk.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    }
    assert ("chunk_index", "source_id", "source_type") in unique_cols


def test_embedding_column_compiles_on_both_dialects() -> None:
    # The suite runs on SQLite; production runs on Postgres. One column
    # definition has to serve both.
    from sqlalchemy.dialects import postgresql, sqlite

    column = ExperimentNoteChunk.__table__.c.embedding
    assert "VECTOR(512)" in str(column.type.compile(dialect=postgresql.dialect()))
    assert "JSON" in str(column.type.compile(dialect=sqlite.dialect()))
