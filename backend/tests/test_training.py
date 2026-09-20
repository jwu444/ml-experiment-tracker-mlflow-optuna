import numpy as np
import pandas as pd
import pytest
from app.training import (
    MODEL_REGISTRY,
    cv_objective,
    cv_splitter,
    fit_and_score,
    prepare,
    split_frame,
)
from sklearn.model_selection import KFold, TimeSeriesSplit

REGRESSORS = sorted(
    k
    for k, s in MODEL_REGISTRY.items()
    # persistence needs an explicit prior_column hyperparam pointing at a real
    # feature column, so it does not share this test's `{}`-hyperparams
    # contract; it is exercised end-to-end in test_baseline.py instead.
    if s.task_type == "regression" and k != "persistence"
)
CLASSIFIERS = sorted(k for k, s in MODEL_REGISTRY.items() if s.task_type == "classification")


def make_frame(n: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    memory = rng.integers(4, 25, n)
    chipset = rng.choice(["a", "b", "c"], n)
    price = memory * 30.0 + rng.normal(0, 5, n)
    return pd.DataFrame({"memory": memory, "chipset": chipset, "price": price})


def make_panel(n: int = 60) -> pd.DataFrame:
    """A time-indexed frame whose target rises monotonically with time.

    That monotonicity is what makes the chronological-split test meaningful: if
    the split is honoured, every test target exceeds every train target.
    """
    df = make_frame(n)
    df["as_of"] = pd.date_range("2015-01-01", periods=n, freq="QE")
    df["price"] = np.arange(n, dtype=float) * 10.0
    return df


def make_labels(n: int = 60) -> pd.DataFrame:
    df = make_frame(n)
    df["direction"] = np.where(df["memory"] > 14, "up", "down")
    return df


def test_prepare_drops_null_target_rows():
    df = make_frame(10)
    df.loc[0:2, "price"] = None
    x, y = prepare(df, "price", ["memory", "chipset"], None)
    assert len(x) == len(y) == 7
    assert not y.isna().any()


def test_prepare_rejects_missing_target():
    with pytest.raises(ValueError, match="target"):
        prepare(make_frame(5), "nope", ["memory"], None)


def test_prepare_rejects_all_null_target():
    df = make_frame(5)
    df["price"] = None
    with pytest.raises(ValueError, match="non-null"):
        prepare(df, "price", ["memory"], None)


def test_prepare_sorts_by_the_time_column_and_drops_it_from_features():
    df = make_panel(12).sample(frac=1, random_state=1)  # deliberately shuffled
    x, y = prepare(df, "price", ["memory", "as_of"], "as_of")
    assert "as_of" not in x.columns
    assert list(y) == sorted(y)


def test_prepare_rejects_the_target_as_a_feature():
    # Without the guard this selects `price` twice, and the opaque
    # "DuplicateError: Expected unique column names" it eventually raises says
    # nothing about the actual mistake. /train takes `features` from the
    # request body, so this is a user-facing error.
    with pytest.raises(ValueError, match="target"):
        prepare(make_frame(10), "price", ["memory", "price"], None)


def test_prepare_rejects_duplicate_features():
    with pytest.raises(ValueError, match="duplicate"):
        prepare(make_frame(10), "price", ["memory", "memory"], None)


def test_prepare_rejects_an_unknown_time_column():
    with pytest.raises(ValueError, match="time column"):
        prepare(make_frame(5), "price", ["memory"], "nope")


def test_chronological_split_puts_the_latest_rows_in_test():
    x, y = prepare(make_panel(50), "price", ["memory", "chipset"], "as_of")
    _, _, y_train, y_test = split_frame(x, y, chronological=True)
    assert y_train.max() < y_test.min()


def test_random_split_does_not_preserve_time_order():
    x, y = prepare(make_panel(50), "price", ["memory", "chipset"], "as_of")
    _, _, y_train, y_test = split_frame(x, y, chronological=False)
    assert y_train.max() > y_test.min()


def test_cv_splitter_is_time_aware_only_when_chronological():
    assert isinstance(cv_splitter(chronological=True), TimeSeriesSplit)
    assert isinstance(cv_splitter(chronological=False), KFold)


@pytest.mark.parametrize("model_type", REGRESSORS)
def test_every_regressor_fits_and_scores(model_type):
    result = fit_and_score(model_type, {}, make_frame(), "price", ["memory", "chipset"], None)
    assert result.status == "FINISHED"
    assert set(result.metrics) == {"rmse", "mae", "r2"}
    assert result.metrics["rmse"] > 0
    assert result.model is not None
    assert result.error is None


@pytest.mark.parametrize("model_type", CLASSIFIERS)
def test_every_classifier_fits_and_scores(model_type):
    result = fit_and_score(model_type, {}, make_labels(), "direction", ["memory"], None)
    assert result.status == "FINISHED"
    assert set(result.metrics) == {"accuracy", "f1_macro", "precision_macro", "recall_macro"}
    assert 0.0 <= result.metrics["f1_macro"] <= 1.0


def test_every_registry_entry_declares_a_coherent_direction():
    # The review's point 3: a maximising metric under a minimising study
    # silently selects the worst model. Assert the pairing, do not trust it.
    for name, spec in MODEL_REGISTRY.items():
        assert spec.task_type in {"regression", "classification"}, name
        assert spec.direction in {"minimize", "maximize"}, name
        if spec.task_type == "regression":
            assert spec.direction == "minimize", name
        else:
            assert spec.direction == "maximize", name


def test_fit_is_deterministic():
    args = ("random_forest", {}, make_frame(), "price", ["memory", "chipset"], None)
    assert fit_and_score(*args).metrics == fit_and_score(*args).metrics


def test_unknown_model_type_fails_without_raising():
    result = fit_and_score("nope", {}, make_frame(), "price", ["memory"], None)
    assert result.status == "FAILED"
    assert result.metrics == {}
    assert result.model is None
    assert "nope" in (result.error or "")


def test_bad_hyperparams_fail_without_raising():
    result = fit_and_score(
        "random_forest", {"n_estimators": -5}, make_frame(), "price", ["memory"], None
    )
    assert result.status == "FAILED"
    assert result.error


def test_unseen_category_at_predict_time_does_not_crash():
    df = make_frame(60)
    df.loc[df.index[-5:], "chipset"] = "rare"
    result = fit_and_score("ridge", {}, df, "price", ["memory", "chipset"], None)
    assert result.status == "FINISHED"


def test_cv_objective_returns_a_mean_and_a_std():
    mean, std = cv_objective("ridge", {}, make_frame(), "price", ["memory", "chipset"], None)
    assert mean > 0
    assert std >= 0


def test_cv_objective_is_positive_for_a_maximising_classifier():
    mean, _ = cv_objective("logistic_regression", {}, make_labels(), "direction", ["memory"], None)
    assert 0.0 <= mean <= 1.0
