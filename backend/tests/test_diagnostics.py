import numpy as np
import pandas as pd
from app import diagnostics, training


def _panel() -> pd.DataFrame:
    """40 rows, two tickers, a clean linear relationship and a time axis."""
    return pd.DataFrame(
        {
            "quarter_end": pd.date_range("2015-03-31", periods=40, freq="QE").astype(str),
            "ticker": ["AAPL", "MSFT"] * 20,
            "revenue": np.arange(40, dtype=float) * 100.0,
            "revenue_next": np.arange(40, dtype=float) * 100.0 + 50.0,
        }
    )


def _fitted(frame, features, time_column="quarter_end"):
    x, y = training.prepare(frame, "revenue_next", features, time_column)
    pipeline = training.build_pipeline("ridge", {}, ["revenue"], ["ticker"])
    x_train, _, y_train, _ = training.split_frame(x, y, chronological=time_column is not None)
    pipeline.fit(x_train, y_train)
    return pipeline


def test_residual_frame_scores_exactly_the_rows_split_frame_held_out() -> None:
    """The assertion that matters. A diagnostic computed on the wrong split is
    entirely plausible-looking and completely wrong."""
    frame = _panel()
    features = ["revenue", "ticker"]
    model = _fitted(frame, features)
    x, y = training.prepare(frame, "revenue_next", features, "quarter_end")
    _, x_test, _, y_test = training.split_frame(x, y, chronological=True)

    out = diagnostics.residual_frame(
        model, frame, "revenue_next", features, "quarter_end", id_columns=("ticker",)
    )
    assert len(out) == len(x_test)
    assert out["actual"].tolist() == y_test.tolist()


def test_residual_frame_columns_and_arithmetic() -> None:
    frame = _panel()
    features = ["revenue", "ticker"]
    out = diagnostics.residual_frame(
        _fitted(frame, features),
        frame,
        "revenue_next",
        features,
        "quarter_end",
        id_columns=("ticker",),
    )
    for column in ("actual", "predicted", "residual", "abs_error", "ticker", "quarter_end"):
        assert column in out.columns
    assert np.allclose(out["residual"], out["actual"] - out["predicted"])
    assert (out["abs_error"] >= 0).all()


def test_residual_frame_carries_identifiers_from_the_right_rows() -> None:
    """Identifiers are re-attached by index, not by position — a positional
    join against a time-sorted frame silently mislabels every row."""
    frame = _panel()
    features = ["revenue", "ticker"]
    out = diagnostics.residual_frame(
        _fitted(frame, features),
        frame,
        "revenue_next",
        features,
        "quarter_end",
        id_columns=("ticker",),
    )
    assert set(out["ticker"]) <= {"AAPL", "MSFT"}
    # The holdout is the tail of the time-sorted frame, so its quarter_end
    # values must all be later than the training rows'.
    assert out["quarter_end"].min() > frame["quarter_end"].sort_values().iloc[0]


def test_residual_frame_emits_a_numeric_time_index_in_sorted_time_order() -> None:
    """`line` rejects a non-numeric x, and `quarter_end` loads as a string, so a
    temporal run needs an ordinal companion or the drift question is unanswerable."""
    # Shuffled deliberately: if `time_index` were merely the output row position
    # it would still look right on an already-sorted frame.
    frame = _panel().sample(frac=1.0, random_state=0).reset_index(drop=True)
    features = ["revenue", "ticker"]
    out = diagnostics.residual_frame(
        _fitted(frame, features),
        frame,
        "revenue_next",
        features,
        "quarter_end",
        id_columns=("ticker",),
    )

    assert "time_index" in out.columns
    # Numeric is the whole point — this is what makes it a legal `line` x_column.
    assert pd.api.types.is_numeric_dtype(out["time_index"])
    # A dense 0-based ordinal over the holdout.
    assert sorted(out["time_index"]) == list(range(len(out)))
    # The ordering is the real claim: ranked by time_index, the actual dates must
    # come out in ascending order.
    by_index = out.sort_values("time_index")
    assert by_index["quarter_end"].is_monotonic_increasing
    assert by_index["quarter_end"].iloc[0] == out["quarter_end"].min()
    assert by_index["quarter_end"].iloc[-1] == out["quarter_end"].max()
    # The real time column survives alongside it, so stats and sample rows still
    # show dates rather than only an opaque ordinal.
    assert out["quarter_end"].dtype == object


def test_residual_frame_omits_time_index_when_the_split_is_random() -> None:
    """A random split has no meaningful row ordering; inventing one would invite
    drift conclusions drawn from noise."""
    frame = _panel()
    features = ["revenue", "ticker"]
    out = diagnostics.residual_frame(
        _fitted(frame, features, time_column=None),
        frame,
        "revenue_next",
        features,
        None,
        id_columns=("ticker",),
    )
    assert "time_index" not in out.columns


def test_learning_curve_frame_shape_and_monotonic_train_size() -> None:
    frame = _panel()
    features = ["revenue", "ticker"]
    out = diagnostics.learning_curve_frame(
        _fitted(frame, features), frame, "revenue_next", features, "quarter_end"
    )
    assert list(out.columns) == ["train_size", "train_score", "validation_score"]
    assert len(out) >= 3
    assert out["train_size"].is_monotonic_increasing


def test_learning_curve_frame_uses_timeseriessplit_when_time_column_given(monkeypatch) -> None:
    """A learning curve built on shuffled folds for a temporal run reports
    optimistic scores at every training size."""
    from sklearn.model_selection import TimeSeriesSplit

    seen = {}
    real = training.cv_splitter

    def spy(chronological):
        seen["chronological"] = chronological
        return real(chronological)

    monkeypatch.setattr(diagnostics.training, "cv_splitter", spy)
    frame = _panel()
    features = ["revenue", "ticker"]
    diagnostics.learning_curve_frame(
        _fitted(frame, features), frame, "revenue_next", features, "quarter_end"
    )
    assert seen["chronological"] is True
    assert isinstance(real(True), TimeSeriesSplit)


def test_learning_curve_frame_is_random_split_without_a_time_column() -> None:
    frame = _panel().drop(columns=["quarter_end"])
    features = ["revenue", "ticker"]
    model = _fitted(frame, features, time_column=None)
    out = diagnostics.learning_curve_frame(model, frame, "revenue_next", features, None)
    assert len(out) >= 3
