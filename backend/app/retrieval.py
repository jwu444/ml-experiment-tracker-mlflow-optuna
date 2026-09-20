"""Two-stage retrieval over reviewed experiment history (3.4).

Stage 1 resolves the structured filters relationally; stage 2 runs a similarity
search restricted to what stage 1 admitted, then groups the matching chunks back
into the SOURCES they came from.

The order matters and is D15/D31: "ridge runs on the revenue panel" is a WHERE
clause, not something to hope the embedding encoded. A pure-vector version
returns plausible text about the wrong model and reads exactly like a right
answer.
"""

from dataclasses import astuple, dataclass
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app import experiment_log
from app.config import settings
from app.embeddings import embed_texts
from app.models import Experiment, ExperimentNoteChunk, Run
from app.tracing import span


@dataclass(frozen=True)
class Filters:
    """The agent's structured filters. Every field is optional; all supplied
    fields are ANDed."""

    model_type: str | None = None
    dataset_id: str | None = None
    task_type: str | None = None
    experiment_id: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class Candidates:
    """What stage 1 admits.

    `keys is None` means UNRESTRICTED — no filters were given, so stage 2
    searches the whole index. `keys == ()` means filters were given and matched
    nothing. Collapsing the two turns "no ridge runs exist" into "here is
    everything", which the agent then summarises with total confidence.
    """

    keys: tuple[tuple[str, str], ...] | None
    run_ids: tuple[str, ...]
    warnings: tuple[str, ...] = ()


def candidate_runs(session: Session, filters: Filters) -> Candidates:
    """Resolve `filters` against the relational store.

    Each matching run expands to three chunk keys (D30):
      ("note", run.id), ("diagnostic", run.id), ("eda", experiment.dataset_id)
    The EDA key is why "what do we know about this data" finds the dataset
    write-up and not only run notes.
    """
    # Attributes are counts and flags only (3.1): a filter VALUE is the model's
    # own query text and an exporter is a place data leaves the process from.
    supplied = (
        filters.model_type,
        filters.dataset_id,
        filters.task_type,
        filters.experiment_id,
        filters.status,
    )
    if not any(supplied):
        return Candidates(keys=None, run_ids=(), warnings=())

    # dataset_id and task_type live on the PARENT (D37), model_type and
    # experiment_id on the run itself.
    #
    # Three columns, not two whole entities: `Run.notes` is TEXT and nothing here
    # reads it, so selecting the ORM objects would drag every approved write-up
    # in the candidate set across the wire to compute a set of keys.
    stmt = select(Run.id, Run.mlflow_run_id, Experiment.dataset_id).join(
        Experiment, Run.experiment_id == Experiment.id
    )
    if filters.model_type:
        stmt = stmt.where(Run.model_type == filters.model_type)
    if filters.experiment_id:
        stmt = stmt.where(Run.experiment_id == filters.experiment_id)
    if filters.dataset_id:
        stmt = stmt.where(Experiment.dataset_id == filters.dataset_id)
    if filters.task_type:
        stmt = stmt.where(Experiment.task_type == filters.task_type)

    rows = list(session.execute(stmt).all())
    warnings: list[str] = []

    if filters.status:
        # app.runs has no status column — params, metrics and status live in
        # MLflow (D4), so this is an intersection with the tracking store.
        #
        # fetch_runs, not search_runs: search_runs asks for the WHOLE store
        # capped at SEARCH_MAX_RESULTS and truncates *before* applying the
        # status filter, so past that cap this filter would silently return
        # fewer candidates than exist — the exact silent-narrowing failure the
        # keys=None/() distinction below exists to prevent. fetch_runs scopes
        # the query to `attributes.run_id IN (...)` over the rows the relational
        # stage already admitted, in one call.
        # No `if run_id` guard: runs.mlflow_run_id is NOT NULL, so every row
        # here has one and a filter would be dead code implying otherwise.
        try:
            allowed = {
                run_id
                for run_id, data in experiment_log.fetch_runs(
                    [run_id for _, run_id, _ in rows]
                ).items()
                if data.status == filters.status
            }
        except Exception as exc:  # noqa: BLE001
            # Degrade, never 503. Notes and findings are in Postgres and remain
            # answerable; failing the whole request because an OPTIONAL filter's
            # backing store is down trades a partial answer for no answer. The
            # warning reaches the response so the caller knows the filter did
            # not apply, rather than silently trusting a broader result.
            warnings.append(
                f"status filter {filters.status!r} was not applied: "
                f"the MLflow tracking store is unavailable ({exc})"
            )
        else:
            rows = [row for row in rows if row[1] in allowed]

    keys: list[tuple[str, str]] = []
    run_ids: list[str] = []
    for run_id, _, dataset_id in rows:
        run_ids.append(run_id)
        keys.append(("note", run_id))
        keys.append(("diagnostic", run_id))
        if dataset_id:
            keys.append(("eda", dataset_id))

    # Sorted and de-duplicated: several runs in one experiment share an EDA key,
    # and a stable order keeps the generated IN list cacheable and diffable.
    return Candidates(
        keys=tuple(sorted(set(keys))),
        run_ids=tuple(dict.fromkeys(run_ids)),
        warnings=tuple(warnings),
    )


