"""Chart/stat engine. Renders on a fresh matplotlib Agg Figure per call and
never touches pyplot global state (not thread-safe under FastAPI)."""

from __future__ import annotations

import base64
import io
from typing import Any

import matplotlib
import numpy as np

matplotlib.use("Agg")  # headless backend; must precede Figure import usage

import pandas as pd  # noqa: E402
import seaborn as sns  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402


def _nan_to_none(value: Any) -> float | None:
    """Undefined statistics (NaN — e.g. std/correlation of a constant column)
    must serialize as JSON null, not the non-JSON-compliant NaN token."""
    return float(value) if pd.notna(value) else None


def _fig_to_base64(fig: Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=100)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def histogram(df: pd.DataFrame, column: str) -> tuple[str, dict[str, Any]]:
    series = pd.to_numeric(df[column], errors="coerce").dropna()
    fig = Figure(figsize=(6, 4))
    try:
        ax = fig.subplots()
        ax.hist(series, bins=min(30, max(1, series.nunique())), color="#4C72B0")
        ax.set_title(f"Distribution of {column}")
        ax.set_xlabel(column)
        ax.set_ylabel("count")
        png = _fig_to_base64(fig)
    finally:
        fig.clear()
    stats: dict[str, Any] = {
        "column": column,
        "count": int(series.count()),
        "min": _nan_to_none(series.min()),
        "max": _nan_to_none(series.max()),
        "mean": _nan_to_none(series.mean()),
        "std": _nan_to_none(series.std()),
    }
    return png, stats


def scatter(df: pd.DataFrame, x: str, y: str) -> tuple[str, dict[str, Any]]:
    sub = df[[x, y]].apply(pd.to_numeric, errors="coerce").dropna()
    fig = Figure(figsize=(6, 4))
    try:
        ax = fig.subplots()
        ax.scatter(sub[x], sub[y], alpha=0.7, color="#4C72B0")
        ax.set_title(f"{y} vs {x}")
        ax.set_xlabel(x)
        ax.set_ylabel(y)
        png = _fig_to_base64(fig)
    finally:
        fig.clear()
    with np.errstate(invalid="ignore", divide="ignore"):
        corr_value = sub[x].corr(sub[y])
    corr = _nan_to_none(corr_value)
    stats: dict[str, Any] = {"x": x, "y": y, "count": int(len(sub)), "correlation": corr}
    return png, stats


def correlation_matrix(df: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    numeric = df.select_dtypes(include="number")
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = numeric.corr()
    fig = Figure(figsize=(6, 5))
    try:
        ax = fig.subplots()
        sns.heatmap(corr, annot=True, fmt=".2f", cmap="coolwarm", vmin=-1, vmax=1, ax=ax)
        ax.set_title("Correlation matrix")
        png = _fig_to_base64(fig)
    finally:
        fig.clear()
    stats: dict[str, Any] = {
        "columns": list(corr.columns),
        "matrix": {c: {r: _nan_to_none(corr.loc[r, c]) for r in corr.index} for c in corr.columns},
    }
    return png, stats


def compare(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    key_a: str,
    key_b: str,
    metric_a: str,
    metric_b: str,
    agg: str,
) -> tuple[str, dict[str, Any]]:
    left = df_a[[key_a, metric_a]].copy()
    left[metric_a] = pd.to_numeric(left[metric_a], errors="coerce")
    right = df_b[[key_b, metric_b]].copy()
    right[metric_b] = pd.to_numeric(right[metric_b], errors="coerce")

    left_agg = left.groupby(key_a)[metric_a].agg(agg)
    right_agg = right.groupby(key_b)[metric_b].agg(agg)
    joined = pd.concat({"a": left_agg, "b": right_agg}, axis=1, join="inner")

    fig = Figure(figsize=(6, 4))
    try:
        ax = fig.subplots()
        x = np.arange(len(joined))
        width = 0.35
        ax.bar(x - width / 2, joined["a"], width, label=f"A: {metric_a}", color="#4C72B0")
        ax.bar(x + width / 2, joined["b"], width, label=f"B: {metric_b}", color="#DD8452")
        ax.set_xticks(x)
        ax.set_xticklabels([str(v) for v in joined.index], rotation=45, ha="right")
        ax.set_title(f"{agg}({metric_a}) vs {agg}({metric_b}) by {key_a}")
        ax.legend()
        png = _fig_to_base64(fig)
    finally:
        fig.clear()

    stats: dict[str, Any] = {
        "key": key_a,
        "agg": agg,
        "rows": [
            {"key": str(idx), "a": _nan_to_none(row["a"]), "b": _nan_to_none(row["b"])}
            for idx, row in joined.iterrows()
        ],
    }
    return png, stats


def error_by_group(
    df: pd.DataFrame, group_column: str, error_column: str
) -> tuple[str, dict[str, Any]]:
    """Mean error per group, as a bar chart. This is per-ticker error.

    `compare` aggregates across two datasets; this aggregates across groups
    within one, which is a different question and not expressible with it.
    """
    sub = df[[group_column, error_column]].copy()
    sub[error_column] = pd.to_numeric(sub[error_column], errors="coerce")
    sub = sub.dropna(subset=[error_column])
    means = sub.groupby(group_column)[error_column].mean().sort_values(ascending=False)
    fig = Figure(figsize=(6, 4))
    try:
        ax = fig.subplots()
        ax.bar([str(i) for i in means.index], means.to_numpy(), color="#4C72B0")
        ax.set_title(f"Mean {error_column} by {group_column}")
        ax.set_xlabel(group_column)
        ax.set_ylabel(f"mean {error_column}")
        ax.tick_params(axis="x", rotation=45)
        png = _fig_to_base64(fig)
    finally:
        fig.clear()
    stats: dict[str, Any] = {
        "group_column": group_column,
        "error_column": error_column,
        "n": int(len(sub)),
        "groups": {str(k): _nan_to_none(v) for k, v in means.items()},
        "worst_group": str(means.index[0]) if len(means) else None,
        "best_group": str(means.index[-1]) if len(means) else None,
    }
    return png, stats


def line(df: pd.DataFrame, x_column: str, y_columns: list[str]) -> tuple[str, dict[str, Any]]:
    """An ordered line plot of one or more series against a shared x.

    Sorting by x is the point: a learning curve or a residual-against-time plot
    drawn in arbitrary row order shows a zigzag that reads as instability in the
    data rather than in the row order.
    """
    columns = [x_column, *y_columns]
    sub = df[columns].apply(pd.to_numeric, errors="coerce").dropna()
    sub = sub.sort_values(x_column, kind="stable")
    fig = Figure(figsize=(6, 4))
    try:
        ax = fig.subplots()
        for column in y_columns:
            ax.plot(sub[x_column], sub[column], marker="o", label=column)
        ax.set_title(f"{', '.join(y_columns)} by {x_column}")
        ax.set_xlabel(x_column)
        if len(y_columns) > 1:
            ax.legend()
        else:
            ax.set_ylabel(y_columns[0])
        png = _fig_to_base64(fig)
    finally:
        fig.clear()
    stats: dict[str, Any] = {
        "x_column": x_column,
        "n": int(len(sub)),
        "series": {
            column: {
                "first": _nan_to_none(sub[column].iloc[0]) if len(sub) else None,
                "last": _nan_to_none(sub[column].iloc[-1]) if len(sub) else None,
                "min": _nan_to_none(sub[column].min()),
                "max": _nan_to_none(sub[column].max()),
                "mean": _nan_to_none(sub[column].mean()),
            }
            for column in y_columns
        },
    }
    return png, stats
