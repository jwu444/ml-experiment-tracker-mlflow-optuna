"""Metric arithmetic (D43). Offline: no API key, no database, no network.

These numbers are hand-computed. A real eval run's numbers have no
independently known correct value, which is exactly why the arithmetic is
pinned here instead of being trusted because a report printed something.
"""

import pytest
from eval.metrics import (
    aggregate,
    paired_mrr_delta,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    score_query,
)

A = ("note", "a")
B = ("note", "b")
C = ("eda", "c")
D = ("diagnostic", "d")


def test_precision_counts_relevant_in_the_top_k():
    # 2 of the first 4 are relevant.
    assert precision_at_k([A, C, B, D], {A, B}, 4) == 0.5


def test_precision_divides_by_k_not_by_the_result_length():
    """A search that returned 2 sources when 8 were asked for was not perfectly
    precise; dividing by len(ranked) would report 1.0 and hide the shortfall."""
    assert precision_at_k([A, B], {A, B}, 8) == pytest.approx(0.25)


def test_recall_divides_by_the_relevant_set():
    assert recall_at_k([A, C], {A, B}, 8) == 0.5


def test_recall_is_one_when_everything_relevant_is_retrieved():
    assert recall_at_k([C, A, D, B], {A, B}, 8) == 1.0


def test_k_larger_than_the_result_set_is_not_an_error():
    assert recall_at_k([A], {A}, 100) == 1.0
    assert precision_at_k([A], {A}, 100) == pytest.approx(0.01)


def test_nothing_relevant_retrieved_scores_zero_everywhere():
    assert precision_at_k([C, D], {A, B}, 8) == 0.0
    assert recall_at_k([C, D], {A, B}, 8) == 0.0
    assert reciprocal_rank([C, D], {A, B}) == 0.0


def test_reciprocal_rank_uses_the_first_relevant_position():
    assert reciprocal_rank([C, A, B], {A, B}) == pytest.approx(1 / 2)
    assert reciprocal_rank([A, C, B], {A, B}) == 1.0


def test_an_empty_relevant_set_is_a_programming_error():
    """A golden-set entry with no labelled sources is unanswerable, and
    silently scoring it 0.0 would drag the mean down for a data-entry bug."""
    with pytest.raises(ValueError):
        reciprocal_rank([A], set())


def test_score_query_reports_every_cutoff():
    score = score_query("q1", [A, C, B], {A, B}, ks=(1, 3))
    assert score.query_id == "q1"
    assert score.precision[1] == 1.0
    assert score.precision[3] == pytest.approx(2 / 3)
    assert score.recall[1] == 0.5
    assert score.recall[3] == 1.0
    assert score.rr == 1.0


def test_aggregate_means_across_queries():
    one = score_query("q1", [A], {A}, ks=(1,))
    two = score_query("q2", [C], {A}, ks=(1,))
    agg = aggregate([one, two])
    assert agg.n == 2
    assert agg.precision[1] == 0.5
    assert agg.mrr == 0.5


def test_aggregate_of_nothing_is_zero_not_a_crash():
    agg = aggregate([])
    assert agg.n == 0
    assert agg.mrr == 0.0
    assert agg.precision == {}


def test_paired_delta_is_computed_per_query_not_between_means():
    """The D46 adoption rule needs the spread of per-query differences. Taking
    the difference of two means throws that spread away and every challenger
    then looks decisive."""
    base = [
        score_query("q1", [C, A], {A}, ks=(2,)),
        score_query("q2", [A], {A}, ks=(2,)),
    ]
    chal = [
        score_query("q1", [A, C], {A}, ks=(2,)),
        score_query("q2", [A], {A}, ks=(2,)),
    ]
    mean, stderr = paired_mrr_delta(base, chal)
    # q1 improves 0.5 -> 1.0; q2 is unchanged. Mean 0.25, stdev 0.3535..., n=2.
    assert mean == pytest.approx(0.25)
    assert stderr == pytest.approx(0.25)


def test_paired_delta_requires_matching_query_ids():
    """Comparing two configs over different query sets is not a comparison."""
    base = [score_query("q1", [A], {A}, ks=(1,))]
    chal = [score_query("q2", [A], {A}, ks=(1,))]
    with pytest.raises(ValueError):
        paired_mrr_delta(base, chal)


def test_paired_delta_of_a_single_query_has_no_standard_error():
    """One sample has no spread. Reporting 0.0 would make any difference clear
    the adoption bar automatically."""
    base = [score_query("q1", [C, A], {A}, ks=(2,))]
    chal = [score_query("q1", [A, C], {A}, ks=(2,))]
    mean, stderr = paired_mrr_delta(base, chal)
    assert mean == pytest.approx(0.5)
    assert stderr == float("inf")


def test_precision_at_k_with_empty_relevant_raises():
    """Empty relevant set is a programming error."""
    with pytest.raises(ValueError):
        precision_at_k([A], set(), 1)


def test_precision_at_k_with_k_zero_or_negative_raises():
    """k must be positive."""
    with pytest.raises(ValueError):
        precision_at_k([A], {A}, 0)
    with pytest.raises(ValueError):
        precision_at_k([A], {A}, -1)


def test_paired_mrr_delta_with_no_queries_raises():
    """Empty query list is an error."""
    with pytest.raises(ValueError):
        paired_mrr_delta([], [])