class TrackingStoreUnavailable(RuntimeError):
    """MLflow could not be reached for a call that has no partial answer.

    Distinct from the status-filter degradation in `candidate_runs`: there, the
    store backs one optional filter and the rest of the answer survives without
    it. Here the params and metrics ARE the answer.
    """


@dataclass(frozen=True)
class Hit:
    """One retrieved SOURCE (not one chunk), with the ids the UI deep-links on."""

    source_type: str  # "note" | "eda" | "diagnostic"
    source_id: str
    run_id: str | None  # None for an eda hit — it is about a dataset
    experiment_id: str | None
    dataset_id: str | None
    snippet: str  # the single best-matching chunk's text
    score: float  # 1.0 - cosine distance; higher is nearer


@dataclass(frozen=True)
class RunDetail:
    run_id: str
    mlflow_run_id: str
    experiment_id: str
    experiment_name: str
    experiment_objective: str
    model_type: str
    status: str
    params: dict[str, str]
    metrics: dict[str, float]
    cv_std: float | None
    notes: str
    notes_status: str


def _rank_chunks(
    session: Session, vector: list[float], keys: tuple[tuple[str, str], ...] | None, limit: int
) -> list[tuple[ExperimentNoteChunk, float]]:
    """Nearest chunks by cosine distance. THE ONLY function that emits `<=>`.

    Isolated deliberately: `<=>` is a pgvector operator with no SQLite
    equivalent, and the whole test suite runs on SQLite. Tests of grouping and
    scoring monkeypatch this seam; its real SQL is covered against Postgres in
    test_retrieval_postgres.py.
    """
    distance = ExperimentNoteChunk.embedding.cosine_distance(vector)
    stmt = select(ExperimentNoteChunk, distance.label("distance"))
    # status is denormalised onto the chunk row, but the backfill is what keeps
    # it honest (3.3b) — this predicate is a second line, not the first.
    stmt = stmt.where(ExperimentNoteChunk.status == "approved")
    if keys is not None:
        stmt = stmt.where(
            tuple_(ExperimentNoteChunk.source_type, ExperimentNoteChunk.source_id).in_(keys)
        )
    stmt = stmt.order_by(distance).limit(limit)
    return [(row[0], float(row[1])) for row in session.execute(stmt).all()]


def _resolve_ids(
    session: Session, keys: set[tuple[str, str]]
) -> dict[tuple[str, str], tuple[str | None, str | None, str | None]]:
    """(run_id, experiment_id, dataset_id) per chunk key, in one query.

    Resolved here, where the join is already open, rather than per hit in the
    route — the route version is an N+1 that only shows up under a full k.
    """
    run_ids = [source_id for source_type, source_id in keys if source_type != "eda"]

    by_run: dict[str, tuple[str, str | None]] = {}
    if run_ids:
        rows = session.execute(
            select(Run.id, Experiment.id, Experiment.dataset_id)
            .join(Experiment, Run.experiment_id == Experiment.id)
            .where(Run.id.in_(run_ids))
        ).all()
        by_run = {row[0]: (row[1], row[2]) for row in rows}

    resolved: dict[tuple[str, str], tuple[str | None, str | None, str | None]] = {}
    for key in keys:
        source_type, source_id = key
        if source_type == "eda":
            # An eda chunk keys on datasets.id (D30), so the id IS the answer —
            # there is no run and no experiment to attribute it to.
            resolved[key] = (None, None, source_id)
        else:
            experiment_id, dataset_id = by_run.get(source_id, (None, None))
            resolved[key] = (source_id, experiment_id, dataset_id)
    return resolved


