import hashlib
import io
from collections.abc import Iterator

import pytest
from app import experiment_log
from app.db import get_session
from app.main import create_app
from app.models import Base, Experiment
from app.sqlite_schema import attach_app_schema
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def db_engine(tmp_path):
    # attach_app_schema mirrors app/db.py and Alembic's env.py exactly, so a
    # SQLite database any one of the three touches looks the same to the
    # others — see app/sqlite_schema.py.
    engine = attach_app_schema(create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True))
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def client(db_engine) -> Iterator[TestClient]:
    testing_session = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)

    def override_get_session() -> Iterator[Session]:
        with testing_session() as session:
            yield session

    app = create_app(init_on_startup=False)
    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db_session(db_engine) -> Iterator[Session]:
    """A session on the same SQLite file the app writes to. Serves both callers:
    route tests asserting on rows the app persisted, and module-level unit tests
    that never go through HTTP. expire_on_commit=False so objects stay readable
    after the route's own commit."""
    with sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)() as session:
        yield session


@pytest.fixture
def session(db_session: Session) -> Session:
    """Alias for db_session — named `session` (rather than reused as
    `db_session`) because test_leaderboard.py calls module-level functions
    directly and wants the generic name; it is the same fixture underneath,
    not a second database."""
    return db_session


# Shared by the /experiments route modules: a small numeric+categorical CSV, a
# temporal panel, and an MLflow store rooted in tmp_path. mlflow_store is not
# autouse — modules that need it opt in with a module-level usefixtures mark,
# so the rest of the suite keeps running with no tracking URI at all.
CSV = "memory,chipset,price\n" + "".join(
    f"{4 * (i % 6) + 4},{'abc'[i % 3]},{100 + i}\n" for i in range(40)
)

# A tiny temporal panel: `as_of` ascends, `price` ascends with it.
PANEL_CSV = "as_of,memory,price\n" + "".join(
    f"20{20 + i // 4:02d}-{3 * (i % 4) + 1:02d}-01,{4 * (i % 6) + 4},{100 + i}\n" for i in range(40)
)


@pytest.fixture
def dataset_id(client):
    resp = client.post("/datasets", files={"file": ("t.csv", io.BytesIO(CSV.encode()), "text/csv")})
    assert resp.status_code == 200
    return resp.json()["id"]


@pytest.fixture
def panel_id(client):
    resp = client.post(
        "/datasets", files={"file": ("p.csv", io.BytesIO(PANEL_CSV.encode()), "text/csv")}
    )
    assert resp.status_code == 200
    return resp.json()["id"]


@pytest.fixture
def mlflow_store(tmp_path, monkeypatch):
    monkeypatch.setattr(
        experiment_log.settings, "mlflow_tracking_uri", f"sqlite:///{tmp_path}/mlflow.db"
    )
    monkeypatch.setattr(experiment_log.settings, "mlflow_artifact_root", str(tmp_path / "art"))


@pytest.fixture
def seeded_experiment(client, dataset_id, mlflow_store, session) -> Experiment:
    """One Experiment with three trained Runs carrying distinct rmse values —
    what test_leaderboard.py needs to exercise real ranking. Goes through
    `client` (the same tmp_path-backed engine `session` reads back from)
    rather than inserting Run rows by hand, so the runs are real MLflow rows
    and not a shape that merge_runs would never actually see."""
    resp = client.post(
        "/experiments",
        json={
            "name": "leaderboard-fixture",
            "target_column": "price",
            "dataset_id": dataset_id,
            "task_type": "regression",
        },
    )
    assert resp.status_code == 201, resp.text
    experiment_id = resp.json()["id"]
    for model_type in ("ridge", "random_forest", "gradient_boosting"):
        train_resp = client.post(
            f"/experiments/{experiment_id}/train", json={"model_type": model_type}
        )
        assert train_resp.status_code == 200, train_resp.text
    experiment = session.get(Experiment, experiment_id)
    assert experiment is not None
    return experiment


@pytest.fixture
def spans(monkeypatch):
    """An in-memory span exporter wired into app.tracing.

    Patches `tracing._tracer` rather than calling `trace.set_tracer_provider`,
    because the global provider can only be set once per process — a fixture
    that set it would work in the first test that used it and silently export
    nothing in every later one.
    """
    from app import tracing
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    monkeypatch.setattr(tracing, "_tracer", lambda: tracer)
    return exporter


class FakeVoyage:
    """Stands in for `voyageai.Client`. Records every call and returns
    deterministic vectors derived from the text, so two identical texts embed
    identically and two different ones do not — enough for the reconciliation
    tests, which care about which rows exist rather than about geometry.
    Ranking assertions use hand-built vectors instead (test_retrieval_postgres)."""

    def __init__(self, width: int | None = None) -> None:
        from app.models import EMBEDDING_DIM

        self.width = width if width is not None else EMBEDDING_DIM
        self.calls: list[dict] = []

    def embed(self, texts, model=None, input_type=None, output_dimension=None):
        self.calls.append(
            {
                "texts": list(texts),
                "model": model,
                "input_type": input_type,
                "output_dimension": output_dimension,
            }
        )

        class _Resp:
            pass

        resp = _Resp()
        # Seeded on the text rather than PYTHONHASHSEED-dependent hash(), so a
        # vector is the same across processes — the backfill's "already indexed"
        # comparison would otherwise flip between runs.
        resp.embeddings = [
            [
                float(int(hashlib.sha256(f"{t}:{i}".encode()).hexdigest()[:8], 16) % 7) / 7.0
                for i in range(self.width)
            ]
            for t in texts
        ]
        return resp


@pytest.fixture
def fake_voyage():
    return FakeVoyage()
