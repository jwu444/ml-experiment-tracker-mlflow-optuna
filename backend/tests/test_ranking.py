import pytest
from app.ranking import rank_runs


def test_minimize_orders_ascending_and_marks_the_best():
    ranked = rank_runs(
        [("a", {"rmse": 5.0}), ("b", {"rmse": 2.0}), ("c", {"rmse": 9.0})],
        "rmse",
        "minimize",
    )
    assert [r.run_id for r in ranked] == ["b", "a", "c"]
    assert [r.rank for r in ranked] == [1, 2, 3]
    assert [r.is_best for r in ranked] == [True, False, False]


def test_maximize_orders_descending():
    ranked = rank_runs([("a", {"f1_macro": 0.7}), ("b", {"f1_macro": 0.9})], "f1_macro", "maximize")
    assert [r.run_id for r in ranked] == ["b", "a"]
    assert ranked[0].is_best


def test_a_run_missing_the_metric_sorts_last_and_is_not_ranked():
    """Never dropped and never coerced to 0/inf: a FAILED run is history worth
    seeing, and a silently omitted row is how a leaderboard starts lying."""
    ranked = rank_runs([("missing", {"mae": 1.0}), ("present", {"rmse": 4.0})], "rmse", "minimize")
    assert [r.run_id for r in ranked] == ["present", "missing"]
    assert ranked[1].rank is None
    assert ranked[1].value is None
    assert ranked[1].is_best is False


def test_a_win_smaller_than_the_leaders_cv_std_is_within_noise():
    """On a ~224-row panel a difference smaller than the fold spread is noise."""
    ranked = rank_runs(
        [
            ("winner", {"rmse": 10.0, "cv_rmse": 10.5, "cv_std": 2.0}),
            ("second", {"rmse": 11.0, "cv_rmse": 11.2, "cv_std": 1.8}),
        ],
        "rmse",
        "minimize",
    )
    assert ranked[0].run_id == "winner"
    assert ranked[0].within_noise is True, "margin 1.0 < cv_std 2.0"
    assert ranked[0].cv_value == 10.5
    assert ranked[0].cv_std == 2.0


def test_a_win_larger_than_the_cv_std_is_a_real_win():
    ranked = rank_runs(
        [
            ("winner", {"rmse": 10.0, "cv_rmse": 10.5, "cv_std": 0.2}),
            ("second", {"rmse": 14.0, "cv_rmse": 14.1, "cv_std": 0.3}),
        ],
        "rmse",
        "minimize",
    )
    assert ranked[0].within_noise is False, "margin 4.0 > cv_std 0.2"


def test_the_leader_without_cv_std_is_never_within_noise():
    """The persistence baseline is one of three runs with no cv_std at all
    (design §7.1). Absent spread must not read as zero spread."""
    ranked = rank_runs(
        [("baseline", {"rmse": 10.0}), ("other", {"rmse": 10.1})], "rmse", "minimize"
    )
    assert ranked[0].run_id == "baseline"
    assert ranked[0].cv_std is None
    assert ranked[0].within_noise is False


def test_a_single_run_is_best_but_not_within_noise():
    ranked = rank_runs([("only", {"rmse": 3.0, "cv_std": 9.0})], "rmse", "minimize")
    assert ranked[0].is_best is True
    assert ranked[0].within_noise is False, "nothing to be within noise OF"


def test_the_noise_band_is_the_leaders_spread_not_second_places():
    """Second place's cv_std is deliberately ignored. The claim being qualified
    is "the leader won", so the uncertainty that matters is the leader's — using
    the runner-up's would call a stable leader noisy because a worse, wobblier
    model happened to sit behind it."""
    ranked = rank_runs(
        [
            ("winner", {"rmse": 10.0, "cv_std": 0.1}),
            ("runner_up", {"rmse": 11.0, "cv_std": 50.0}),
        ],
        "rmse",
        "minimize",
    )
    assert ranked[0].run_id == "winner"
    assert ranked[0].within_noise is False, "margin 1.0 > the LEADER's cv_std 0.1"


def test_a_margin_exactly_equal_to_the_cv_std_is_a_real_win():
    """The comparison is strict (`margin < cv_std`). At the boundary the win is
    reported as real — pinned because flipping the operator changes only this
    one input and nothing else in the suite would notice."""
    ranked = rank_runs(
        [("winner", {"rmse": 10.0, "cv_std": 2.0}), ("other", {"rmse": 12.0})],
        "rmse",
        "minimize",
    )
    assert ranked[0].within_noise is False, "margin 2.0 == cv_std 2.0 is not < it"


def test_several_unscored_runs_keep_their_incoming_order():
    """Their order carries whatever the caller sorted by (newest-first, from the
    route). Sorting them among themselves on an absent metric would mean
    inventing an order, so the list comprehension preserves the input's."""
    ranked = rank_runs(
        [("u1", {}), ("scored", {"rmse": 1.0}), ("u2", {}), ("u3", {"mae": 3.0})],
        "rmse",
        "minimize",
    )
    assert [r.run_id for r in ranked] == ["scored", "u1", "u2", "u3"]
    assert [r.rank for r in ranked] == [1, None, None, None]


def test_no_runs_returns_empty():
    assert rank_runs([], "rmse", "minimize") == []


def test_an_unknown_direction_raises():
    with pytest.raises(ValueError, match="direction"):
        rank_runs([("a", {"rmse": 1.0})], "rmse", "sideways")