def search_runs(
    session: Session,
    query: str,
    *,
    filters: Filters | None = None,
    k: int | None = None,
    client: Any | None = None,
) -> tuple[list[Hit], list[str]]:
    """Two-stage retrieval. Returns (hits, warnings); `k` counts SOURCES."""
    filters = filters or Filters()
    k = k or settings.retrieval_top_k

    # Attributes carry counts, never the query, the filter values or the text
    # retrieved (3.1). `filters` is a COUNT of how many were supplied.
    with span(
        "retrieval.search",
        k=k,
        overfetch=settings.chunk_overfetch,
        filters=sum(1 for value in astuple(filters) if value),
    ) as search_span:
        candidates = candidate_runs(session, filters)
        warnings = list(candidates.warnings)
        # Both branches are recorded: `unrestricted` is the keys=None/()
        # distinction, and reading `candidate_keys=0` without it cannot tell
        # "no filters, search everything" from "filters matched nothing".
        search_span.set_attribute("unrestricted", candidates.keys is None)
        search_span.set_attribute("candidate_keys", len(candidates.keys or ()))
        search_span.set_attribute("warnings", len(warnings))
        if candidates.keys is not None and not candidates.keys:
            # Stage 1 excluded everything. Running the similarity search anyway
            # would search the whole corpus and silently ignore the filter.
            search_span.set_attribute("chunks", 0)
            search_span.set_attribute("sources", 0)
            return [], warnings

        with span("retrieval.embed_query", chars=len(query)):
            vector = embed_texts([query], input_type="query", client=client)[0]
        with span("retrieval.rank_chunks", limit=k * settings.chunk_overfetch) as rank_span:
            ranked = _rank_chunks(session, vector, candidates.keys, k * settings.chunk_overfetch)
            rank_span.set_attribute("chunks", len(ranked))

        # Group chunks into sources, scoring each by its SINGLE BEST chunk.
        # Averaging would punish a long, thorough write-up for its own breadth —
        # which is the document most worth surfacing.
        best: dict[tuple[str, str], tuple[ExperimentNoteChunk, float]] = {}
        for chunk, distance in ranked:
            key = (chunk.source_type, chunk.source_id)
            if key not in best or distance < best[key][1]:
                best[key] = (chunk, distance)

        ordered = sorted(best.items(), key=lambda item: item[1][1])[:k]
        ids = _resolve_ids(session, {key for key, _ in ordered})

        hits = []
        for key, (chunk, distance) in ordered:
            run_id, experiment_id, dataset_id = ids[key]
            hits.append(
                Hit(
                    source_type=key[0],
                    source_id=key[1],
                    run_id=run_id,
                    experiment_id=experiment_id,
                    dataset_id=dataset_id,
                    snippet=chunk.chunk_text,
                    score=1.0 - distance,
                )
            )
        search_span.set_attribute("chunks", len(ranked))
        search_span.set_attribute("sources", len(hits))
        return hits, warnings


def get_run_detail(session: Session, run_id: str) -> RunDetail:
    """One run's full record: our row, its parent investigation, and MLflow's
    params and metrics."""
    # run_id is an id, which span attributes may carry; the params, metrics and
    # notes this returns are payloads, which they may not.
    with span("retrieval.run_detail", run_id=run_id):
        row = session.execute(
            select(Run, Experiment)
            .join(Experiment, Run.experiment_id == Experiment.id)
            .where(Run.id == run_id)
        ).first()
    if row is None:
        raise KeyError(run_id)
    run, experiment = row

    try:
        data = experiment_log.fetch_runs([run.mlflow_run_id]).get(run.mlflow_run_id)
    except Exception as exc:  # noqa: BLE001
        raise TrackingStoreUnavailable(str(exc)) from exc

    metrics = dict(data.metrics) if data else {}
    return RunDetail(
        run_id=run.id,
        mlflow_run_id=run.mlflow_run_id,
        experiment_id=experiment.id,
        experiment_name=experiment.name,
        experiment_objective=experiment.objective,
        model_type=run.model_type,
        status=data.status if data else "UNKNOWN",
        params=dict(data.params) if data else {},
        metrics=metrics,
        # None, never 0.0. "unquantified" is a thing the agent can say; a
        # fabricated zero band makes every difference look significant.
        cv_std=metrics.get("cv_std"),
        notes=run.notes,
        notes_status=run.notes_status,
    )
