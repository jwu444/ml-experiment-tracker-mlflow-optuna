"""Retrieval metrics over sources (D43).

The ground-truth unit is `(source_type, source_id)` — the unit
`retrieval.search_runs` returns. Not experiment ids (D33 split experiment from
run, and an `eda` source is keyed to a dataset and has no experiment id at
all), and not chunk ids (`k` counts sources, so a chunk-level metric would
measure something the system does not return).

Pure: no I/O, no database, no imports from `app`. That is what lets it run
inside `make check` with no key and no Postgres, and the arithmetic is the part
a real-API suite tests worst — a live run's numbers have no independently known
correct value.
"""

from __future__ import annotations

import statistics
from collections.abc import Collection, Sequence
from dataclasses import dataclass

Source = tuple[str, str]
"""(source_type, source_id) — "note" | "diagnostic" | "eda", and its row id."""


def _check_relevant(relevant: Collection[Source]) -> None:
    if not relevant:
        # A golden-set entry with no labelled sources is unanswerable. Scoring
        # it 0.0 would drag every mean down for what is really a data-entry bug.
        raise ValueError(
            "the relevant set is empty; a golden-set entry must label at least one source"
        )


def precision_at_k(ranked: Sequence[Source], relevant: Collection[Source], k: int) -> float:
    """Fraction of the top `k` slots filled by a relevant source.

    Divides by `k`, NOT by `len(ranked)`. A search asked for 8 sources and
    returning 2 relevant ones was not perfectly precise, and dividing by the
    result length would report 1.0 and hide the shortfall.
    """
    _check_relevant(relevant)
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")
    wanted = set(relevant)
    return sum(1 for source in ranked[:k] if source in wanted) / k


def recall_at_k(ranked: Sequence[Source], relevant: Collection[Source], k: int) -> float:
    """Fraction of the relevant sources that appear in the top `k`."""
    _check_relevant(relevant)
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")
    wanted = set(relevant)
    return sum(1 for source in ranked[:k] if source in wanted) / len(wanted)


def reciprocal_rank(ranked: Sequence[Source], relevant: Collection[Source]) -> float:
    """1 / (1-based position of the first relevant source); 0.0 if none."""
    _check_relevant(relevant)
    wanted = set(relevant)
    for position, source in enumerate(ranked, start=1):
        if source in wanted:
            return 1.0 / position
    return 0.0


@dataclass(frozen=True)
class QueryScore:
    """One golden-set query's scores, at every reported cutoff."""

    query_id: str
    precision: dict[int, float]
    recall: dict[int, float]
    rr: float


def score_query(
    query_id: str,
    ranked: Sequence[Source],
    relevant: Collection[Source],
    ks: Sequence[int],
) -> QueryScore:
    """Score one query. `ranked` is ONE search's results; the cutoffs in `ks`
    are readings of that one list, not separate searches (D46)."""
    return QueryScore(
        query_id=query_id,
        precision={k: precision_at_k(ranked, relevant, k) for k in ks},
        recall={k: recall_at_k(ranked, relevant, k) for k in ks},
        rr=reciprocal_rank(ranked, relevant),
    )


@dataclass(frozen=True)
class Aggregate:
    n: int
    precision: dict[int, float]
    recall: dict[int, float]
    mrr: float


def aggregate(scores: Sequence[QueryScore]) -> Aggregate:
    """Unweighted means across queries. MRR is the mean reciprocal rank."""
    if not scores:
        return Aggregate(n=0, precision={}, recall={}, mrr=0.0)
    ks = sorted(scores[0].precision)
    return Aggregate(
        n=len(scores),
        precision={k: statistics.fmean(s.precision[k] for s in scores) for k in ks},
        recall={k: statistics.fmean(s.recall[k] for s in scores) for k in ks},
        mrr=statistics.fmean(s.rr for s in scores),
    )


def paired_mrr_delta(
    baseline: Sequence[QueryScore], challenger: Sequence[QueryScore]
) -> tuple[float, float]:
    """(mean, standard error) of the PER-QUERY reciprocal-rank differences.

    D46's adoption rule needs the spread of the differences, so the pairing
    happens per query and not between two aggregate means — differencing two
    means discards the spread entirely, after which every challenger clears any
    bar you set.

    A single query has no spread, so the standard error is infinite rather than
    zero: reporting 0.0 would let any difference at all clear the bar.
    """
    if [s.query_id for s in baseline] != [s.query_id for s in challenger]:
        raise ValueError("paired comparison needs the same queries in the same order")
    diffs = [c.rr - b.rr for b, c in zip(baseline, challenger, strict=True)]
    if not diffs:
        raise ValueError("no queries to compare")
    mean = statistics.fmean(diffs)
    if len(diffs) < 2:
        return mean, float("inf")
    return mean, statistics.stdev(diffs) / (len(diffs) ** 0.5)
