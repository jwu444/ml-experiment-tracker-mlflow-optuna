"""The pgvector half of retrieval, against a real Postgres (3.7).

Skipped unless POSTGRES_TEST_URL is set. Locally:

    make db-up
    POSTGRES_TEST_URL=postgresql+psycopg2://wavepoint:wavepoint@localhost:5433/wavepoint \
      poetry run pytest -m postgres -v

Every vector below is HAND-BUILT at a known angle. Random vectors in 512
dimensions are near-orthogonal with overwhelming probability, so a random-vector
test passes under a wrong distance operator about as often as under the right
one -- and then fails intermittently for reasons nobody can reproduce.
"""

import math
import os

import pytest
from app import retrieval
from app.models import EMBEDDING_DIM, Base, Dataset, Experiment, ExperimentNoteChunk, Run
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.postgres

POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL", "")


def _unit(angle_degrees: float) -> list[float]:
    """A unit vector in the plane spanned by the first two axes, at a known
    angle from axis 0. Cosine distance to `_unit(0)` is exactly
    1 - cos(angle), so every assertion below is arithmetic rather than luck."""
    radians = math.radians(angle_degrees)
    vector = [0.0] * EMBEDDING_DIM
    vector[0] = math.cos(radians)
    vector[1] = math.sin(radians)
    return vector


@pytest.fixture(scope="module")
def pg_engine():
    if not POSTGRES_TEST_URL:
        pytest.skip("POSTGRES_TEST_URL is not set")
    engine = create_engine(POSTGRES_TEST_URL, future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS app"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def pg_session(pg_engine):
    """A session on a transaction that is always rolled back, so the tests leave
    the developer's dev database exactly as they found it.

    The chunk table is emptied inside that transaction. Several tests below call
    `_rank_chunks` with `keys=None` -- deliberately unrestricted, since that is
    the "search the whole index" path -- and assert on the whole ranked list. On
    the CI service container the index is empty and that holds; on a dev database
    it is not, and since D45 it never is again: `make embed` leaves ~50 approved
    chunks there, whose vectors sit at arbitrary angles to the fixtures'. They
    interleave, and the LIMIT then pushes the seeded rows off the end entirely,
    so the failure reads as a wrong operator or a wrong ORDER BY rather than as
    pre-existing data. The DELETE is undone by the same rollback as everything
    else, so the dev index survives the run."""
    connection = pg_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, expire_on_commit=False)()
    session.execute(text("DELETE FROM app.experiment_note_chunks"))
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _seed(session, *, model_type="ridge"):
    dataset = Dataset(
        name="d.csv",
        data_csv="a,b\n1,2\n",
        content_hash=f"h-{model_type}",
        n_rows=1,
        n_cols=2,
        # NOT NULL with no default -- omitting it fails at flush, and only on
        # Postgres, which is the one place these tests run.
        profile_json={},
    )
    session.add(dataset)
    session.flush()
    experiment = Experiment(
        name=f"exp-{model_type}",
        dataset_id=dataset.id,
        target_column="b",
        task_type="regression",
        primary_metric="rmse",
    )
    session.add(experiment)
    session.flush()
    run = Run(
        mlflow_run_id=f"mlf-{model_type}",
        experiment_id=experiment.id,
        model_type=model_type,
        notes="n",
        notes_status="approved",
    )
    session.add(run)
    session.flush()
    return dataset, experiment, run


def _chunk(session, source_type, source_id, index, textval, vector, status="approved"):
    row = ExperimentNoteChunk(
        source_type=source_type,
        source_id=source_id,
        chunk_text=textval,
        chunk_index=index,
        status=status,
        embedding=vector,
    )
    session.add(row)
    session.flush()
    return row


def test_the_vector_column_round_trips_at_512_dimensions(pg_session):
    _, _, run = _seed(pg_session)
    row = _chunk(pg_session, "note", run.id, 0, "t", _unit(0))
    pg_session.expire(row)
    assert len(row.embedding) == EMBEDDING_DIM


