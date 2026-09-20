"""`make eval` — retrieval quality against a committed golden set (§4).

Deliberately NOT hermetic and deliberately not part of `make check`: it needs a
real VOYAGE_API_KEY (on a cold cache) and Postgres with pgvector, because the
`<=>` similarity operator has no SQLite equivalent. Grades RETRIEVAL only —
precision@k, recall@k, MRR over sources — and never answer quality: an
LLM-judged answer grade would put Claude on both sides of the scoring, which is
the circularity D44 exists to break.

Reads through `retrieval.search_runs`, exactly as POST /agent/chat does, so
what is measured is the production path and not a reimplementation that can
drift from it.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from app import retrieval
from app.config import settings
from app.db import SessionLocal

from eval.cache import CachingVoyageClient
from eval.metrics import Aggregate, QueryScore, Source, aggregate, score_query

HERE = Path(__file__).resolve().parent
GOLDEN_SET = HERE / "golden_set.yaml"
CACHE = HERE / ".vector-cache.json"
RESULTS = HERE / "results"

KS: tuple[int, ...] = (3, 5, 8)
"""Reporting cutoffs. Retrieval runs ONCE at settings.retrieval_top_k and these
are three readings of that one ranked list — not three searches (D46)."""


@dataclass(frozen=True)
class GoldenQuery:
    id: str
    query: str
    relevant: frozenset[Source]
    notes: str


def load_golden_set(path: Path = GOLDEN_SET) -> list[GoldenQuery]:
    raw = yaml.safe_load(path.read_text()) or []
    queries: list[GoldenQuery] = []
    seen: set[str] = set()
    for entry in raw:
        qid = entry["id"]
        if qid in seen:
            # paired_mrr_delta pairs by position and id; duplicates make the
            # sweep's comparison ambiguous.
            raise ValueError(f"duplicate golden-set id: {qid}")
        seen.add(qid)
        relevant = frozenset((str(t), str(i)) for t, i in entry.get("relevant") or [])
        if not relevant:
            raise ValueError(f"golden-set entry {qid} labels no relevant sources")
        queries.append(
            GoldenQuery(
                id=qid, query=entry["query"], relevant=relevant, notes=entry.get("notes", "")
            )
        )
    return queries


def run_eval(session: Any, queries: list[GoldenQuery], *, client: Any, k: int) -> list[QueryScore]:
    scores: list[QueryScore] = []
    for q in queries:
        hits, _warnings = retrieval.search_runs(session, q.query, k=k, client=client)
        ranked: list[Source] = [(h.source_type, h.source_id) for h in hits]
        scores.append(score_query(q.id, ranked, q.relevant, ks=KS))
    return scores


def validate_golden_set(session: Any, queries: list[GoldenQuery]) -> list[str]:
    """Every labelled source must exist AND be indexed.

    A typo'd id is unreachable, so the query scores 0.0 and looks like a
    retrieval failure. This turns that into a named problem.
    """
    from app.models import ExperimentNoteChunk

    indexed = {
        (row.source_type, row.source_id)
        for row in session.query(
            ExperimentNoteChunk.source_type, ExperimentNoteChunk.source_id
        ).distinct()
    }
    problems: list[str] = []
    for q in queries:
        for source in sorted(q.relevant):
            if source not in indexed:
                problems.append(f"{q.id}: {source[0]}/{source[1]} is not in the index")
    return problems


def render_report(
    scores: list[QueryScore], agg: Aggregate, *, label: str, config: dict[str, Any]
) -> str:
    """A results file that does not name its configuration cannot be compared
    to another one, which is the whole point of the sweep (D46)."""
    lines = [
        f"# Retrieval eval — {label}",
        "",
        "## Configuration",
        "",
        "| Setting | Value |",
        "| --- | --- |",
    ]
    lines += [f"| `{key}` | {value} |" for key, value in sorted(config.items())]
    lines += [
        "",
        "## Aggregate",
        "",
        f"- queries: **{agg.n}**",
        f"- MRR: **{agg.mrr:.3f}**",
    ]
    lines += [f"- precision@{k}: {agg.precision[k]:.3f}" for k in KS]
    lines += [f"- recall@{k}: {agg.recall[k]:.3f}" for k in KS]
    lines += ["", "## Per query", "", "| query | RR | " + " | ".join(f"P@{k}" for k in KS) + " |"]
    lines.append("| --- | --- |" + " --- |" * len(KS))
    for s in scores:
        cells = " | ".join(f"{s.precision[k]:.2f}" for k in KS)
        lines.append(f"| {s.query_id} | {s.rr:.2f} | {cells} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Retrieval eval over the golden set")
    parser.add_argument("--label", default="baseline", help="names the report and its file")
    parser.add_argument("--no-cache", action="store_true", help="ignore the vector cache")
    parser.add_argument("--validate-only", action="store_true", help="check ids, do not search")
    args = parser.parse_args()

    if "sqlite" in settings.database_url:
        # The `<=>` operator has no SQLite equivalent. Failing here names the
        # problem; failing inside the query would name an operator.
        print(
            "error: the eval needs Postgres with pgvector — DATABASE_URL points at SQLite.\n"
            "       run `make db-up` and set DATABASE_URL in .env.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    queries = load_golden_set()
    inner = None
    if not args.no_cache and not settings.voyage_api_key:
        print("warning: VOYAGE_API_KEY is unset; only fully-cached runs will work", file=sys.stderr)
    elif settings.voyage_api_key:
        from app import embeddings

        inner = embeddings._default_client()

    with SessionLocal() as session:
        problems = validate_golden_set(session, queries)
        if problems:
            print("golden set does not match the index:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            raise SystemExit(1)
        if args.validate_only:
            print(f"golden set is clean: {len(queries)} queries, every labelled source indexed.")
            return

        cache = None if args.no_cache else CachingVoyageClient(CACHE, inner=inner)
        scores = run_eval(session, queries, client=cache, k=settings.retrieval_top_k)

    if cache is not None:
        cache.save()
        print(f"vector cache: {cache.hits} hit(s), {cache.misses} miss(es)")

    agg = aggregate(scores)
    config = {
        "chunk_max_chars": settings.chunk_max_chars,
        "chunk_overfetch": settings.chunk_overfetch,
        "retrieval_top_k": settings.retrieval_top_k,
        "voyage_model": settings.voyage_model,
    }
    report = render_report(scores, agg, label=args.label, config=config)
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{args.label}.md"
    out.write_text(report)
    print(report)
    print(f"written to {out}")


if __name__ == "__main__":
    main()
