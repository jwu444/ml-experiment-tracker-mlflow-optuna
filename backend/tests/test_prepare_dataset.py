from pathlib import Path

import pandas as pd
import pytest
from prepare_dataset import build_revenue_nowcast, load_revenue, to_quarterly

ROOT = Path(__file__).resolve().parents[2] / "data-sources"


def sec_row(ticker, start, end, filed, value):
    return {
        "ticker": ticker,
        "period_start": pd.Timestamp(start),
        "period_end": pd.Timestamp(end),
        "filed": pd.Timestamp(filed),
        "value_usd": float(value),
        "months": round((pd.Timestamp(end) - pd.Timestamp(start)).days / 30.44),
    }


def test_three_month_rows_pass_through_unchanged():
    df = pd.DataFrame([sec_row("X", "2020-01-01", "2020-03-31", "2020-04-25", 100)])
    out = to_quarterly(df)
    assert out.loc[0, "revenue_usd"] == 100


def test_cumulative_rows_are_differenced_into_quarters():
    df = pd.DataFrame(
        [
            sec_row("X", "2020-01-01", "2020-03-31", "2020-04-25", 100),
            sec_row("X", "2020-01-01", "2020-06-30", "2020-07-25", 250),
            sec_row("X", "2020-01-01", "2020-09-30", "2020-10-25", 420),
        ]
    )
    out = to_quarterly(df).sort_values("quarter_end").reset_index(drop=True)
    assert list(out["revenue_usd"]) == [100, 150, 170]


def test_a_cumulative_row_without_its_predecessor_is_dropped():
    df = pd.DataFrame([sec_row("X", "2020-01-01", "2020-09-30", "2020-10-25", 420)])
    assert to_quarterly(df).empty


def test_as_of_is_the_filing_date_not_the_quarter_end():
    df = pd.DataFrame([sec_row("X", "2020-01-01", "2020-03-31", "2020-04-25", 100)])
    out = to_quarterly(df)
    assert out.loc[0, "as_of"] == pd.Timestamp("2020-04-25")
    assert out.loc[0, "as_of"] > out.loc[0, "quarter_end"]


def test_negative_or_zero_quarters_are_dropped():
    # A restated FY smaller than its own 9-month figure would difference negative.
    df = pd.DataFrame(
        [
            sec_row("X", "2020-01-01", "2020-09-30", "2020-10-25", 420),
            sec_row("X", "2020-01-01", "2020-12-31", "2021-02-01", 400),
        ]
    )
    out = to_quarterly(df)
    assert (out["revenue_usd"] > 0).all()
    assert len(out) == 0


def write_sec_csv(root, rows):
    directory = root / "sec-edgar-revenue"
    directory.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(directory / "x_revenue.csv", index=False)
    return root


def test_a_restated_figure_does_not_displace_the_first_report(tmp_path):
    # The same window filed twice: the original, then a restatement 10 months
    # later. A nowcast can only ever have seen the first one, so keep="first" is
    # what makes the panel point-in-time rather than hindsight.
    root = write_sec_csv(
        tmp_path,
        [
            sec_row("X", "2020-01-01", "2020-03-31", "2020-04-25", 100),
            sec_row("X", "2020-01-01", "2020-03-31", "2021-02-10", 175),
        ],
    )
    out = load_revenue(root, tickers=["X"])
    assert len(out) == 1
    assert out.iloc[0]["value_usd"] == 100
    assert out.iloc[0]["filed"] == pd.Timestamp("2020-04-25")


def test_dedup_keys_on_the_date_window_not_the_fiscal_label(tmp_path):
    # Two genuinely different windows that a filing may label identically (a
    # 3-month Q1 and the 12-month FY that contains it). Deduping on a fiscal
    # label would collapse these into one and destroy the de-cumulation input.
    root = write_sec_csv(
        tmp_path,
        [
            sec_row("X", "2020-01-01", "2020-03-31", "2020-04-25", 100),
            sec_row("X", "2020-01-01", "2020-12-31", "2021-02-01", 500),
        ],
    )
    out = load_revenue(root, tickers=["X"])
    assert len(out) == 2


@pytest.fixture(scope="module")
def panel():
    return build_revenue_nowcast(ROOT)


def test_panel_has_enough_rows_to_model(panel):
    assert len(panel) >= 200
    assert panel["ticker"].nunique() == 5


def test_every_feature_is_known_at_as_of(panel):
    # The target's quarter ends after the information date. If this ever fails,
    # the panel is leaking and every metric downstream is fiction.
    assert (panel["as_of"] > panel["quarter_end"]).all()


def test_only_ticker_is_non_numeric(panel):
    objects = [c for c in panel.columns if panel[c].dtype == object]
    assert objects == ["ticker"]


def test_the_target_is_never_null(panel):
    assert panel["revenue_next_usd"].notna().all()
