import base64

from app.charts import render_message_charts

DATA = {"ds1": "age,score\n20,1\n30,2\n40,3\n"}
DATA_TWO = {
    "ds1": "region,revenue\neast,10\neast,20\nwest,5\n",
    "ds2": "region,revenue\neast,100\nwest,200\nwest,300\n",
}


def _is_png(s: str) -> bool:
    return base64.b64decode(s)[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_histogram_and_scatter() -> None:
    calls = [
        {"name": "histogram", "args": {"dataset_id": "ds1", "column": "age"}},
        {"name": "scatter", "args": {"dataset_id": "ds1", "x": "age", "y": "score"}},
    ]
    charts = render_message_charts(DATA, calls)
    assert len(charts) == 2
    assert all(_is_png(c) for c in charts)


def test_unknown_tool_is_skipped() -> None:
    charts = render_message_charts(DATA, [{"name": "pie", "args": {}}])
    assert charts == []


def test_bad_column_skipped_but_good_call_still_renders() -> None:
    calls = [
        {"name": "histogram", "args": {"dataset_id": "ds1", "column": "does_not_exist"}},
        {"name": "scatter", "args": {"dataset_id": "ds1", "x": "age", "y": "score"}},
    ]
    charts = render_message_charts(DATA, calls)
    assert len(charts) == 1
    assert _is_png(charts[0])


def test_correlation_matrix_renders() -> None:
    calls = [{"name": "correlation_matrix", "args": {"dataset_id": "ds1"}}]
    charts = render_message_charts(DATA, calls)
    assert len(charts) == 1
    assert _is_png(charts[0])


def test_partial_scatter_args_skipped() -> None:
    calls = [{"name": "scatter", "args": {"dataset_id": "ds1", "x": "age"}}]
    charts = render_message_charts(DATA, calls)
    assert charts == []


def test_unknown_dataset_id_skipped() -> None:
    calls = [{"name": "histogram", "args": {"dataset_id": "nope", "column": "age"}}]
    assert render_message_charts(DATA, calls) == []


def test_compare_renders_across_two_datasets() -> None:
    calls = [
        {
            "name": "compare",
            "args": {
                "dataset_a_id": "ds1",
                "dataset_b_id": "ds2",
                "key_a": "region",
                "key_b": "region",
                "metric_a": "revenue",
                "metric_b": "revenue",
                "agg": "mean",
            },
        }
    ]
    charts = render_message_charts(DATA_TWO, calls)
    assert len(charts) == 1
    assert _is_png(charts[0])
