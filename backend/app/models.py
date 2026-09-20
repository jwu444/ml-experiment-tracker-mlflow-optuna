from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        UniqueConstraint("content_hash", name="uq_datasets_content_hash"),
        {"schema": "app"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    n_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    n_cols: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    data_csv: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DatasetColumn(Base):
    __tablename__ = "dataset_columns"
    __table_args__ = (
        UniqueConstraint("dataset_id", "name", name="uq_dataset_columns_dataset_id_name"),
        {"schema": "app"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("app.datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal_position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    inferred_type: Mapped[str] = mapped_column(String, nullable=False)
    null_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Chat(Base):
    __tablename__ = "chats"
    __table_args__ = {"schema": "app"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ChatDataset(Base):
    __tablename__ = "chat_datasets"
    __table_args__ = (
        UniqueConstraint("chat_id", "dataset_id", name="uq_chat_datasets_chat_id_dataset_id"),
        {"schema": "app"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("app.chats.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("app.datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal_position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = {"schema": "app"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("app.chats.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tool_calls: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(
        Numeric(10, 6, asdecimal=False), nullable=False, default=0.0
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # LLM loop (issue #9): how many analyst passes ran and the best judge score.
    # Nullable — pre-loop rows and (rare) judge-failure turns stay NULL.
    pass_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    judge_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Per-pass loop trace (issue #9 review): {"passes": [{analyst, judge, charts,
    # stats, errors, revision_instruction}, ...]}. The system prompt is excluded
    # by design (it never leaves the backend). Nullable — pre-trace and
    # non-assistant rows stay NULL. Stores rendered chart PNGs per pass.
    trace_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = {"schema": "app"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("app.chat_messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chart_type: Mapped[str] = mapped_column(String, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_stats: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    output_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# Embedding width for `experiment_note_chunks.embedding`. The provider is chosen
# in Phase 3; this width is a placeholder that the (still empty) table can be
# migrated away from cheaply if that choice implies a different one.
EMBEDDING_DIM = 512


class Experiment(Base):
    """An investigation: one question, many attempts at it (D33).

    Mirrors MLflow's own Experiment-groups-Runs shape rather than inventing a
    parallel one. The dataset, target and task live HERE and not on the run
    (D34) — that is what makes the runs inside one experiment comparable, which
    is the precondition ranking needs.
    """

    __tablename__ = "experiments"
    __table_args__ = {"schema": "app"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # May be empty. A migration must never invent an objective nobody stated —
    # a fabricated one reads as though someone meant it (design §5.1).
    objective: Mapped[str] = mapped_column(Text, nullable=False, default="")
    dataset_id: Mapped[str | None] = mapped_column(
        ForeignKey("app.datasets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    dataset_version: Mapped[str | None] = mapped_column(String, nullable=True)
    # Promoted out of MLflow params, where it was recovered with a ""-fallback
    # behind a network call (design §1.5).
    target_column: Mapped[str] = mapped_column(String, nullable=False)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False, default="regression")
    # Lifted from ModelSpec.objective_metric / .direction, not invented (§3.1).
    primary_metric: Mapped[str] = mapped_column(String(32), nullable=False, default="rmse")
    metric_direction: Mapped[str] = mapped_column(String(16), nullable=False, default="minimize")
    mlflow_experiment_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    runs: Mapped[list[Run]] = relationship(back_populates="experiment")


class Run(Base):
    """One logged training run. Params/metrics live in MLflow, not here (D4) —
    this row carries only what MLflow can't: the link back to our dataset and
    the free-text notes that Phase 3 embeds.

    Named `Run` to match MLflow's own entity (D33). The investigation this run
    belongs to is `app.experiments`, added in Task 2.
    """

    __tablename__ = "runs"
    __table_args__ = {"schema": "app"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    mlflow_run_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    model_type: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # D20: an LLM-written note is a draft until a human has read it. Set to
    # "draft" at creation and changed only through Task 8's review endpoint, to
    # "approved" or "rejected". Phase 3 embeds approved notes only — a run with
    # empty notes is still a draft, because "nobody has looked at this" is
    # exactly what the column means.
    notes_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # dataset_id, dataset_version and task_type used to live here; they moved to
    # the parent Experiment (D34) and were dropped from this table once every
    # row had an experiment to inherit them from (D37 contraction). A run
    # cannot exist without one: NOT NULL, no default.
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("app.experiments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    experiment: Mapped[Experiment] = relationship(back_populates="runs")


class Finding(Base):
    """Reviewable model-written text that is not an experiment note (D22).

    `source_id` addresses `datasets.id` when `source_type == "eda"` and
    `runs.id` when it is "diagnostic". A column cannot carry two foreign
    keys, so there is none — `app/findings.py` validates the reference at write
    time instead, the same trade-off D21 already accepted for the chunk table.
    """

    __tablename__ = "findings"
    __table_args__ = {"schema": "app"}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Frozen at insert, never rewritten: without it the left-hand side of 2b.4's
    # draft-vs-edit diff is gone the moment the reviewer saves, and Phase 4 loses
    # its record of how much of the ground truth is the model's words.
    original_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ExperimentNoteChunk(Base):
    """A chunk of reviewable text plus its embedding (D6/D21). Written by
    app/embeddings.py and read by the agent's `search_runs` tool (D41).

    `source_type` discriminates the three content types retrieval covers, and
    each keys to a different table (D30):

    | source_type  | source_id      | text comes from        |
    |--------------|----------------|------------------------|
    | "note"       | app.runs.id    | runs.notes             |
    | "diagnostic" | app.runs.id    | app.findings.text      |
    | "eda"        | app.datasets.id| app.findings.text      |

    Like `findings.source_id`, this addresses more than one table and so carries
    no FK. Only APPROVED text is ever written here (D28), and the backfill
    REAPS chunks whose source is no longer approved — the denormalised `status`
    below is a second line of defence, not the first.
    """

    __tablename__ = "experiment_note_chunks"
    __table_args__ = (
        UniqueConstraint(
            "source_type", "source_id", "chunk_index", name="uq_note_chunks_source_chunk_index"
        ),
        {"schema": "app"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # Denormalised from the source row so a similarity search can filter to
    # approved text in the same query, without a UNION back to two tables.
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    # pgvector's VECTOR type has no SQLite equivalent, and the whole test suite
    # runs on SQLite. with_variant keeps one column definition serving both:
    # VECTOR(512) on Postgres, JSON on SQLite. Vector *operators* (<=>) remain
    # Postgres-only — Phase 3's similarity search is tested against Postgres.
    embedding: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_DIM).with_variant(JSON(), "sqlite"), nullable=False
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
