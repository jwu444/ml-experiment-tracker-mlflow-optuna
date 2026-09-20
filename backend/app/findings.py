"""Findings persistence and validation (D22).

Knows nothing about HTTP or LLMs. Routes translate `FindingError.status_code`
into an `HTTPException`; the LLM layer hands this module finished text.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Dataset, Finding, Run

SOURCE_TYPES = frozenset({"eda", "diagnostic"})
STATUSES = frozenset({"draft", "approved", "rejected"})


class FindingError(Exception):
    """A validation failure carrying the HTTP status a route should return."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _validate_source(session: Session, source_type: str, source_id: str) -> None:
    """The referential check the missing foreign key no longer performs.

    An unknown `source_id` is an error at write time, not a dangling row
    discovered later when Phase 3 retrieves a finding whose subject is gone.
    """
    if source_type not in SOURCE_TYPES:
        raise FindingError(422, f"unknown source_type; known: {sorted(SOURCE_TYPES)}")
    model = Dataset if source_type == "eda" else Run
    if session.get(model, source_id) is None:
        raise FindingError(404, f"no {source_type} source with id {source_id!r}")


def create_finding(session: Session, source_type: str, source_id: str, text: str) -> Finding:
    """Insert a draft finding. `original_text` is set here and never again."""
    _validate_source(session, source_type, source_id)
    row = Finding(
        source_type=source_type,
        source_id=source_id,
        text=text,
        original_text=text,
        status="draft",
    )
    session.add(row)
    session.flush()
    return row


def list_findings(
    session: Session,
    status: str | None = None,
    source_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    source_id: str | None = None,
) -> list[Finding]:
    """Findings, newest first, narrowed by any combination of the filters.

    `source_id` addresses two tables (D22), so it is only meaningful beside a
    `source_type` — but it is not *required* to carry one, because ids here are
    uuids and do not collide across tables. It exists so a page showing one
    dataset or one run can ask for exactly that row's findings: filtering a
    broad fetch client-side would silently drop everything past `limit`, and
    the page would look empty rather than truncated.
    """
    query = select(Finding).order_by(Finding.created_at.desc())
    if status:
        query = query.where(Finding.status == status)
    if source_type:
        query = query.where(Finding.source_type == source_type)
    if source_id:
        query = query.where(Finding.source_id == source_id)
    return list(session.execute(query.limit(limit).offset(offset)).scalars())


def update_finding(
    session: Session,
    finding_id: str,
    text: str | None = None,
    status: str | None = None,
) -> Finding:
    """Edit the text, move the review status, or both (D20).

    Sending `text` alone is an edit and never an approval — the same rule
    `PATCH /experiments/{id}` established, for the same reason: a generator that
    writes through this path must not be able to bless its own output.
    """
    row = session.get(Finding, finding_id)
    if row is None:
        raise FindingError(404, "Finding not found")
    if text is not None:
        row.text = text
    if status is not None:
        if status not in STATUSES:
            raise FindingError(422, f"unknown status; known: {sorted(STATUSES)}")
        if status == "approved" and not row.text.strip():
            raise FindingError(422, "an empty finding cannot be approved")
        row.status = status
    session.flush()
    return row
