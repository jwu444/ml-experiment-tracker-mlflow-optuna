import base64
import json

import pandas as pd
from app import analysis
from app.analysis import compare, correlation_matrix, histogram, scatter


def _df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "age": [20, 30, 40, 50, 60],
            "score": [1.0, 2.0, 3.0, 4.0, 5.0],
            "city": ["A", "B", "A", "B", "C"],
        }
    )


def _is_png_base64(s: str) -> bool:
    raw = base64.b64decode(s)
    return raw[:8] == b"\x89PNG\r\n\x1a\n"


def test_histogram_returns_png_and_stats() -> None:
    png, stats = histogram(_df(), "age")
    assert _is_png_base64(png)
    assert stats["column"] == "age"
    assert stats["count"] == 5
    assert stats["min"] == 20
    assert stats["max"] == 60


def test_scatter_returns_png_and_correlation() -> None:
    png, stats = scatter(_df(), "age", "score")
    assert _is_png_base64(png)
    assert stats["x"] == "age"
    assert stats["y"] == "score"
    assert round(stats["correlation"], 5) == 1.0


def test_correlation_matrix_returns_png_and_pairs() -> None:
    png, stats = correlation_matrix(_df())
    assert _is_png_base64(png)
    assert set(stats["columns"]) == {"age", "score"}
    assert round(stats["matrix"]["age"]["score"], 5) == 1.0


def test_histogram_single_value_std_is_none() -> None:
    _png, stats = histogram(pd.DataFrame({"x": [5.0]}), "x")
    assert stats["std"] is None
    json.dumps(stats, allow_nan=False)  # must not raise


def test_scatter_constant_column_correlation_is_none() -> None:
    df = pd.DataFrame({"a": [1, 2, 3], "b": [7, 7, 7]})
    _png, stats = scatter(df, "a", "b")
    assert stats["correlation"] is None
    json.dumps(stats, allow_nan=False)


def test_correlation_matrix_constant_column_has_no_nan() -> None:
    df = pd.DataFrame({"a": [1, 2, 3], "b": [7, 7, 7]})
    _png, stats = correlation_matrix(df)
    assert stats["matrix"]["a"]["b"] is None
    json.dumps(stats, allow_nan=False)


def test_compare_joins_and_aggregates() -> None:
    df_a = pd.DataFrame({"region": ["east", "east", "west"], "revenue": [10, 20, 5]})
    df_b = pd.DataFrame({"region": ["east", "west", "west"], "revenue": [100, 200, 300]})
    png, stats = compare(df_a, df_b, "region", "region", "revenue", "revenue", "mean")
    assert _is_png_base64(png)
    rows_by_key = {r["key"]: r for r in stats["rows"]}
    assert rows_by_key["east"]["a"] == 15.0
    assert rows_by_key["east"]["b"] == 100.0
    assert rows_by_key["west"]["a"] == 5.0
    assert rows_by_key["west"]["b"] == 250.0


def test_compare_sum_agg() -> None:
    df_a = pd.DataFrame({"k": ["x", "x"], "v": [1, 2]})
    df_b = pd.DataFrame({"k": ["x"], "v": [10]})
    _png, stats = compare(df_a, df_b, "k", "k", "v", "v", "sum")
    assert stats["rows"] == [{"key": "x", "a": 3.0, "b": 10.0}]


def test_compare_only_matching_keys_included() -> None:
    df_a = pd.DataFrame({"k": ["x", "y"], "v": [1, 2]})
    df_b = pd.DataFrame({"k": ["x", "z"], "v": [10, 20]})
    _png, stats = compare(df_a, df_b, "k", "k", "v", "v", "mean")
    assert {r["key"] for r in stats["rows"]} == {"x"}


def test_error_by_group_returns_png_and_per_group_means() -> None:
    df = pd.DataFrame(
        {
            "ticker": ["AAPL", "AAPL", "MSFT", "MSFT"],
            "abs_error": [1.0, 3.0, 10.0, 20.0],
        }
    )
    png, stats = analysis.error_by_group(df, "ticker", "abs_error")
    assert png  # base64 payload, non-empty
    assert stats["group_column"] == "ticker"
    assert stats["groups"]["AAPL"] == 2.0
    assert stats["groups"]["MSFT"] == 15.0
    assert stats["worst_group"] == "MSFT"


def test_error_by_group_ignores_rows_with_a_null_error() -> None:
    df = pd.DataFrame({"g": ["a", "a", "b"], "e": [2.0, None, 4.0]})
    _, stats = analysis.error_by_group(df, "g", "e")
    assert stats["groups"]["a"] == 2.0
    assert stats["n"] == 2


def test_line_plots_multiple_series_against_a_shared_x() -> None:
    df = pd.DataFrame(
        {
            "train_size": [10, 20, 30],
            "train_score": [5.0, 4.0, 3.5],
            "validation_score": [9.0, 8.0, 7.5],
        }
    )
    png, stats = analysis.line(df, "train_size", ["train_score", "validation_score"])
    assert png
    assert stats["x_column"] == "train_size"
    assert stats["series"]["train_score"]["last"] == 3.5
    assert stats["series"]["validation_score"]["last"] == 7.5
    assert stats["n"] == 3


def test_line_sorts_by_x_so_the_connecting_line_is_meaningful() -> None:
    """An unordered frame drawn as a line plot produces a zigzag that reads as
    instability in the data rather than in the row order."""
    df = pd.DataFrame({"x": [3, 1, 2], "y": [30.0, 10.0, 20.0]})
    _, stats = analysis.line(df, "x", ["y"])
    assert stats["series"]["y"]["first"] == 10.0
    assert stats["series"]["y"]["last"] == 30.0
