"""Chunking and embedding for the retrieval index (3.3).

The only module that imports `voyageai`. Two boundaries it holds:

- **Chunking is a pure function of a string** (D29): split on sentence
  boundaries, accumulate to ~1000 characters, no overlap. Sentence boundaries
  already guarantee no sentence is unretrievable, so overlap would duplicate
  text in the index and inflate Phase 4's recall by counting one passage twice.
- **Indexing and querying use different input types.** Voyage's models are
  trained with that asymmetry; passing "document" for a query costs recall, and
  the only symptom is mediocre eval numbers with nothing to attribute them to.
"""

import logging
import re
import time
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import EMBEDDING_DIM, ExperimentNoteChunk, Finding, Run

logger = logging.getLogger(__name__)

# A blank line ends a block. This is a HARD boundary: a sentence break is only a
# place a chunk MAY end, but a paragraph break is a place it MUST, or a markdown
# heading is packed onto the tail of the section above it and then retrieves as
# that section — the wrong section, with nothing about the result looking wrong.
_BLOCK = re.compile(r"\n{2,}")

# Sentence enders followed by whitespace: where a chunk may break inside a block.
_SENTENCE = re.compile(r"(?<=[.!?])\s+")

# A markdown ATX heading. Headings attach to the section BELOW them (see below).
_HEADING = re.compile(r"^#{1,6}\s")

_INPUT_TYPES = ("document", "query")

# Indirected so tests can substitute it: the retry below is exponential and a
# real sleep would put minutes into the suite.
_sleep = time.sleep


def _is_rate_limited(exc: Exception) -> bool:
    """Is `exc` Voyage saying "too many requests"?

    Matched on the class NAME and the message rather than by importing
    `voyageai.error`: the voyageai import is deliberately deferred into
    `_default_client()` so that a missing package surfaces as a key error at
    call time instead of an ImportError at app startup, and a module-scope
    `except` clause would undo that. It also keeps injected test doubles — which
    raise their own exception classes — on the same path as the real SDK.
    """
    return type(exc).__name__ == "RateLimitError" or "429" in str(exc)


def _pack(block: str, max_chars: int) -> list[str]:
    """Accumulate a block's sentences into chunks of at most `max_chars`.

    A single sentence longer than the budget is emitted whole rather than cut:
    half a sentence retrieves as nonsense, and the embedding model truncates
    over-long input on its own terms.
    """
    chunks: list[str] = []
    current = ""
    for piece in (p.strip() for p in _SENTENCE.split(block)):
        if not piece:
            continue
        candidate = f"{current} {piece}" if current else piece
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = piece
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def chunk_text(text: str, max_chars: int | None = None) -> list[str]:
    """Split `text` into chunks of at most `max_chars`, breaking only between
    sentences and never across a blank line (D29).

    The budget is resolved HERE rather than at the call sites. `backfill` calls
    this twice — once to build chunks, once in its skip check — and passing a
    budget to only one of the two would make every source compare unequal
    forever, re-indexing the whole corpus on every run.

    A heading is held back and prepended to the block beneath it rather than
    becoming a chunk of its own. "## Missingness" alone embeds as almost nothing
    and would answer a question about missingness with a bare heading; carried
    onto its section it is what makes that section findable.
    """
    max_chars = max_chars or settings.chunk_max_chars
    stripped = text.strip()
    if not stripped:
        return []

    chunks: list[str] = []
    pending = ""
    for raw in _BLOCK.split(stripped):
        block = raw.strip()
        if not block:
            continue
        if _HEADING.match(block):
            pending = f"{pending}\n{block}" if pending else block
            continue
        chunks.extend(_pack(f"{pending}\n\n{block}" if pending else block, max_chars))
        pending = ""
    if pending:  # a heading with no section under it — trailing, but not lost
        chunks.append(pending)
    return chunks


def _default_client() -> Any:
    # The key check comes FIRST. With the import above it, a missing key on a
    # machine where voyageai is not installed surfaces as ImportError — the
    # wrong diagnosis for the far more common cause, and it buries the one
    # message here that tells the operator what to do.
    if not settings.voyage_api_key:
        raise RuntimeError("VOYAGE_API_KEY is not set; embedding is unavailable")

    # From voyageai.client, not the package root: voyageai ships py.typed but
    # re-exports Client without `as`, so `voyageai.Client` is an attr-defined
    # error under mypy strict. The submodule is where the class actually lives.
    from voyageai.client import Client

    return Client(api_key=settings.voyage_api_key)


def embed_texts(
    texts: list[str], *, input_type: str, client: Any | None = None
) -> list[list[float]]:
    """Embed `texts` at EMBEDDING_DIM.

    `input_type` is "document" when indexing and "query" when searching, and is
    checked rather than defaulted — a silent default is exactly the mistake that
    shows up only as a recall number nobody can explain.
    """
    if input_type not in _INPUT_TYPES:
        raise ValueError(f"input_type must be one of {_INPUT_TYPES}, got {input_type!r}")
    if not texts:
        return []

    voyage = client or _default_client()
    attempts = max(1, settings.voyage_max_attempts)
    for attempt in range(attempts):
        try:
            resp = voyage.embed(
                texts,
                model=settings.voyage_model,
                input_type=input_type,
                output_dimension=EMBEDDING_DIM,
            )
        except Exception as exc:  # noqa: BLE001 - re-raised unless it is a 429
            # ONLY rate limits are retried. A bad key, a wrong model name or a
            # malformed request fails identically on every attempt, so retrying
            # those turns an instant, legible error into a slow one.
            if not _is_rate_limited(exc) or attempt == attempts - 1:
                raise
            delay = settings.voyage_retry_base_seconds * 2**attempt
            logger.warning(
                "voyage rate limit (attempt %d/%d); retrying in %.1fs",
                attempt + 1,
                attempts,
                delay,
            )
            _sleep(delay)
        else:
            break
    vectors = [[float(v) for v in e] for e in resp.embeddings]
    bad = next((len(v) for v in vectors if len(v) != EMBEDDING_DIM), None)
    if bad is not None:
        # Caught here rather than at INSERT, where the error names the column and
        # says nothing about the provider that produced the wrong width.
        raise ValueError(
            f"{settings.voyage_model} returned {bad}-dimension vectors; "
            f"experiment_note_chunks.embedding is VECTOR({EMBEDDING_DIM})"
        )
    return vectors


