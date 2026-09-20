from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

import pandas as pd
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (
    GradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    precision_score,
    r2_score,
    recall_score,
    root_mean_squared_error,
)
from sklearn.model_selection import KFold, TimeSeriesSplit, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from app.config import settings

# One search-space entry: (kind, low, high, log). `kind` is "int" or "float".
SearchSpace = dict[str, tuple[str, float, float, bool]]


@dataclass(frozen=True)
class ModelSpec:
    """One registered model.

    `objective_metric` and `direction` are per entry, never global: a maximising
    metric optimised by a minimising study picks the worst model and says
    nothing about it (design review, point 3).
    """

    task_type: str  # "regression" | "classification"
    factory: Callable[..., Any]
    search_space: SearchSpace
    objective_metric: str  # the key in `metrics` this model is ranked on
    direction: str  # "minimize" | "maximize" — must agree with cv_scoring
    cv_scoring: str  # an sklearn scorer name for cross_val_score
    # Hyperparameters whose value is a COLUMN NAME rather than a number, and
    # which the estimator needs before it can fit at all. They are absent from
    # `search_space` because there is nothing to search over — but a caller that
    # omits one gets a FAILED run, so a form has to ask for them. Naming them
    # here keeps that knowledge in the registry: the alternative is a frontend
    # that special-cases a model by name, which is how #51 happened.
    column_hyperparams: tuple[str, ...] = ()
    # When False, build_pipeline returns a bare Pipeline([("model", ...)]) and
    # the estimator receives the DataFrame with its column names intact. Only
    # the persistence baseline needs this: inside the standard pipeline it would
    # receive a SCALED prior value and could never emit raw dollars — the
    # baseline would be silently wrong rather than fail (D25).
    preprocess: bool = True


@dataclass(frozen=True)
class TrainResult:
    status: str  # "FINISHED" | "FAILED"
    metrics: dict[str, float]
    params: dict[str, Any]
    error: str | None
    model: Any | None


class PriorValueRegressor(BaseEstimator, RegressorMixin):  # type: ignore[misc]
    """Predicts next period's value as this period's: `revenue_next = revenue`.

    A real estimator rather than a number computed in a notebook, so the
    baseline is a logged run on the leaderboard that any model must beat before
    it is worth reporting (D25). `prior_column` arrives through the existing
    `hyperparams` dict, so no request field is added.
    """

    def __init__(self, prior_column: str = "") -> None:
        # sklearn's clone() requires __init__ params to be stored unmodified
        # under their own names. Anything else here breaks cross_val_score.
        self.prior_column = prior_column

    def fit(self, X: pd.DataFrame, y: Any = None) -> PriorValueRegressor:  # noqa: N803
        if self.prior_column not in X.columns:
            raise ValueError(
                f"prior_column {self.prior_column!r} is not among the feature columns "
                f"{sorted(X.columns)}"
            )
        self.is_fitted_ = True
        return self

    def predict(self, X: pd.DataFrame) -> Any:  # noqa: N803
        return X[self.prior_column].to_numpy(dtype=float)


# Each entry carries the estimator, its search space, AND how it is scored, so
# /train, /tune, and the Optuna study can never disagree about any of the three.
MODEL_REGISTRY: dict[str, ModelSpec] = {
    "ridge": ModelSpec(
        task_type="regression",
        factory=Ridge,
        search_space={"alpha": ("float", 1e-3, 1e3, True)},
        objective_metric="rmse",
        direction="minimize",
        cv_scoring="neg_root_mean_squared_error",
    ),
    "random_forest": ModelSpec(
        task_type="regression",
        factory=RandomForestRegressor,
        search_space={
            "n_estimators": ("int", 50, 400, False),
            "max_depth": ("int", 2, 20, False),
            "min_samples_leaf": ("int", 1, 10, False),
        },
        objective_metric="rmse",
        direction="minimize",
        cv_scoring="neg_root_mean_squared_error",
    ),
    "gradient_boosting": ModelSpec(
        task_type="regression",
        factory=GradientBoostingRegressor,
        search_space={
            "n_estimators": ("int", 50, 400, False),
            "learning_rate": ("float", 1e-3, 0.3, True),
            "max_depth": ("int", 2, 8, False),
        },
        objective_metric="rmse",
        direction="minimize",
        cv_scoring="neg_root_mean_squared_error",
    ),
    "logistic_regression": ModelSpec(
        task_type="classification",
        factory=LogisticRegression,
        search_space={"C": ("float", 1e-3, 1e2, True)},
        objective_metric="f1_macro",
        direction="maximize",
        cv_scoring="f1_macro",
    ),
    "random_forest_clf": ModelSpec(
        task_type="classification",
        factory=RandomForestClassifier,
        search_space={
            "n_estimators": ("int", 50, 400, False),
            "max_depth": ("int", 2, 20, False),
            "min_samples_leaf": ("int", 1, 10, False),
        },
        objective_metric="f1_macro",
        direction="maximize",
        cv_scoring="f1_macro",
    ),
    # Scoped to the temporal panel: predicting "next quarter equals this
    # quarter" is meaningless on the cross-sectional components dataset, and
    # nothing forces a caller to fit it there.
    "persistence": ModelSpec(
        task_type="regression",
        factory=PriorValueRegressor,
        search_space={},  # nothing to tune; /tune rejects it rather than running duplicates
        column_hyperparams=("prior_column",),
        objective_metric="rmse",
        direction="minimize",
        cv_scoring="neg_root_mean_squared_error",
        preprocess=False,
    ),
}


