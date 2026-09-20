"""The retrieval agent's one endpoint (3.6).

Mounted at /agent, NOT under /experiments (D42): the agent answers across
investigations, and nesting it under one would imply a scope it does not have.

Like POST /chats/{id}/messages and the two generation endpoints (D23), this calls
the LLM synchronously inside the request. It is the one request-path caller of
Voyage, because every search embeds its query — indexing stays in `make embed`
(D17), so an approval never fails because a vendor is down.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agent import AgentResult, run_agent
from app.db import get_session
from app.schemas import (
    AgentChatOut,
    AgentChatRequest,
    AgentStepOut,
    AgentTraceOut,
    RetrievedOut,
)

router = APIRouter(prefix="/agent", tags=["agent"])


def _out(result: AgentResult) -> AgentChatOut:
    return AgentChatOut(
        answer=result.answer,
        retrieved=[
            RetrievedOut(
                source_type=hit.source_type,
                source_id=hit.source_id,
                run_id=hit.run_id,
                experiment_id=hit.experiment_id,
                dataset_id=hit.dataset_id,
                snippet=hit.snippet,
                score=hit.score,
            )
            for hit in result.retrieved
        ],
        warnings=list(result.warnings),
        trace=AgentTraceOut(
            steps=[
                AgentStepOut(
                    type=step.type,
                    model=step.model,
                    tokens_in=step.tokens_in,
                    tokens_out=step.tokens_out,
                    latency_ms=step.latency_ms,
                    tool_name=step.tool_name,
                    tool_args=step.tool_args,
                    result_summary=step.result_summary,
                    error=step.error,
                )
                for step in result.steps
            ],
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_usd=result.cost_usd,
            latency_ms=result.latency_ms,
        ),
    )


@router.post("/chat", response_model=AgentChatOut)
def chat(body: AgentChatRequest, session: Session = Depends(get_session)) -> AgentChatOut:
    # No try/except, matching routes/chats.py and the two generation endpoints
    # (D23): a loop failure propagates to FastAPI's default handler so the
    # behaviour stays uniform across every LLM-calling route.
    return _out(run_agent(body.question, session))
