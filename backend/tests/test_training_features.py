import pandas as pd
import pytest
from app.training import infer_feature_columns


def frame(**cols):
    return pd.DataFrame(cols)


def test_keeps_numeric_and_low_cardinality_categoricals():
    df = frame(
        memory=[4, 8, 12],
        price=[1.0, 2.0, 3.0],
        chipset=["a", "b", "a"],
    )
    assert infer_feature_columns(df, "price", 20) == ["memory", "chipset"]


def test_excludes_the_target():
    df = frame(memory=[4, 8, 12], price=[1.0, 2.0, 3.0])
    assert "price" not in infer_feature_columns(df, "price", 20)


def test_excludes_high_cardinality_identifiers():
    df = frame(
        memory=list(range(30)),
        price=[float(i) for i in range(30)],
        name=[f"card-{i}" for i in range(30)],
    )
    assert infer_feature_columns(df, "price", 20) == ["memory"]


def test_excludes_the_time_column():
    df = frame(
        as_of=pd.date_range("2020-01-01", periods=3, freq="QE"),
        memory=[4, 8, 12],
        price=[1.0, 2.0, 3.0],
    )
    assert infer_feature_columns(df, "price", 20, time_column="as_of") == ["memory"]


def test_excludes_datetime_columns_even_when_not_the_split_axis():
    # A raw timestamp one-hot-encodes into one column per row and leaks the
    # ordering the chronological split is meant to control.
    df = frame(
        quarter_end=pd.date_range("2020-01-01", periods=3, freq="QE"),
        memory=[4, 8, 12],
        price=[1.0, 2.0, 3.0],
    )
    assert infer_feature_columns(df, "price", 20) == ["memory"]


def test_preserves_column_order():
    df = frame(chipset=["a", "b"], memory=[4, 8], price=[1.0, 2.0])
    assert infer_feature_columns(df, "price", 20) == ["chipset", "memory"]


def test_raises_when_the_target_is_absent():
    with pytest.raises(ValueError, match="target"):
        infer_feature_columns(frame(memory=[1, 2]), "price", 20)


def test_raises_when_nothing_usable_remains():
    df = frame(price=[1.0, 2.0, 3.0], name=["a", "b", "c"])
    with pytest.raises(ValueError, match="no usable feature"):
        infer_feature_columns(df, "price", 2)


def test_picks_the_real_panel_features():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    df = pd.read_csv(root / "data-sources" / "prepared" / "revenue_nowcast.csv")
    got = infer_feature_columns(df, "revenue_next_usd", 20, time_column="as_of")
    assert "ticker" in got  # 5 distinct values — a real categorical
    assert "revenue_usd" in got
    assert "as_of" not in got  # excluded as the split axis
    # `quarter_end` survives read_csv as a high-cardinality string, so it is the
    # cardinality rule — not the dtype rule — that drops it. Assert it either way.
    assert "quarter_end" not in got
    assert "revenue_next_usd" not in got  # the target