def test_chunks_come_back_nearest_first(pg_session):
    """The operator and the ORDER BY direction, together. `<->` instead of `<=>`
    or a DESC here returns the LEAST relevant text, confidently."""
    _, _, run = _seed(pg_session)
    near = _chunk(pg_session, "note", run.id, 0, "near", _unit(10))
    mid = _chunk(pg_session, "note", run.id, 1, "mid", _unit(60))
    far = _chunk(pg_session, "note", run.id, 2, "far", _unit(150))

    ranked = retrieval._rank_chunks(pg_session, _unit(0), None, 10)
    assert [chunk.chunk_text for chunk, _ in ranked] == ["near", "mid", "far"]
    assert [near.id, mid.id, far.id]  # rows were really written


def test_the_distance_is_cosine_and_matches_the_known_angle(pg_session):
    """1 - cos(60 degrees) = 0.5. A euclidean operator on unit vectors gives
    1.0 here, so this catches `<->` even when the ordering happens to agree."""
    _, _, run = _seed(pg_session)
    _chunk(pg_session, "note", run.id, 0, "sixty", _unit(60))

    ranked = retrieval._rank_chunks(pg_session, _unit(0), None, 10)
    assert ranked[0][1] == pytest.approx(0.5, abs=1e-6)


def test_scores_are_one_minus_distance(pg_session, monkeypatch, fake_voyage):
    """End to end through search_runs, with the real operator underneath."""
    _, _, run = _seed(pg_session)
    _chunk(pg_session, "note", run.id, 0, "sixty", _unit(60))
    monkeypatch.setattr(
        retrieval, "embed_texts", lambda texts, *, input_type, client=None: [_unit(0)]
    )

    hits, _ = retrieval.search_runs(pg_session, "q", k=5, client=fake_voyage)
    assert hits[0].score == pytest.approx(0.5, abs=1e-6)


def test_the_key_restriction_really_restricts(pg_session):
    """tuple_(source_type, source_id).in_(keys) -- a composite IN. If it silently
    matched everything, every filtered search would quietly return the whole
    corpus, and Task 7's monkeypatched tests could never see it."""
    _, _, ridge = _seed(pg_session, model_type="ridge")
    _, _, forest = _seed(pg_session, model_type="random_forest")
    _chunk(pg_session, "note", ridge.id, 0, "ridge note", _unit(5))
    _chunk(pg_session, "note", forest.id, 0, "forest note", _unit(1))

    ranked = retrieval._rank_chunks(pg_session, _unit(0), (("note", ridge.id),), 10)
    assert [chunk.chunk_text for chunk, _ in ranked] == ["ridge note"]


def test_a_key_restriction_does_not_leak_across_source_types(pg_session):
    """Both a note and a diagnostic key on runs.id; only source_type separates
    them. A restriction on source_id alone would return both."""
    _, _, run = _seed(pg_session)
    _chunk(pg_session, "note", run.id, 0, "the note", _unit(5))
    _chunk(pg_session, "diagnostic", run.id, 0, "the diagnostic", _unit(1))

    ranked = retrieval._rank_chunks(pg_session, _unit(0), (("note", run.id),), 10)
    assert [chunk.chunk_text for chunk, _ in ranked] == ["the note"]


def test_unapproved_chunks_are_never_ranked(pg_session):
    """Second line of defence behind the backfill's reaping (5.3). D28 is the
    claim that only reviewed text is retrievable, and it must hold even if a
    stale row survives."""
    _, _, run = _seed(pg_session)
    _chunk(pg_session, "note", run.id, 0, "draft text", _unit(1), status="draft")
    _chunk(pg_session, "note", run.id, 1, "approved text", _unit(80))

    ranked = retrieval._rank_chunks(pg_session, _unit(0), None, 10)
    assert [chunk.chunk_text for chunk, _ in ranked] == ["approved text"]


def test_the_limit_is_applied_in_the_database(pg_session):
    """Over-fetch is k * chunk_overfetch, not the whole table."""
    _, _, run = _seed(pg_session)
    for i in range(10):
        _chunk(pg_session, "note", run.id, i, f"chunk {i}", _unit(i))

    assert len(retrieval._rank_chunks(pg_session, _unit(0), None, 3)) == 3
