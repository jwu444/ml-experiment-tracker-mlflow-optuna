"""Read and review endpoints for findings (D22).

The same D20 semantics as PATCH /experiments/{id}: sending `text` alone is an
edit, never an approval. Approval requires an explicit `status`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import findings
from app.db import get_session
from app.models import Finding
from app.schemas import FindingOut, FindingPatchRequest

router = APIRouter(prefix="/findings", tags=["findings"])


def _out(row: Finding) -> FindingOut:
    return FindingOut(
        id=row.id,
        source_type=row.source_type,
        source_id=row.source_id,
        text=row.text,
        original_text=row.original_text,
        status=row.status,
        created_at=row.created_at,
    )


@router.get("", response_model=list[FindingOut])
def list_findings(
    status: str | None = None,
    source_type: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    source_id: str | None = None,
    session: Session = Depends(get_session),
) -> list[FindingOut]:
    rows = findings.list_findings(session, status, source_type, limit, offset, source_id)
    return [_out(r) for r in rows]


@router.patch("/{finding_id}", response_model=FindingOut)
def update_finding(
    finding_id: str,
    request: FindingPatchRequest,
    session: Session = Depends(get_session),
) -> FindingOut:
    try:
        row = findings.update_finding(session, finding_id, request.text, request.status)
    except findings.FindingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    session.commit()
    session.refresh(row)
    return _out(row)