def prepare(
    df: pd.DataFrame, target: str, features: list[str], time_column: str | None
) -> tuple[pd.DataFrame, pd.Series]:
    """Select features and target, dropping rows with a null target.

    When `time_column` is given, rows are sorted by it and the column itself is
    excluded from the features — it is the split axis, not a predictor. Sorting
    here (rather than trusting the CSV) is what makes `split_frame` and
    `cv_splitter` correct no matter how the file arrived.
    """
    if target not in df.columns:
        raise ValueError(f"target column {target!r} is not in the dataset")
    if time_column is not None and time_column not in df.columns:
        raise ValueError(f"time column {time_column!r} is not in the dataset")
    features = [f for f in features if f != time_column]
    # Both of these otherwise select the same column twice, and the failure
    # surfaces much later as sklearn's "DuplicateError: Expected unique column
    # names", which names neither the target nor the duplicate. /train takes
    # `features` from the request body, so catch it here where the message can
    # still say what the caller did wrong.
    if target in features:
        raise ValueError(f"target column {target!r} cannot also be a feature")
    duplicates = sorted({f for f in features if features.count(f) > 1})
    if duplicates:
        raise ValueError(f"duplicate feature columns: {duplicates}")
    missing = [f for f in features if f not in df.columns]
    if missing:
        raise ValueError(f"feature columns not in the dataset: {missing}")

    keep = [*features, target] if time_column is None else [*features, target, time_column]
    frame = df[keep].dropna(subset=[target])
    if time_column is not None:
        frame = frame.sort_values(time_column, kind="stable").drop(columns=[time_column])
    if frame.empty:
        raise ValueError(f"no rows have a non-null {target!r}")
    return frame[features], frame[target]


def split_frame(
    x: pd.DataFrame, y: pd.Series, chronological: bool
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    """Holdout split. Chronological means the test set is the LATEST rows.

    `prepare` has already sorted by time, so the cut is a positional slice.
    """
    if chronological:
        cut = int(len(x) * (1 - settings.train_test_size))
        return x.iloc[:cut], x.iloc[cut:], y.iloc[:cut], y.iloc[cut:]
    # train_test_split is untyped (returns list[Any]); the split of a DataFrame
    # and a Series is these four in this order.
    return cast(
        "tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]",
        tuple(
            train_test_split(
                x, y, test_size=settings.train_test_size, random_state=settings.train_test_seed
            )
        ),
    )


def cv_splitter(chronological: bool) -> TimeSeriesSplit | KFold:
    """Expanding-window CV for time series, shuffled k-fold otherwise.

    `TimeSeriesSplit` never puts a later row in a fold used to train for an
    earlier one, which is the whole point.
    """
    if chronological:
        return TimeSeriesSplit(n_splits=settings.cv_folds)
    return KFold(n_splits=settings.cv_folds, shuffle=True, random_state=settings.train_test_seed)


def _column_kinds(x: pd.DataFrame) -> tuple[list[str], list[str]]:
    numeric = [c for c in x.columns if pd.api.types.is_numeric_dtype(x[c])]
    return numeric, [c for c in x.columns if c not in numeric]


def build_pipeline(
    model_type: str, hyperparams: dict[str, Any], numeric: list[str], categorical: list[str]
) -> Pipeline:
    if model_type not in MODEL_REGISTRY:
        raise ValueError(f"unknown model_type {model_type!r}; known: {sorted(MODEL_REGISTRY)}")
    spec = MODEL_REGISTRY[model_type]
    estimator = spec.factory(**hyperparams)
    # Seed anything stochastic (the forests, gradient boosting's subsampling) so
    # re-running an experiment reproduces its metrics — otherwise two rows in the
    # MLflow history differ by noise and the comparison Phase 3 retrieves is
    # meaningless. An explicit random_state in hyperparams still wins.
    if "random_state" in estimator.get_params() and "random_state" not in hyperparams:
        estimator.set_params(random_state=settings.train_test_seed)
    if not spec.preprocess:
        # The estimator reads named columns off the DataFrame itself (D25).
        return Pipeline([("model", estimator)])
    # Scaling lives INSIDE the pipeline so cross_val_score refits it per fold.
    # Scaling before the split fits the scaler on the test rows — a quiet leak
    # that no metric reveals (design §3.6).
    # sparse_output=False keeps the matrix dense: at these row counts the memory
    # cost is nil, and every estimator accepts it without a sparse-support caveat.
    pre = ColumnTransformer(
        [
            (
                "num",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="median")),
                        ("scale", StandardScaler()),
                    ]
                ),
                numeric,
            ),
            (
                "cat",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        ("ohe", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
                    ]
                ),
                categorical,
            ),
        ],
        remainder="drop",
    )
    return Pipeline([("pre", pre), ("model", estimator)])


