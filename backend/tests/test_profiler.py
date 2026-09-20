import json

import numpy as np
import pandas as pd
from app.profiler import profile_dataframe


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "age": [20, 30, 40, np.nan],
            "income": [100, 200, 300, 400],
            "city": ["NY", "NY", "LA", "LA"],
        }
    )


def test_shape_and_columns():
    profile = profile_dataframe(_frame())
    assert profile["n_rows"] == 4
    assert profile["n_cols"] == 3
    names = {c["name"]: c for c in profile["columns"]}
    assert names["age"]["n_null"] == 1
    assert names["income"]["n_null"] == 0


def test_numeric_summary_has_mean():
    profile = profile_dataframe(_frame())
    assert "income" in profile["numeric_summary"]
    assert profile["numeric_summary"]["income"]["mean"] == 250.0


def test_categorical_summary_counts():
    profile = profile_dataframe(_frame())
    assert profile["categorical_summary"]["city"] == {"NY": 2, "LA": 2}


def test_high_cardinality_column_skipped():
    df = pd.DataFrame({"id": [f"u{i}" for i in range(50)]})
    profile = profile_dataframe(df, max_cardinality=20)
    assert "id" not in profile["categorical_summary"]


def test_correlations_present_and_sorted():
    profile = profile_dataframe(_frame())
    assert len(profile["correlations"]) >= 1
    assert profile["correlations"][0]["abs_corr"] >= profile["correlations"][-1]["abs_corr"]


def test_sample_rows_nan_becomes_none():
    profile = profile_dataframe(_frame())
    assert profile["sample_rows"][3]["age"] is None


def test_infinite_and_nan_stats_become_json_safe():
    df = pd.DataFrame(
        {
            "ratio": [1.0, 2.0, np.inf, -np.inf],
            "constant": [5, 5, 5, 5],
            "other": [1, 2, 3, 4],
        }
    )
    profile = profile_dataframe(df)
    # describe() mean/std over a column containing inf is itself inf/nan
    assert profile["numeric_summary"]["ratio"]["mean"] is None
    # corr() against a zero-variance column is NaN
    assert any(
        pair["abs_corr"] is None
        for pair in profile["correlations"]
        if "constant" in (pair["a"], pair["b"])
    )
    # a literal inf value in a sample row is normalized too
    assert profile["sample_rows"][2]["ratio"] is None
    # Postgres' json/jsonb column rejects the raw NaN/Infinity tokens
    # Python's json.dumps emits for non-finite floats.
    serialized = json.dumps(profile)
    assert "Infinity" not in serialized
    assert "NaN" not in serialized


def test_profile_degrades_over_token_budget():
    profile = profile_dataframe(_frame(), token_budget=1)
    assert profile["degraded"] is True
    assert profile["categorical_summary"] == {}
    assert profile["sample_rows"] == []
    # schema + describe + correlations survive the degrade
    assert profile["columns"]
    assert profile["numeric_summary"]
