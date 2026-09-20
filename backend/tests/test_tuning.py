from unittest import mock

import pandas as pd
import pytest
from app import training
from app.tuning import TrialRecord, run_study


def frame(n: int = 60) -> pd.DataFrame:
    return pd.DataFrame(
        {"memory": [4 * (i % 6) + 4 for i in range(n)], "price": [100.0 + i for i in range(n)]}
    )


def labelled(n: int = 60) -> pd.DataFrame:
    df = frame(n)
    df["direction"] = ["up" if m > 14 else "down" for m in df["memory"]]
    return df


def test_study_runs_the_requested_number_of_trials():
    result = run_study("ridge", frame(), "price", ["memory"], n_trials=3)
    assert len(result.trials) == 3
    assert all(t.status == "FINISHED" for t in result.trials)


def test_a_minimising_study_reports_its_lowest_trial():
    result = run_study("ridge", frame(), "price", ["memory"], n_trials=4)
    assert result.direction == "minimize"
    assert result.best_value == min(t.value for t in result.trials)
    assert "alpha" in result.best_params


def test_a_maximising_study_reports_its_HIGHEST_trial():
    # The whole point of a per-registry-entry direction. Under a hard-coded
    # `direction="minimize"` this passes back the worst classifier found and
    # nothing anywhere says so.
    result = run_study("logistic_regression", labelled(), "direction", ["memory"], n_trials=4)
    assert result.direction == "maximize"
    assert result.best_value == max(t.value for t in result.trials)


def test_every_trial_carries_its_cv_standard_deviation():
    result = run_study("ridge", frame(), "price", ["memory"], n_trials=2)
    assert all(t.std is not None and t.std >= 0 for t in result.trials)


def test_every_trial_is_reported_to_the_callback():
    seen = []
    run_study("ridge", frame(), "price", ["memory"], n_trials=3, on_trial=seen.append)
    assert len(seen) == 3
    assert [t.number for t in seen] == [0, 1, 2]


def test_a_persistence_failure_propagates_instead_of_being_swallowed():
    """`on_trial` raising must fail the study, not quietly skip the trial.

    It is the caller's DB write. Swallowing it would leave the study's own best
    trial pointing at a run nobody stored, so the route could name one trial in
    `best_run_id` and a different one in `best_metrics`.
    """

    def explode(record: TrialRecord) -> None:
        raise RuntimeError("db is down")

    with pytest.raises(RuntimeError, match="db is down"):
        run_study("ridge", frame(), "price", ["memory"], n_trials=3, on_trial=explode)


def test_a_bad_hyperparameter_draw_is_still_pruned_not_raised():
    """The counterpart: dropping `catch=` must not turn a fit failure into a 500.

    A draw that cannot fit becomes `TrialPruned`, which Optuna honours whether or
    not `catch=` is set — so the study completes and simply reports fewer usable
    trials.
    """
    calls = {"n": 0}
    real = training.cv_objective

    def flaky(*args: object, **kwargs: object) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("singular matrix")
        return real(*args, **kwargs)  # type: ignore[arg-type]

    with mock.patch.object(training, "cv_objective", flaky):
        result = run_study("ridge", frame(), "price", ["memory"], n_trials=3)
    assert calls["n"] == 3, "the patch never took effect, so this proves nothing"
    assert len(result.trials) == 3  # the pruned trial is still recorded
    assert result.trials[0].value is None  # ...but carries no value
    assert result.best_value is not None


def test_a_time_column_is_passed_through_to_the_objective():
    captured = {}

    import app.tuning as tuning_mod

    real = tuning_mod.training.cv_objective

    def spy(model_type, params, df, target, features, time_column=None):
        captured["time_column"] = time_column
        return real(model_type, params, df, target, features, time_column)

    tuning_mod.training.cv_objective = spy
    try:
        panel = frame()
        panel["as_of"] = pd.date_range("2015-01-01", periods=len(panel), freq="QE")
        run_study("ridge", panel, "price", ["memory"], n_trials=1, time_column="as_of")
    finally:
        tuning_mod.training.cv_objective = real
    assert captured["time_column"] == "as_of"


def test_a_failing_trial_is_recorded_not_raised(monkeypatch):
    import app.tuning as tuning_mod

    def boom(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(tuning_mod.training, "cv_objective", boom)
    result = run_study("ridge", frame(), "price", ["memory"], n_trials=2)
    assert len(result.trials) == 2
    assert all(t.status == "FAILED" for t in result.trials)
    assert result.best_params == {}


def test_unknown_model_type_raises():
    with pytest.raises(ValueError, match="unknown model_type"):
        run_study("nope", frame(), "price", ["memory"], n_trials=1)