def _score(task_type: str, y_true: Any, pred: Any) -> dict[str, float]:
    if task_type == "regression":
        return {
            "rmse": float(root_mean_squared_error(y_true, pred)),
            "mae": float(mean_absolute_error(y_true, pred)),
            "r2": float(r2_score(y_true, pred)),
        }
    return {
        "accuracy": float(accuracy_score(y_true, pred)),
        "f1_macro": float(f1_score(y_true, pred, average="macro", zero_division=0)),
        "precision_macro": float(precision_score(y_true, pred, average="macro", zero_division=0)),
        "recall_macro": float(recall_score(y_true, pred, average="macro", zero_division=0)),
    }


def fit_and_score(
    model_type: str,
    hyperparams: dict[str, Any],
    df: pd.DataFrame,
    target: str,
    features: list[str],
    time_column: str | None = None,
) -> TrainResult:
    """Fit on the train split, score on the held-out test split.

    When `time_column` is given the split is chronological: the test set is the
    latest rows, never a random sample. Never raises — a bad model_type or bad
    hyperparams come back as status="FAILED" so the caller can still record the
    failure as history (§8).
    """
    try:
        if model_type not in MODEL_REGISTRY:
            raise ValueError(f"unknown model_type {model_type!r}; known: {sorted(MODEL_REGISTRY)}")
        spec = MODEL_REGISTRY[model_type]
        x, y = prepare(df, target, features, time_column)
        numeric, categorical = _column_kinds(x)
        pipeline = build_pipeline(model_type, hyperparams, numeric, categorical)
        x_train, x_test, y_train, y_test = split_frame(x, y, chronological=time_column is not None)
        pipeline.fit(x_train, y_train)
        pred = pipeline.predict(x_test)
        return TrainResult(
            "FINISHED", _score(spec.task_type, y_test, pred), dict(hyperparams), None, pipeline
        )
    except Exception as exc:  # noqa: BLE001 — failures are data, not crashes (§8)
        return TrainResult("FAILED", {}, dict(hyperparams), f"{type(exc).__name__}: {exc}", None)


def cv_objective(
    model_type: str,
    hyperparams: dict[str, Any],
    df: pd.DataFrame,
    target: str,
    features: list[str],
    time_column: str | None = None,
) -> tuple[float, float]:
    """Cross-validated score on the TRAIN split only, as (mean, std).

    Optuna optimises this, never the test split — tuning against the split you
    then report is not a measurement. The std comes back with it because a
    ~180-row train split cannot separate two models on a point estimate
    (Global Constraints); Task 7 logs it as `cv_std` beside the mean.

    The sign is normalised here: sklearn's `neg_*` scorers are higher-is-better,
    so a "neg_" prefix means the raw score must be negated to recover the metric
    the registry's `direction` refers to.
    """
    if model_type not in MODEL_REGISTRY:
        raise ValueError(f"unknown model_type {model_type!r}; known: {sorted(MODEL_REGISTRY)}")
    spec = MODEL_REGISTRY[model_type]
    chronological = time_column is not None
    x, y = prepare(df, target, features, time_column)
    numeric, categorical = _column_kinds(x)
    x_train, _, y_train, _ = split_frame(x, y, chronological=chronological)
    pipeline = build_pipeline(model_type, hyperparams, numeric, categorical)
    scores = cross_val_score(
        pipeline,
        x_train,
        y_train,
        cv=cv_splitter(chronological),
        scoring=spec.cv_scoring,
    )
    if spec.cv_scoring.startswith("neg_"):
        scores = -scores
    return float(scores.mean()), float(scores.std())


def infer_feature_columns(
    df: pd.DataFrame,
    target: str,
    max_cardinality: int,
    time_column: str | None = None,
) -> list[str]:
    """Pick features from the DataFrame itself (design §3.3).

    Numeric columns, plus categoricals at or below `max_cardinality` distinct
    values. Excluded: the target, the time column, anything datetime-like, and
    high-cardinality text — an identifier one-hot-encodes into one column per
    row, which is memorisation, not a feature.

    Deliberately NOT driven by `datasets.profile_json`: that structure carries
    no per-column cardinality (`app/profiler.py:46` emits name/dtype/n_null
    only), and its `categorical_summary` is emptied whenever the profile
    degrades past its token budget.
    """
    if target not in df.columns:
        raise ValueError(f"target column {target!r} is not in the dataset")
    features: list[str] = []
    for name in df.columns:
        if name == target or name == time_column:
            continue
        series = df[name]
        if pd.api.types.is_datetime64_any_dtype(series):
            continue
        if pd.api.types.is_bool_dtype(series):
            features.append(str(name))
            continue
        if pd.api.types.is_numeric_dtype(series):
            features.append(str(name))
            continue
        if series.nunique(dropna=True) <= max_cardinality:
            features.append(str(name))
    if not features:
        raise ValueError(f"no usable feature columns for target {target!r}")
    return features
