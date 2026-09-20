from app.tools import TOOL_DEFS, validate_tool_call

PROFILES = {
    "ds1": {
        "columns": [
            {"name": "age", "dtype": "int64", "n_null": 0},
            {"name": "score", "dtype": "float64", "n_null": 0},
            {"name": "city", "dtype": "object", "n_null": 0},
        ]
    }
}


PROFILES_COMPARE = {
    "ds1": {
        "columns": [
            {"name": "region", "dtype": "object", "n_null": 0},
            {"name": "revenue", "dtype": "float64", "n_null": 0},
        ]
    },
    "ds2": {
        "columns": [
            {"name": "region", "dtype": "object", "n_null": 0},
            {"name": "revenue", "dtype": "int64", "n_null": 0},
        ]
    },
}


def test_tool_defs_cover_six_tools() -> None:
    names = {t["name"] for t in TOOL_DEFS}
    assert names == {
        "histogram",
        "scatter",
        "correlation_matrix",
        "compare",
        "error_by_group",
        "line",
    }


def _compare_args(**overrides: object) -> dict[str, object]:
    args: dict[str, object] = {
        "dataset_a_id": "ds1",
        "dataset_b_id": "ds2",
        "key_a": "region",
        "key_b": "region",
        "metric_a": "revenue",
        "metric_b": "revenue",
        "agg": "mean",
    }
    args.update(overrides)
    return args


def test_valid_compare_passes() -> None:
    assert validate_tool_call("compare", _compare_args(), PROFILES_COMPARE) is None


def test_compare_unknown_dataset_rejected() -> None:
    err = validate_tool_call("compare", _compare_args(dataset_a_id="nope"), PROFILES_COMPARE)
    assert err is not None and "nope" in err


def test_compare_unknown_key_rejected() -> None:
    err = validate_tool_call("compare", _compare_args(key_a="nope"), PROFILES_COMPARE)
    assert err is not None and "nope" in err


def test_compare_non_numeric_metric_rejected() -> None:
    err = validate_tool_call("compare", _compare_args(metric_a="region"), PROFILES_COMPARE)
    assert err is not None and "numeric" in err.lower()


def test_compare_unsupported_agg_rejected() -> None:
    err = validate_tool_call("compare", _compare_args(agg="median"), PROFILES_COMPARE)
    assert err is not None and "agg" in err.lower()


_PROFILE = {
    "columns": [
        {"name": "ticker", "dtype": "object", "n_null": 0},
        {"name": "abs_error", "dtype": "float64", "n_null": 0},
        {"name": "train_size", "dtype": "int64", "n_null": 0},
    ]
}


def test_error_by_group_accepts_a_categorical_group_and_numeric_error() -> None:
    err = validate_tool_call(
        "error_by_group",
        {"dataset_id": "d1", "group_column": "ticker", "error_column": "abs_error"},
        {"d1": _PROFILE},
    )
    assert err is None


def test_error_by_group_rejects_a_non_numeric_error_column() -> None:
    err = validate_tool_call(
        "error_by_group",
        {"dataset_id": "d1", "group_column": "abs_error", "error_column": "ticker"},
        {"d1": _PROFILE},
    )
    assert err == "Column must be numeric: ticker"


def test_error_by_group_rejects_an_unknown_group_column() -> None:
    err = validate_tool_call(
        "error_by_group",
        {"dataset_id": "d1", "group_column": "sector", "error_column": "abs_error"},
        {"d1": _PROFILE},
    )
    assert err == "Column not found: 'sector'"


def test_line_accepts_numeric_x_and_y_columns() -> None:
    err = validate_tool_call(
        "line",
        {"dataset_id": "d1", "x_column": "train_size", "y_columns": ["abs_error"]},
        {"d1": _PROFILE},
    )
    assert err is None


def test_line_rejects_an_empty_y_columns_list() -> None:
    err = validate_tool_call(
        "line", {"dataset_id": "d1", "x_column": "train_size", "y_columns": []}, {"d1": _PROFILE}
    )
    assert err == "line requires at least one y column"


def test_line_rejects_a_non_numeric_y_column() -> None:
    err = validate_tool_call(
        "line",
        {"dataset_id": "d1", "x_column": "train_size", "y_columns": ["ticker"]},
        {"d1": _PROFILE},
    )
    assert err == "Column must be numeric: ticker"


def test_valid_histogram_passes() -> None:
    args = {"dataset_id": "ds1", "column": "age"}
    assert validate_tool_call("histogram", args, PROFILES) is None


def test_histogram_unknown_column_rejected() -> None:
    args = {"dataset_id": "ds1", "column": "nope"}
    err = validate_tool_call("histogram", args, PROFILES)
    assert err is not None and "nope" in err


def test_histogram_non_numeric_column_rejected() -> None:
    args = {"dataset_id": "ds1", "column": "city"}
    err = validate_tool_call("histogram", args, PROFILES)
    assert err is not None and "numeric" in err.lower()


def test_histogram_unknown_dataset_rejected() -> None:
    args = {"dataset_id": "nope", "column": "age"}
    err = validate_tool_call("histogram", args, PROFILES)
    assert err is not None and "nope" in err


def test_scatter_requires_two_numeric_columns() -> None:
    ok = {"dataset_id": "ds1", "x": "age", "y": "score"}
    bad = {"dataset_id": "ds1", "x": "age", "y": "city"}
    assert validate_tool_call("scatter", ok, PROFILES) is None
    assert validate_tool_call("scatter", bad, PROFILES) is not None


def test_correlation_matrix_requires_dataset_id() -> None:
    assert validate_tool_call("correlation_matrix", {"dataset_id": "ds1"}, PROFILES) is None
    err = validate_tool_call("correlation_matrix", {"dataset_id": "nope"}, PROFILES)
    assert err is not None


def test_unknown_tool_rejected() -> None:
    assert validate_tool_call("pie", {}, PROFILES) is not None


def test_missing_required_arg_rejected() -> None:
    assert isinstance(validate_tool_call("histogram", {"dataset_id": "ds1"}, PROFILES), str)


def test_non_string_arg_rejected_without_raising() -> None:
    bad_column = {"dataset_id": "ds1", "column": ["a", "b"]}
    bad_x = {"dataset_id": "ds1", "x": {"k": 1}, "y": "score"}
    assert isinstance(validate_tool_call("histogram", bad_column, PROFILES), str)
    assert isinstance(validate_tool_call("scatter", bad_x, PROFILES), str)


def test_profile_column_missing_dtype_does_not_raise() -> None:
    profiles = {"ds1": {"columns": [{"name": "age", "n_null": 0}]}}
    args = {"dataset_id": "ds1", "column": "age"}
    result = validate_tool_call("histogram", args, profiles)
    assert isinstance(result, str)  # treated as non-numeric, rejected, not crashed
