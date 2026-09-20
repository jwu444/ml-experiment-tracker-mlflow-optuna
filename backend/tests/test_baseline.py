import numpy as np
import pandas as pd
import pytest
from app import training


def _panel() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "quarter_end": pd.date_range("2015-03-31", periods=40, freq="QE").astype(str),
            "ticker": ["AAPL", "MSFT"] * 20,
            "revenue": np.arange(40, dtype=float) * 100.0,
            "revenue_next": np.arange(40, dtype=float) * 100.0 + 50.0,
        }
    )


def test_persistence_is_registered_as_a_regression_model() -> None:
    spec = training.MODEL_REGISTRY["persistence"]
    assert spec.task_type == "regression"
    assert spec.objective_metric == "rmse"
    assert spec.direction == "minimize"
    assert spec.preprocess is False


def test_persistence_search_space_is_empty_so_tuning_is_meaningless() -> None:
    assert training.MODEL_REGISTRY["persistence"].search_space == {}


def test_prior_value_regressor_predicts_the_prior_column_unchanged() -> None:
    """Tested THROUGH the pipeline, not in isolation — that is what catches a
    regression if anyone flips `preprocess` back to the default. Inside the
    standard pipeline the estimator would receive a SCALED prior value and could
    never emit raw dollars; the baseline would be silently wrong, not fail."""
    pipeline = training.build_pipeline(
        "persistence", {"prior_column": "revenue"}, ["revenue"], ["ticker"]
    )
    x = pd.DataFrame({"revenue": [100.0, 200.0, 300.0], "ticker": ["A", "B", "A"]})
    y = pd.Series([150.0, 250.0, 350.0])
    pipeline.fit(x, y)
    assert pipeline.predict(x).tolist() == [100.0, 200.0, 300.0]


def test_persistence_pipeline_has_no_preprocessing_step() -> None:
    pipeline = training.build_pipeline("persistence", {"prior_column": "revenue"}, ["revenue"], [])
    assert [name for name, _ in pipeline.steps] == ["model"]


def test_other_models_keep_their_preprocessing_step() -> None:
    pipeline = training.build_pipeline("ridge", {}, ["revenue"], ["ticker"])
    assert [name for name, _ in pipeline.steps] == ["pre", "model"]


def test_persistence_is_clonable_so_cross_val_score_works() -> None:
    from sklearn.base import clone

    estimator = training.PriorValueRegressor(prior_column="revenue")
    assert clone(estimator).get_params()["prior_column"] == "revenue"


def test_persistence_scores_end_to_end_through_fit_and_score() -> None:
    result = training.fit_and_score(
        "persistence",
        {"prior_column": "revenue"},
        _panel(),
        "revenue_next",
        ["revenue", "ticker"],
        "quarter_end",
    )
    assert result.status == "FINISHED"
    # revenue_next is always revenue + 50, so persistence is off by exactly 50.
    assert result.metrics["rmse"] == pytest.approx(50.0)
    assert result.metrics["mae"] == pytest.approx(50.0)


def test_persistence_with_an_unknown_prior_column_fails_as_data_not_a_crash() -> None:
    result = training.fit_and_score(
        "persistence",
        {"prior_column": "nope"},
        _panel(),
        "revenue_next",
        ["revenue"],
        "quarter_end",
    )
    assert result.status == "FAILED"
    assert "nope" in (result.error or "")
