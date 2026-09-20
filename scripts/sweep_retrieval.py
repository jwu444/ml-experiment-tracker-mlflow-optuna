"""The pre-registered retrieval sweep (§5, D46).

The grid, the metric and the adoption rule are fixed in this file's first
commit, BEFORE any configuration is measured. Nine configurations scored on
twenty queries with the winner chosen afterwards finds a winner from noise
essentially every time — there is always a highest number.

chunk_overfetch changes nothing about the index, so all three of its values are
measured against one re-index. chunk_max_chars does change it: each of its three
values costs a full `make embed` cycle, one Voyage request per changed source at
the free tier's 3 RPM.

Run any invocation that touches Voyage with a wider retry budget than the
committed defaults, which are tuned for a paid tier:

    VOYAGE_MAX_ATTEMPTS=5 VOYAGE_RETRY_BASE_SECONDS=25 poetry run python scripts/sweep_retrieval.py
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from app.config import settings
from app.db import SessionLocal
from app.embeddings import backfill
from eval.cache import CachingVoyageClient
from eval.metrics import aggregate, paired_mrr_delta
from eval.runner import CACHE, RESULTS, load_golden_set, run_eval

GRID: tuple[tuple[int, int], ...] = tuple(
    (chars, over) for chars in (600, 1000, 1500) for over in (2, 4, 8)
)
"""(chunk_max_chars, chunk_overfetch). Pre-registered — see the module docstring."""

BASELINE: tuple[int, int] = (1000, 4)
ADOPTION_SIGMA = 2.0


@dataclass(frozen=True)
class SweepRow:
    chunk_max_chars: int
    chunk_overfetch: int
    mrr: float
    delta: float
    stderr: float
    adopt: bool


def adoption_verdict(delta: float, stderr: float) -> bool:
    """Strictly greater than two standard errors. The boundary goes to the
    incumbent: a tie is not evidence for changing a shipped default (D38)."""
    if stderr == float("inf"):
        return False
    return delta > ADOPTION_SIGMA * stderr


def render_sweep(rows: list[SweepRow], baseline_mrr: float) -> str:
    lines = [
        "# Retrieval sweep — pre-registered grid (D46)",
        "",
        "The grid, the metric and the adoption rule were committed before any",
        "configuration was measured. A configuration is adopted only if its",
        "**paired** MRR delta against the baseline exceeds **two standard errors**;",
        "otherwise the baseline stands.",
        "",
        f"Baseline: `chunk_max_chars={BASELINE[0]}`, `chunk_overfetch={BASELINE[1]}`, "
        f"MRR **{baseline_mrr:.3f}**.",
        "",
        "| chunk_max_chars | chunk_overfetch | MRR | Δ MRR | std. err. | adopt? |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row.chunk_max_chars} | {row.chunk_overfetch} | {row.mrr:.3f} | "
            f"{row.delta:+.3f} | {row.stderr:.3f} | {'**yes**' if row.adopt else 'no'} |"
        )
    lines.append("")
    winners = [r for r in rows if r.adopt]
    if winners:
        best = max(winners, key=lambda r: r.delta)
        lines.append(
            f"**Adopted:** `chunk_max_chars={best.chunk_max_chars}`, "
            f"`chunk_overfetch={best.chunk_overfetch}` "
            f"({best.delta:+.3f} ± {best.stderr:.3f})."
        )
    else:
        lines.append(
            "**No configuration cleared the bar.** The baseline stands. This is the "
            "likeliest outcome at n=20 and is a result, not a failed sweep: it says the "
            "defaults are not detectably wrong at this corpus size, and it is the honest "
            "alternative to shipping the highest number in the table."
        )
    return "\n".join(lines) + "\n"


def _reindex(chunk_max_chars: int, client: object) -> None:
    """Re-chunk and re-embed at a new size.

    backfill()'s skip check is `current == chunk_text(source.text)`, which
    re-chunks with the CURRENT parameters — so a chunk-size change is correctly
    seen as an edit and every source is re-indexed. Nothing extra is needed here.
    """
    settings.chunk_max_chars = chunk_max_chars
    with SessionLocal() as session:
        report = backfill(session, client=client)
        session.commit()
    print(f"  reindexed at {chunk_max_chars}: {report}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-registered retrieval sweep")
    parser.add_argument("--dry-run", action="store_true", help="print the grid and exit")
    args = parser.parse_args()

    if args.dry_run:
        for chars, over in GRID:
            print(f"chunk_max_chars={chars} chunk_overfetch={over}")
        return
    if "sqlite" in settings.database_url:
        print("error: the sweep needs Postgres with pgvector.", file=sys.stderr)
        raise SystemExit(1)

    from app import embeddings

    cache = CachingVoyageClient(CACHE, inner=embeddings._default_client())
    queries = load_golden_set()
    by_config: dict[tuple[int, int], list] = {}

    # Grouped by chunk size so each re-index is paid once, not once per overfetch.
    for chars in sorted({c for c, _ in GRID}):
        _reindex(chars, cache)
        for over in sorted({o for c, o in GRID if c == chars}):
            settings.chunk_overfetch = over
            with SessionLocal() as session:
                by_config[(chars, over)] = run_eval(
                    session, queries, client=cache, k=settings.retrieval_top_k
                )
            print(f"  scored ({chars}, {over})", file=sys.stderr)
    cache.save()

    base_scores = by_config[BASELINE]
    rows: list[SweepRow] = []
    for config in GRID:
        scores = by_config[config]
        # (baseline, challenger) — reversing these inverts every delta in
        # the table, and the sign is the only thing the adoption rule reads.
        delta, stderr = paired_mrr_delta(base_scores, scores)
        rows.append(
            SweepRow(
                chunk_max_chars=config[0],
                chunk_overfetch=config[1],
                mrr=aggregate(scores).mrr,
                delta=delta,
                stderr=stderr,
                adopt=config != BASELINE and adoption_verdict(delta, stderr),
            )
        )

    report = render_sweep(rows, baseline_mrr=aggregate(base_scores).mrr)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "sweep.md").write_text(report)
    print(report)

    # Leave the index at whatever the adopted configuration is — a store left at
    # 1500 while settings say 1000 is an index that silently disagrees with the code.
    adopted = next((r for r in rows if r.adopt), None)
    final = (adopted.chunk_max_chars, adopted.chunk_overfetch) if adopted else BASELINE
    _reindex(final[0], cache)
    cache.save()
    print(f"index restored to chunk_max_chars={final[0]}", file=sys.stderr)


if __name__ == "__main__":
    main()
