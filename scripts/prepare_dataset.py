"""Offline dataset preparation (Project 2 design D18).

Reads only committed snapshots under `data-sources/` and writes one wide CSV per
candidate into `data-sources/prepared/`. Nothing here runs at request time: the
app's only input is the `datasets` table (D13).

Candidate #4 — company revenue nowcasting. Grain is (ticker, quarter). The target
is the NEXT quarter's revenue; every feature is sampled as of the CURRENT
quarter's filing date, which is the one date on which all of it is public.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pandas as pd

STOCK_FILES = {
    "AMD": "amd.csv",
    "DELL": "dell.csv",
    "HPQ": "hp_inc.csv",
    "INTC": "intel.csv",
    "NVDA": "nvidia.csv",
}

_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
MONTHS = {name: i for i, name in enumerate(_MONTH_NAMES, start=1)}

FEATURE_ORDER = [
    "ticker", "quarter_end", "as_of", "quarter",
    "revenue_usd", "revenue_qoq", "revenue_yoy",
    "stock_close", "stock_ret_63d", "stock_vol_63d",
    "sox_close", "sox_ret_63d",
    "wsts_3mo", "wsts_yoy",
    "ppi_semis", "ppi_yoy",
    "gdp_growth_pct", "inflation_cpi_pct",
    "revenue_next_usd",
]


def load_revenue(root: Path, tickers: Iterable[str] = tuple(STOCK_FILES)) -> pd.DataFrame:
    """SEC EDGAR revenue facts, coerced and deduplicated to point-in-time."""
    frames = [pd.read_csv(p) for p in sorted(root.glob("sec-edgar-revenue/*_revenue.csv"))]
    df = pd.concat(frames, ignore_index=True)
    df = df[df["ticker"].isin(set(tickers))].copy()
    for col in ("period_start", "period_end", "filed"):
        df[col] = pd.to_datetime(df[col], errors="coerce")
    df["value_usd"] = pd.to_numeric(df["value_usd"], errors="coerce")
    df = df.dropna(subset=["value_usd", "period_start", "period_end", "filed"])
    df["months"] = ((df["period_end"] - df["period_start"]).dt.days / 30.44).round().astype(int)
    df = df[df["months"].isin([3, 6, 9, 12])]
    # Dedup on the real date window, never on fiscal_period: the same window is
    # tagged Q3 in a 10-Q and FY in the following 10-K. keep="first" is the
    # point-in-time choice — the figure and the date as first reported.
    return df.sort_values("filed").drop_duplicates(
        ["ticker", "period_start", "period_end"], keep="first"
    )


def to_quarterly(df: pd.DataFrame) -> pd.DataFrame:
    """Difference cumulative year-to-date facts into discrete quarters.

    An XBRL revenue fact covers period_start..period_end, which is YTD, not a
    quarter: quarter = cum(n months) - cum(n-3 months) over the same start.
    Rows whose predecessor is absent are dropped rather than guessed at.
    """
    prior = df[["ticker", "period_start", "months", "value_usd"]].rename(
        columns={"months": "prior_months", "value_usd": "prior_value"}
    )
    joined = df.assign(prior_months=df["months"] - 3).merge(
        prior, on=["ticker", "period_start", "prior_months"], how="left"
    )
    joined["revenue_usd"] = np.where(
        joined["months"] == 3, joined["value_usd"], joined["value_usd"] - joined["prior_value"]
    )
    out = joined.dropna(subset=["revenue_usd"])
    out = out[out["revenue_usd"] > 0]
    return (
        out.rename(columns={"period_end": "quarter_end", "filed": "as_of"})[
            ["ticker", "quarter_end", "as_of", "revenue_usd"]
        ]
        .sort_values(["ticker", "quarter_end"])
        .drop_duplicates(["ticker", "quarter_end"], keep="first")
        .reset_index(drop=True)
    )


def _asof(frame: pd.DataFrame, date_col: str, values: list[str]) -> pd.DataFrame:
    return frame[[date_col, *values]].dropna(subset=[date_col]).sort_values(date_col)


def _merge_asof(left: pd.DataFrame, right: pd.DataFrame) -> pd.DataFrame:
    """Backward as-of join on as_of: only observations already published."""
    return pd.merge_asof(
        left.sort_values("as_of"), right, left_on="as_of", right_on="date", direction="backward"
    ).drop(columns=["date"])


def _stock_features(root: Path, panel: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for ticker, sub in panel.groupby("ticker"):
        s = pd.read_csv(root / "company-stocks" / STOCK_FILES[str(ticker)])
        s["date"] = pd.to_datetime(s["date"])
        s = s.sort_values("date")
        s["stock_ret_63d"] = s["adjclose"].pct_change(63, fill_method=None)
        s["stock_vol_63d"] = s["adjclose"].pct_change(fill_method=None).rolling(63).std()
        cols = _asof(s, "date", ["adjclose", "stock_ret_63d", "stock_vol_63d"]).rename(
            columns={"adjclose": "stock_close"}
        )
        parts.append(_merge_asof(sub, cols))
    return pd.concat(parts, ignore_index=True)


def _index_features(root: Path, panel: pd.DataFrame) -> pd.DataFrame:
    sox = pd.read_csv(root / "market-indices" / "phlx_semiconductor.csv")
    sox["date"] = pd.to_datetime(sox["date"])
    sox = sox.sort_values("date")
    sox["sox_ret_63d"] = sox["adjclose"].pct_change(63, fill_method=None)
    cols = _asof(sox, "date", ["adjclose", "sox_ret_63d"]).rename(columns={"adjclose": "sox_close"})
    return _merge_asof(panel, cols)


def _billings_features(root: Path, panel: pd.DataFrame) -> pd.DataFrame:
    w = pd.read_csv(root / "wsts-semiconductor-billings" / "wsts_monthly_billings.csv")
    w = w[w["region"] == "Worldwide"].copy()   # otherwise one row per region per month
    w["month_num"] = w["month"].map(MONTHS)    # `month` is a name, not a number
    w = w.dropna(subset=["month_num"])
    # Month-end, so a month only becomes visible once it has closed.
    w["date"] = pd.to_datetime(
        dict(year=w["year"], month=w["month_num"].astype(int), day=1)
    ) + pd.offsets.MonthEnd(0)
    w = w.sort_values("date")
    w["wsts_3mo"] = w["billings_thousand_usd"].rolling(3).sum()
    w["wsts_yoy"] = w["billings_thousand_usd"].pct_change(12, fill_method=None)
    return _merge_asof(panel, _asof(w, "date", ["wsts_3mo", "wsts_yoy"]))


def _ppi_features(root: Path, panel: pd.DataFrame) -> pd.DataFrame:
    ppi = pd.read_csv(root / "fred-semiconductor-ppi" / "PCU3344133344131.csv")
    ppi["date"] = pd.to_datetime(ppi["observation_date"]) + pd.offsets.MonthEnd(0)
    ppi = ppi.rename(columns={"PCU3344133344131": "ppi_semis"})
    # FRED marks gaps with a non-numeric token; without coercion pct_change
    # forward-fills them and the nulls silently disappear.
    ppi["ppi_semis"] = pd.to_numeric(ppi["ppi_semis"], errors="coerce")
    ppi = ppi.sort_values("date")
    ppi["ppi_yoy"] = ppi["ppi_semis"].pct_change(12, fill_method=None)
    return _merge_asof(panel, _asof(ppi, "date", ["ppi_semis", "ppi_yoy"]))


def _macro_features(root: Path, panel: pd.DataFrame) -> pd.DataFrame:
    wb = pd.read_csv(root / "worldbank-macro" / "worldbank_macro.csv")
    wb = wb[wb["iso3"] == "USA"][["year", "gdp_growth_pct", "inflation_cpi_pct"]]
    # Annual and published with a lag: only the prior calendar year is safe.
    panel = panel.assign(wb_year=panel["as_of"].dt.year - 1)
    return panel.merge(wb, left_on="wb_year", right_on="year", how="left").drop(
        columns=["year", "wb_year"]
    )


def build_revenue_nowcast(root: Path) -> pd.DataFrame:
    """Candidate #4: predict each company's next-quarter revenue."""
    q = to_quarterly(load_revenue(root))
    q["revenue_qoq"] = q.groupby("ticker")["revenue_usd"].pct_change(1, fill_method=None)
    q["revenue_yoy"] = q.groupby("ticker")["revenue_usd"].pct_change(4, fill_method=None)
    q["quarter"] = q["quarter_end"].dt.quarter

    # The label: next quarter's revenue, but only where the next row really is
    # the next quarter. A gap must not be relabelled as a one-quarter step.
    next_end = q.groupby("ticker")["quarter_end"].shift(-1)
    q["revenue_next_usd"] = q.groupby("ticker")["revenue_usd"].shift(-1)
    gap_days = (next_end - q["quarter_end"]).dt.days
    q.loc[~gap_days.between(60, 120), "revenue_next_usd"] = np.nan

    q = _stock_features(root, q)
    q = _index_features(root, q)
    q = _billings_features(root, q)
    q = _ppi_features(root, q)
    q = _macro_features(root, q)

    q = q[FEATURE_ORDER].dropna(subset=["revenue_next_usd", "stock_close"])
    return q.sort_values(["as_of", "ticker"]).reset_index(drop=True)


BUILDERS = {"revenue_nowcast": build_revenue_nowcast}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", choices=sorted(BUILDERS), nargs="?", default="revenue_nowcast")
    parser.add_argument("--root", type=Path, default=Path("data-sources"))
    args = parser.parse_args()

    frame = BUILDERS[args.candidate](args.root)
    out_dir = args.root / "prepared"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{args.candidate}.csv"
    frame.to_csv(out_path, index=False)
    print(f"{out_path}: {len(frame)} rows x {len(frame.columns)} cols")
    print(f"  as_of {frame['as_of'].min().date()} -> {frame['as_of'].max().date()}")
    print(f"  tickers {sorted(frame['ticker'].unique())}")
    print(f"  nulls {frame.isna().sum().sum()}")


if __name__ == "__main__":
    main()