@dataclass(frozen=True)
class SourceText:
    """One indexable document: all currently-approved text under one chunk key."""

    source_type: str  # "note" | "eda" | "diagnostic"
    source_id: str  # runs.id for note/diagnostic, datasets.id for eda (D30)
    text: str


@dataclass(frozen=True)
class BackfillReport:
    indexed: int = 0  # keys that had no chunks and now do
    reindexed: int = 0  # keys whose text changed since it was indexed
    reaped: int = 0  # keys no longer approved, whose chunks were deleted
    unchanged: int = 0  # keys already indexed at their current text


def approved_sources(session: Session) -> list[SourceText]:
    """Every currently-approved document, keyed as D30 specifies.

    Eligibility is evaluated against the SOURCE tables, never against the chunk
    table's own denormalised `status` — that copy is what goes stale, and
    trusting it is how rejected text stays retrievable.
    """
    grouped: dict[tuple[str, str], list[str]] = {}

    runs = session.execute(select(Run).where(Run.notes_status == "approved")).scalars()
    for run in runs:
        if run.notes and run.notes.strip():
            grouped.setdefault(("note", run.id), []).append(run.notes.strip())

    # Oldest first, so a re-run produces byte-identical text and the unchanged
    # case stays unchanged rather than churning the index every time. `id`
    # breaks the tie: created_at is second-resolution on SQLite, so two findings
    # written in one commit compare equal, and an unstable order here would
    # reindex text nobody edited on every run.
    findings = session.execute(
        select(Finding).where(Finding.status == "approved").order_by(Finding.created_at, Finding.id)
    ).scalars()
    for finding in findings:
        if finding.text and finding.text.strip():
            key = (finding.source_type, finding.source_id)
            grouped.setdefault(key, []).append(finding.text.strip())

    return [
        SourceText(source_type, source_id, "\n\n".join(parts))
        for (source_type, source_id), parts in grouped.items()
    ]


def _existing_chunks(session: Session) -> dict[tuple[str, str], list[ExperimentNoteChunk]]:
    grouped: dict[tuple[str, str], list[ExperimentNoteChunk]] = {}
    rows = session.execute(
        select(ExperimentNoteChunk).order_by(ExperimentNoteChunk.chunk_index)
    ).scalars()
    for row in rows:
        grouped.setdefault((row.source_type, row.source_id), []).append(row)
    return grouped


def _delete_key(session: Session, source_type: str, source_id: str) -> None:
    """Deletion is by source, never by row. Partial repair of one source's chunks
    is how an index ends up holding half of one revision and half of another."""
    session.execute(
        delete(ExperimentNoteChunk)
        .where(ExperimentNoteChunk.source_type == source_type)
        .where(ExperimentNoteChunk.source_id == source_id)
    )


def index_source(session: Session, source: SourceText, *, client: Any | None = None) -> int:
    """Replace one key's chunks with the chunking of `source.text`. Returns the
    chunk count. Does not commit — the caller owns the transaction."""
    chunks = chunk_text(source.text)
    _delete_key(session, source.source_type, source.source_id)
    if not chunks:
        return 0
    vectors = embed_texts(chunks, input_type="document", client=client)
    for index, (text, vector) in enumerate(zip(chunks, vectors, strict=True)):
        session.add(
            ExperimentNoteChunk(
                source_type=source.source_type,
                source_id=source.source_id,
                chunk_text=text,
                chunk_index=index,
                status="approved",
                embedding=vector,
            )
        )
    return len(chunks)


def backfill(session: Session, *, client: Any | None = None) -> BackfillReport:
    """Reconcile the index against what is currently approved.

    Three cases, and the third is the one an append-only implementation misses:

    | Case                  | Action                               |
    |-----------------------|--------------------------------------|
    | Newly approved        | chunk, embed, insert                 |
    | Edited after approval | delete the key's chunks, re-insert   |
    | No longer approved    | REAP — delete the key's chunks       |

    Without the reap, `approved -> rejected` leaves chunks in the table carrying
    `status = 'approved'`, still ranking. Serving rejected text labelled approved
    is worse than serving nothing, and it defeats D28 silently.
    """
    desired = {(s.source_type, s.source_id): s for s in approved_sources(session)}
    existing = _existing_chunks(session)
    report = BackfillReport()

    for key in existing.keys() - desired.keys():
        _delete_key(session, *key)
        report = replace(report, reaped=report.reaped + 1)

    for key, source in desired.items():
        current = [c.chunk_text for c in existing.get(key, [])]
        if current and current == chunk_text(source.text):
            report = replace(report, unchanged=report.unchanged + 1)
            continue
        try:
            index_source(session, source, client=client)
        except Exception:
            # Named before it propagates. The whole run is one transaction, so a
            # single bad source rolls back every key reconciled before it — and
            # without this line the operator gets a provider traceback with
            # nothing in it identifying WHICH note or finding caused it.
            logger.error("indexing failed for %s %s", source.source_type, source.source_id)
            raise
        if current:
            report = replace(report, reindexed=report.reindexed + 1)
        else:
            report = replace(report, indexed=report.indexed + 1)

    session.commit()
    return report
