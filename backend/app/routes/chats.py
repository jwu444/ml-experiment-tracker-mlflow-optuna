"""Chat endpoints: a chat spans one or more datasets. Drives the quality-gated
LLM loop (app.loop.run_loop), which selects/validates/executes chart tools and
scores its own interpretation, then persists the turn (incl. pass_count and
judge_score) and returns charts + interpretation. History reads re-render
charts, never store them."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.charts import render_message_analysis
from app.dataset_io import load_csv
from app.db import get_session
from app.loop import run_loop
from app.models import Analysis, Chat, ChatDataset, ChatMessage, Dataset
from app.schemas import (
    ChatCreateRequest,
    ChatDatasetOut,
    ChatHistoryOut,
    ChatMessageOut,
    ChatOut,
    ChatRequest,
    MessageTraceOut,
)

router = APIRouter(prefix="/chats", tags=["chat"])


def _get_chat(session: Session, chat_id: str) -> Chat:
    chat = session.get(Chat, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


def _chat_datasets(session: Session, chat_id: str) -> list[Dataset]:
    rows = session.scalars(
        select(ChatDataset)
        .where(ChatDataset.chat_id == chat_id)
        .order_by(ChatDataset.ordinal_position)
    ).all()
    datasets: list[Dataset] = []
    for row in rows:
        dataset = session.get(Dataset, row.dataset_id)
        if dataset is not None:
            datasets.append(dataset)
    return datasets


def _prior_messages(session: Session, chat_id: str) -> list[dict[str, str]]:
    rows = session.scalars(
        select(ChatMessage).where(ChatMessage.chat_id == chat_id).order_by(ChatMessage.created_at)
    ).all()
    return [{"role": r.role, "content": r.content} for r in rows]


@router.post("", response_model=ChatOut)
def create_chat(body: ChatCreateRequest, session: Session = Depends(get_session)) -> ChatOut:
    if not body.dataset_ids:
        raise HTTPException(status_code=400, detail="At least one dataset_id is required")

    datasets: list[Dataset] = []
    for dataset_id in body.dataset_ids:
        dataset = session.get(Dataset, dataset_id)
        if dataset is None:
            raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
        datasets.append(dataset)

    chat = Chat()
    session.add(chat)
    session.flush()
    for ordinal_position, dataset in enumerate(datasets):
        session.add(
            ChatDataset(chat_id=chat.id, dataset_id=dataset.id, ordinal_position=ordinal_position)
        )
    session.commit()

    return ChatOut(id=chat.id, datasets=[ChatDatasetOut(id=d.id, name=d.name) for d in datasets])


@router.post("/{chat_id}/messages", response_model=ChatMessageOut)
def post_message(
    chat_id: str,
    body: ChatRequest,
    session: Session = Depends(get_session),
) -> ChatMessageOut:
    chat = _get_chat(session, chat_id)
    datasets = _chat_datasets(session, chat.id)

    prior = _prior_messages(session, chat.id)
    session.add(ChatMessage(chat_id=chat.id, role="user", content=body.question))
    session.flush()

    result = run_loop(
        [{"id": d.id, "name": d.name, "profile": d.profile_json} for d in datasets],
        {d.id: load_csv(d.data_csv) for d in datasets},
        prior,
        body.question,
    )

    trace_payload = {"passes": result.trace}
    assistant = ChatMessage(
        chat_id=chat.id,
        role="assistant",
        content=result.interpretation,
        tool_calls=result.tool_calls,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        cost_usd=result.cost_usd,
        latency_ms=result.latency_ms,
        pass_count=result.pass_count,
        judge_score=result.judge_score,
        trace_json=trace_payload,
    )
    session.add(assistant)
    session.flush()

    for call, stat in zip(result.tool_calls, result.stats, strict=True):
        session.add(
            Analysis(
                message_id=assistant.id,
                chart_type=call["name"],
                params=call["args"],
                result_stats=stat,
            )
        )

    session.commit()
    return ChatMessageOut(
        id=assistant.id,
        role="assistant",
        content=result.interpretation,
        charts=result.charts,
        stats=result.stats,
        errors=result.errors,
        trace=MessageTraceOut.model_validate(trace_payload),
    )


@router.get("/{chat_id}", response_model=ChatHistoryOut)
def get_chat(chat_id: str, session: Session = Depends(get_session)) -> ChatHistoryOut:
    chat = _get_chat(session, chat_id)
    datasets = _chat_datasets(session, chat.id)
    data_csv_by_id = {d.id: d.data_csv for d in datasets}

    rows = session.scalars(
        select(ChatMessage).where(ChatMessage.chat_id == chat.id).order_by(ChatMessage.created_at)
    ).all()

    messages: list[ChatMessageOut] = []
    for r in rows:
        if r.role == "assistant" and r.tool_calls:
            charts, stats = render_message_analysis(data_csv_by_id, r.tool_calls)
        else:
            charts, stats = [], []
        # The trace is persisted verbatim (its PNGs are stored, not re-rendered).
        trace = MessageTraceOut.model_validate(r.trace_json) if r.trace_json else None
        messages.append(
            ChatMessageOut(
                id=r.id,
                role=r.role,
                content=r.content,
                charts=charts,
                stats=stats,
                errors=[],
                trace=trace,
            )
        )
    return ChatHistoryOut(
        datasets=[ChatDatasetOut(id=d.id, name=d.name) for d in datasets],
        messages=messages,
    )
