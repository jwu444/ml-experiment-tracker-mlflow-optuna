"""Residual and learning-curve frames for a fitted run (2b.2).

Two pure functions. Neither loads anything, calls an LLM, nor touches the
database — each takes an already-loaded pipeline and returns a DataFrame.

**Why both return frames.** `charts.py:_DISPATCH` hands tools a dict of
DataFrames and nothing else; a tool has no route to a fitted estimator.
Computing here and handing the loop a frame keeps every tool a pure function of
a DataFrame, which is the property that makes the whole chart layer testable.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import learning_curve

from app import training


def residual_frame(
    model: Any,
    frame: pd.DataFrame,
    target_column: str,
    feature_columns: list[str],
    time_column: str | None,
    id_columns: Sequence[str] = (),
) -> pd.DataFrame:
    """Actual vs. predicted on the run's own holdout, plus identifying columns.

    The split is re-derived with `training.split_frame` rather than re-cut here,
    so the rows scored are identical to the rows the run was scored on. A
    diagnostic computed on a different split is plausible-looking and wrong.

    Temporal runs additionally get `time_index`, a numeric ordinal of the
    holdout in time order, because `line` will not accept the (string) time
    column itself. See the comment at the bottom of this function.
    """
    x, y = training.prepare(frame, target_column, feature_columns, time_column)
    _, x_test, _, y_test = training.split_frame(x, y, chronological=time_column is not None)
    predicted = np.asarray(model.predict(x_test), dtype=float)

    out = pd.DataFrame(
        {"actual": y_test.to_numpy(dtype=float), "predicted": predicted},
        index=x_test.index,
    )
    out["residual"] = out["actual"] - out["predicted"]
    out["abs_error"] = out["residual"].abs()
    # Re-attached by INDEX, not by position: `prepare` sorts by time, so a
    # positional join against the original frame mislabels every row.
    wanted = [*id_columns, *([time_column] if time_column else [])]
    for column in wanted:
        if column in frame.columns:
            out[column] = frame.loc[out.index, column]

    # `line` requires a NUMERIC x (see tools.validate_tool_call), but `load_csv`
    # is a bare `read_csv` with no date parsing, so the time column arrives as
    # object dtype and the drift question the diagnostic prompt asks is the one
    # axis the tool would reject. `time_index` is an ordinal companion — the
    # 0-based rank of these rows in sorted time order — that gives the analyst a
    # plottable x without touching `line` or its validator. The real time column
    # stays alongside it so the stats and sample rows still show actual dates.
    #
    # Only emitted when there IS a time column: a random split has no meaningful
    # row ordering, and a fake one would invite drift claims about noise.
    if time_column is not None and time_column in out.columns:
        order = np.argsort(out[time_column].to_numpy(), kind="stable")
        ranks = np.empty(len(order), dtype=int)
        ranks[order] = np.arange(len(order))
        out["time_index"] = ranks
    return out.reset_index(drop=True)


def learning_curve_frame(
    model: Any,
    frame: pd.DataFrame,
    target_column: str,
    feature_columns: list[str],
    time_column: str | None,
    scoring: str = "neg_root_mean_squared_error",
) -> pd.DataFrame:
    """One row per training size: train_size, train_score, validation_score.

    Uses the same `cv_splitter` the run was scored with, so a temporal run gets
    `TimeSeriesSplit`. Scores are returned in the metric's natural orientation
    (lower rmse is better), so the "neg_" sign is undone here.
    """
    chronological = time_column is not None
    x, y = training.prepare(frame, target_column, feature_columns, time_column)
    x_train, _, y_train, _ = training.split_frame(x, y, chronological=chronological)
    sizes, train_scores, validation_scores = learning_curve(
        model,
        x_train,
        y_train,
        cv=training.cv_splitter(chronological),
        scoring=scoring,
        train_sizes=np.linspace(0.3, 1.0, 5),
        shuffle=False,
    )
    sign = -1.0 if scoring.startswith("neg_") else 1.0
    return pd.DataFrame(
        {
            "train_size": sizes.astype(float),
            "train_score": sign * train_scores.mean(axis=1),
            "validation_score": sign * validation_scores.mean(axis=1),
        }
    )
