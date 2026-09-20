"""Re-render charts for history reads. Charts are a pure function of each
attached dataset's raw CSV plus a message's tool_calls — never stored (design D5)."""

from __future__ import annotations

from typing import Any

from app.analysis import compare, correlation_matrix, error_by_group, histogram, line, scatter
from app.dataset_io import load_csv

_DISPATCH = {
    "histogram": lambda dfs, args: histogram(dfs[args["dataset_id"]], args["column"]),
    "scatter": lambda dfs, args: scatter(dfs[args["dataset_id"]], args["x"], args["y"]),
    "correlation_matrix": lambda dfs, args: correlation_matrix(dfs[args["dataset_id"]]),
    "compare": lambda dfs, args: compare(
        dfs[args["dataset_a_id"]],
        dfs[args["dataset_b_id"]],
        args["key_a"],
        args["key_b"],
        args["metric_a"],
        args["metric_b"],
        args["agg"],
    ),
    "error_by_group": lambda dfs, args: error_by_group(
        dfs[args["dataset_id"]], args["group_column"], args["error_column"]
    ),
    "line": lambda dfs, args: line(dfs[args["dataset_id"]], args["x_column"], args["y_columns"]),
}


def render_message_analysis(
    data_csv_by_id: dict[str, str], tool_calls: list[dict[str, Any]]
) -> tuple[list[str], list[dict[str, Any]]]:
    """Re-derive charts AND stats from each attached dataset's CSV + a message's
    tool_calls (history path). Charts and stats are pure functions of these
    inputs, re-derived on read — consistent with the 'charts are never stored'
    invariant. Unknown/invalid calls (including an unknown dataset_id, which
    raises KeyError against dfs) are skipped so one bad call never breaks a
    history read."""
    dfs = {dataset_id: load_csv(csv) for dataset_id, csv in data_csv_by_id.items()}
    charts: list[str] = []
    stats: list[dict[str, Any]] = []
    for call in tool_calls:
        fn = _DISPATCH.get(call.get("name", ""))
        if fn is None:
            continue
        try:
            png, stat = fn(dfs, call.get("args", {}))
        except (KeyError, ValueError):
            continue
        charts.append(png)
        stats.append(stat)
    return charts, stats


def render_message_charts(
    data_csv_by_id: dict[str, str], tool_calls: list[dict[str, Any]]
) -> list[str]:
    charts, _stats = render_message_analysis(data_csv_by_id, tool_calls)
    return charts
