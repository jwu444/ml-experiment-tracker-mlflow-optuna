# Project 2 Phase 2a — Training, MLflow, and Optuna: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** the app can prepare a real modelling dataset from the committed source snapshots,
fit models against it without leaking the future into the past, log every run to MLflow, tune
hyperparameters with Optuna, browse the results in its own UI, and carry at least 20 genuine
experiments with observation-grade draft notes for Phase 3 to retrieve over.

**Architecture:** one offline preparation script plus four new backend modules with one
external boundary each — `prepare_dataset.py` does every join and coercion ahead of time
(D18), `training.py` is pure sklearn, `experiment_log.py` is the only module importing
`mlflow`, `tuning.py` drives Optuna over both, and `routes/experiments.py` owns every DB
write. Endpoints stay synchronous and need no API key; note enrichment lives in a seeding
script (D17) and everything it writes is a **draft** pending human approval (D20).

**Tech Stack:** pandas · scikit-learn · Optuna · MLflow 3.15 (Postgres-backed, `mlflow`
schema) · FastAPI · SQLAlchemy 2.0 · pytest · React + Vite + TypeScript.

**Scope — this is Phase 2a, the pipeline half.** It ends with a working history of genuine
runs whose notes a human has reviewed. Phase 2b (EDA over the prepared panel, model
diagnostics against a persistence baseline, richer note review, and the
`experiment_note_chunks` source-type migration) gets its own plan once 2a lands. See "Deferred
to Phase 2b" at the end.

**Design spec:** `doc/plans/2026-08-10-project-2-phases-2-4-design.md` (§3 is Phase 2).
**Review comments answered:** `doc/plans/project-2-phase-2-4-design-comments.md`.
**Parent design:** `doc/project-2-ml-experiment-tracker-design.md`.
**Program plan:** `doc/plans/2026-08-05-project-2-overall-implementation-plan.md` §3.

---

## Global Constraints

Every task's requirements implicitly include this section.

- **Python 3.12** (`.python-version`). Poetry for all dependency changes.
- **Line length 100** — ruff and black both configured to it.
- **mypy is strict** on `backend/app`. `ignore_missing_imports = true` is already set
  globally, so sklearn/optuna/mlflow need no override — but `warn_return_any` is on, so a
  value coming out of an untyped library must be coerced (`float(...)`, `str(...)`) before
  being returned from an annotated function.
- Backend application code lives in `backend/app/` **only**; backend tests in
  `backend/tests/` **only**. Imports are absolute from `app` (`from app.training import ...`).
- **All tables live in the `app` Postgres schema.** Tests run on SQLite with
  `schema_translate_map={"app": None}` (see `backend/tests/conftest.py`); do not add
  schema-qualified raw SQL.
- **Tests must not require Postgres, Docker, or any API key.** `make check` is the CI gate
  and runs with no services and no secrets.
- **MLflow tracking store in tests is `sqlite:///{tmp_path}/mlflow.db`.** A `file://` store
  **does not work** — MLflow 3.15 rejects the filesystem backend with a maintenance-mode
  error. This is verified, not assumed.
- `make check` (lint + format-check + type-check + test) must pass before every commit.
- One branch and one PR per task, matching the Phase 1 workflow. Squash-merge with
  `--delete-branch`.
- **Never model MLflow tables in `app/models.py`.** `backend/alembic/env.py`'s
  `app_schema_only` filter exists to keep autogenerate off them; adding one would break it.
- **No temporal leakage** (design §3.6). Any dataset with a time column is split
  chronologically — holdout is the latest fraction by time, cross-validation is
  `TimeSeriesSplit`, and every feature is lagged to information available at `t`. A shuffled
  split on a next-period target trains on the future and inflates every metric in the history
  Phases 3–4 depend on. This is not a per-task detail; it is the reason Task 3 exists.
- **Every metric is reported with its cross-validation standard deviation.** The candidate-#4
  panel is 224 rows (~45 in the chronological holdout), so a point estimate cannot separate
  two models. Never rank on the mean alone.
- **Data preparation is offline and network-free.** `scripts/prepare_dataset.py` reads only
  committed files under `data-sources/` and writes only under `data-sources/prepared/`. No
  request-time file reads: the app's only input is the `datasets` table (D13).
- **Nothing the machine writes may present itself as reviewed (D20).** Every `experiments` row
  is created with `notes_status="draft"`, from both flows and from the seeding script, and only
  an explicit `PATCH` naming `notes_status` moves it to `approved` or `rejected`. Writing note
  text through that same route is not an approval. Phase 3 embeds approved notes.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/prepare_dataset.py` | **Create.** Offline join + coercion + label engineering (D18). Reads `data-sources/`, writes one wide CSV per candidate to `data-sources/prepared/`. Pure pandas, no network, no DB. |
| `backend/app/training.py` | **Create.** Pure sklearn: `MODEL_REGISTRY` (task-typed), `build_pipeline`, `split_frame`, `cv_splitter`, `fit_and_score`, `cv_objective`, `infer_feature_columns`. No MLflow, no DB, no network. |
| `backend/app/experiment_log.py` | **Create.** The only module importing `mlflow`: `log_run`, `fetch_runs`, `search_runs`, `RunData`. |
| `backend/app/tuning.py` | **Create.** Optuna `Study` over `training.cv_objective`, with `suggest_params`; one MLflow run + one `experiments` row per trial. |
| `backend/app/routes/experiments.py` | **Create.** Five endpoints — `POST /train`, `POST /tune`, `GET ""`, `GET /{id}`, `PATCH /{id}`; owns all DB writes. |
| `backend/app/schemas.py` | **Modify.** Add the experiment request/response models. |
| `backend/app/config.py` | **Modify.** Add the Optuna and train/test settings. |
| `backend/app/models.py` | **Modify.** Add `Experiment.task_type` and `Experiment.notes_status` (D20). |
| `backend/app/main.py` | **Modify.** Include the new router. |
| `scripts/fetch_component_data.sh` | **Modify.** Repoint at `data-sources/`, including `prepared/` (D13). |
| `scripts/seed_experiment_history.py` | **Create.** Deliverable 2.10; the only script calling Claude (D17). Writes notes as drafts. |
| `frontend/src/pages/ExperimentsPage.tsx` | **Create.** List, filter by model and task type, compare, and review draft notes (D20). |
| `frontend/src/api.ts` | **Modify.** `listExperiments`, `getExperiment`, `updateExperiment`. |

`training.py` and `experiment_log.py` are deliberately separate so the sklearn code is
testable without MLflow standing up, and so Phase 3's agent reuses one SDK boundary.
`prepare_dataset.py` sits outside `backend/app/` because it is not part of the request path:
it runs once, its output is committed, and the app only ever sees the result through
`datasets` (D13/D18). `suggest_params` lives in `tuning.py`, not `training.py`, because it is
the one function needing an `optuna.Trial` — that placement is what keeps `training.py`
importable and testable without optuna.

---

## Task 1: `scripts/prepare_dataset.py` — the candidate-#4 panel (D18)

**Do this first.** Everything downstream trains on its output, and the join is the likeliest
place for a silent error in the whole phase (design §7 risk 7). Preparation is an **offline**
step: it runs once, its output is committed, and the app only ever sees the result through
the `datasets` table.

**What the sources actually look like** — verified by reading them, not assumed:

| Source | Grain | The trap |
|---|---|---|
| `sec-edgar-revenue/*_revenue.csv` | one row per (ticker, XBRL duration, filing) | **`value_usd` is cumulative year-to-date, not quarterly.** A row spanning 2017-01-01→2017-09-30 is nine months of revenue. Discrete quarters must be differenced out. |
| `company-stocks/{amd,intel,nvidia,dell,hp_inc}.csv` | daily OHLCV, `date,open,high,low,close,adjclose,volume` | starts **2011-08-15**, which is what bounds the panel — not the revenue history |
| `market-indices/phlx_semiconductor.csv` | daily OHLCV, same shape | — |
| `wsts-semiconductor-billings/wsts_monthly_billings.csv` | `year,region,month,billings_thousand_usd` | `month` is a **name** (`"January"`), not a number; `region` must be filtered to `"Worldwide"` or every month appears once per region |
| `fred-semiconductor-ppi/PCU3344133344131.csv` | monthly, `observation_date` + a column named after the series id | missing values are non-numeric markers — coerce, or `pct_change` silently forward-fills them |
| `worldbank-macro/worldbank_macro.csv` | **annual**, `iso3,country,year,gdp_current_usd,gdp_growth_pct,inflation_cpi_pct` | filter `iso3 == "USA"`; published with a lag, so only the prior calendar year is safely known |

**Three things this task decides, which the design left open:**

1. **The information date is the filing date, not the quarter end.** Quarter `t`'s revenue is
   not public at quarter `t`'s end — it is public when the 10-Q lands, ~25 days later. Every
   feature is sampled as of `filed[t]` via `merge_asof(direction="backward")`, and the target
   is quarter `t+1`'s revenue, whose end is ~65 days after `filed[t]`. That gap is the whole
   leakage argument, and it is why `as_of` — not `quarter_end` — is the time column handed to
   `training.py` in Task 3.
2. **Restatement dedup keeps the *first* filing, not the latest.** Keying on the real date
   window `(ticker, period_start, period_end)` — never on `fiscal_period`, because the same
   window is tagged `Q3` in a 10-Q and `FY` in the following 10-K — and keeping `first` gives
   point-in-time values. Keeping `last` pulls restated figures and a filing date up to a year
   after the quarter into the row, which both leaks and scrambles the time axis.
3. **Five tickers, not three.** The design's candidate #4 names NVDA/AMD/INTC. The committed
   `sec-edgar-revenue/` directory holds six (AAPL, AMD, DELL, HPQ, INTC, NVDA), five of which
   have a matching stock file (AAPL does not). Using all five nearly doubles the panel, and
   `ticker` enters as a categorical feature, so nothing about the model changes. **Record this
   as an amendment to D12 when Task 11 syncs the docs.**

**Verified output: 224 rows, 5 tickers, `as_of` spanning 2011-08-25 → 2026-05-06.** A 20%
chronological holdout is therefore ~45 rows from roughly 2024-08 on. That is thin — hence
the CV-standard-deviation rule in Global Constraints.

**Files:**
- Create: `scripts/prepare_dataset.py`
- Create: `data-sources/prepared/revenue_nowcast.csv` (generated, committed)
- Create: `data-sources/prepared/README.md`
- Modify: `pyproject.toml` (add `scripts` to pytest's `pythonpath`)
- Modify: `Makefile` (add `prepare-data`)
- Test: `backend/tests/test_prepare_dataset.py`

**Interfaces:**
- Consumes: committed CSVs under `data-sources/` only. No network, no DB.
- Produces:
  - `load_revenue(root: Path, tickers: Iterable[str]) -> DataFrame`
  - `to_quarterly(df: DataFrame) -> DataFrame` — columns `ticker, quarter_end, as_of, revenue_usd`
  - `build_revenue_nowcast(root: Path) -> DataFrame` — the full wide panel
  - the CSV `data-sources/prepared/revenue_nowcast.csv`, whose time column is `as_of` and
    whose target is `revenue_next_usd`. Task 2 uploads it; Tasks 3–10 only ever see it
    through `datasets`.

- [x] **Step 1: Make `scripts/` importable by the test suite**

In `pyproject.toml`:

```toml
[tool.pytest.ini_options]
pythonpath = ["backend", "scripts"]
testpaths = ["backend/tests"]
```

Backend tests stay in `backend/tests/` as the constraints require; this only lets them
`import prepare_dataset`.

- [x] **Step 2: Write the failing tests**

Create `backend/tests/test_prepare_dataset.py`. These test the two transformations that can
be wrong without anything crashing — de-cumulation and restatement choice — on hand-built
frames, so they do not depend on the committed CSVs.

```python
import pandas as pd
import pytest

from prepare_dataset import to_quarterly


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
```

And, in the same file, the two tests over the real committed data — the join is the risk, so
it gets an assertion, not a hope:

```python
from pathlib import Path

from prepare_dataset import build_revenue_nowcast

ROOT = Path(__file__).resolve().parents[2] / "data-sources"


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
```

- [x] **Step 3: Run the tests to verify they fail**

Run: `poetry run pytest backend/tests/test_prepare_dataset.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'prepare_dataset'`

- [x] **Step 4: Write `scripts/prepare_dataset.py`**

```python
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
```

- [x] **Step 5: Run the tests to verify they pass**

Run: `poetry run pytest backend/tests/test_prepare_dataset.py -v`
Expected: PASS, 9 tests.

- [x] **Step 6: Generate and eyeball the CSV**

```bash
poetry run python scripts/prepare_dataset.py revenue_nowcast
poetry run python -c "
import pandas as pd
d = pd.read_csv('data-sources/prepared/revenue_nowcast.csv')
print(d.shape)
print(d.dtypes.to_string())
print(d.groupby('ticker')['revenue_usd'].agg(['count','median']).to_string())
" | sed 's/^/| /'
```

Expected: `(224, 19)`; every dtype numeric except `ticker`, `quarter_end`, `as_of`; and
per-ticker medians in the right order of magnitude — NVDA and INTC in the billions, not the
millions. A median off by 1000× means the de-cumulation subtracted the wrong row.

- [x] **Step 7: Document the generated file**

Create `data-sources/prepared/README.md`:

```markdown
# Prepared datasets

Generated by `scripts/prepare_dataset.py` — **do not edit by hand.** Regenerate with
`make prepare-data`. These files are committed so training is reproducible offline and so
the join is reviewable in a diff (design D18).

## `revenue_nowcast.csv` — candidate #4, company revenue nowcasting

| | |
|---|---|
| Grain | one row per (ticker, fiscal quarter) |
| Rows | 224, five tickers (AMD, DELL, HPQ, INTC, NVDA) |
| Time column | `as_of` — the SEC filing date of that quarter's report |
| Target | `revenue_next_usd` — the **following** quarter's revenue |
| Span | 2011-08-25 → 2026-05-06 (bounded by the stock history, not the revenue history) |

Sources: `sec-edgar-revenue/`, `company-stocks/`, `market-indices/phlx_semiconductor.csv`,
`wsts-semiconductor-billings/`, `fred-semiconductor-ppi/`, `worldbank-macro/`.

**Every feature is sampled as of `as_of`**, the date the quarter's numbers became public.
Revenue facts are deduplicated to their first filing (point-in-time, not restated) and
differenced out of XBRL's cumulative year-to-date durations. Because `as_of` is ~25 days
after `quarter_end` and the target's quarter ends ~65 days later, no feature can see its own
label. Split this file chronologically on `as_of` — never on row order, never shuffled.
```

- [x] **Step 8: Add the Makefile target**

```make
prepare-data:  ## regenerate data-sources/prepared/ from the committed snapshots
	poetry run python scripts/prepare_dataset.py revenue_nowcast
```

- [x] **Step 9: Commit**

```bash
make check
git add scripts/prepare_dataset.py backend/tests/test_prepare_dataset.py \
        data-sources/prepared pyproject.toml Makefile
git commit -m "feat: offline dataset preparation for the revenue-nowcast panel (D18)"
```

---

## Task 2: Single data path (D13)

Closes the Phase-1 carry-over where `data-sources/` and `make data-fetch` deliver the same
tables by two different routes, and makes Task 1's prepared panel the thing that actually
gets trained on. No new Python — this is purely about making the ingestion input pinned and
offline before anything trains on it.

**Files:**
- Modify: `scripts/fetch_component_data.sh`
- Modify: `.gitignore` (drop the `data/pc-parts/` entry)
- Modify: `CLAUDE.md` (replace the "Two source-data paths coexist" entry)

**Interfaces:**
- Consumes: `data-sources/prepared/revenue_nowcast.csv` from Task 1.
- Produces: three rows in `datasets` named `revenue-nowcast.csv`, `pc-part-video-card.csv`,
  and `pc-part-cpu.csv`, all sourced from committed files. Task 6 onward reads them by
  `dataset_id`; `revenue-nowcast.csv` is the one Phase 2a actually models.

- [x] **Step 1: Repoint the fetch script at the committed snapshots**

Replace the download block in `scripts/fetch_component_data.sh`. The script keeps its POST
loop shape — only the source of the CSVs changes, plus the prepared panel.

```bash
#!/usr/bin/env bash
set -euo pipefail

API="${API:-http://localhost:8000}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)/data-sources"

upload() {  # upload <path> <name-in-datasets>
  if [ ! -f "$1" ]; then
    echo "Missing $1 — run 'make prepare-data', or is data-sources/ checked out?" >&2
    exit 1
  fi
  echo "Uploading $2 ..."
  curl -sS -X POST "${API}/datasets" -F "file=@$1;filename=$2" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("  %s: id=%s rows=%s cols=%s" % (d["name"], d["id"], d["n_rows"], d["n_cols"]))'
}

# The prepared modelling panel (D18) — what Phase 2a trains on.
upload "${ROOT}/prepared/revenue_nowcast.csv" "revenue-nowcast.csv"

# Phase 1's component tables, kept as a second, non-temporal dataset.
for part in video-card cpu; do
  upload "${ROOT}/pc-part-dataset/${part}.csv" "pc-part-${part}.csv"
done
```

- [x] **Step 2: Delete the gitignore entry and any downloaded copy**

```bash
git rm -r --cached data/pc-parts 2>/dev/null || true
rm -rf data/pc-parts
# Remove the `data/pc-parts/` line and its comment from .gitignore
```

- [x] **Step 3: Verify ingestion is offline and idempotent**

Start the backend against Postgres, then run the script twice.

```bash
make db-up
DATABASE_URL="postgresql+psycopg2://wavepoint:wavepoint@localhost:5433/wavepoint" make dev &
sleep 5
make data-fetch
make data-fetch   # second run must print identical ids
curl -sS localhost:8000/datasets | python3 -m json.tool
```

Expected: both runs print the same three ids (SHA-256 dedup), `GET /datasets` returns exactly
three rows with `revenue-nowcast.csv` at 224 rows × 19 cols, and no network request is made
for the CSVs.

- [x] **Step 4: Replace the CLAUDE.md entry**

The current "Two source-data paths currently coexist, and they overlap" entry describes a
problem that no longer exists. Replace it with:

```markdown
**One source-data path: the `datasets` table (Project 2 D13/D18).** `data-sources/` is the
committed, licence-shipping catalogue of snapshots (~50 CSVs across 12 sources, documented
in `data-sources/README.md`). Joining, coercing, and labelling happen **offline** in
`scripts/prepare_dataset.py` (`make prepare-data`), which writes wide, model-ready CSVs into
the committed `data-sources/prepared/`. `make data-fetch` then uploads
`prepared/revenue_nowcast.csv` and `pc-part-dataset/{video-card,cpu}.csv` into `datasets` via
`POST /datasets`. Nothing downloads at run time and nothing reads CSVs off disk at request
time: `app/training.py` takes a DataFrame, and the route parses `datasets.data_csv` with
`dataset_io.load_csv()`. Adding a new training input means preparing it and uploading it,
never adding a file path to the request path.
```

- [x] **Step 5: Commit**

```bash
git add scripts/fetch_component_data.sh .gitignore CLAUDE.md
git commit -m "feat: single data path — ingest prepared + committed snapshots (D13/D18)"
```

---

## Task 3: `app/training.py` — pure sklearn core, task-typed and time-aware

Two things here are not optional decoration, and both come from the design review:

- **The registry carries `task_type`, `objective_metric`, and `direction` per entry**
  (review point 3). A global `direction="minimize"` constant is a silent bug the moment a
  maximising metric like `f1_macro` is registered: the study would select the *worst*
  classifier and report it as best, with nothing in the output to say so.
- **A dataset with a time column is split chronologically** (design §3.6). The
  revenue-nowcast target is next quarter's revenue; a shuffled split trains on rows from
  after the ones it is scored on. Every metric downstream — and therefore the whole
  experiment history Phases 3 and 4 depend on — would be fiction.

**Files:**
- Create: `backend/app/training.py`
- Modify: `backend/app/config.py`, `pyproject.toml`
- Test: `backend/tests/test_training.py`

**Interfaces:**
- Consumes: `app.config.settings`.
- Produces:
  - `TrainResult(status: str, metrics: dict[str, float], params: dict[str, Any], error: str | None, model: Any | None)`
  - `ModelSpec(task_type, factory, search_space, objective_metric, direction, cv_scoring)`
  - `MODEL_REGISTRY: dict[str, ModelSpec]` with keys `"ridge"`, `"random_forest"`,
    `"gradient_boosting"`, `"logistic_regression"`, `"random_forest_clf"`
  - `prepare(df, target, features, time_column) -> tuple[DataFrame, Series]`
  - `build_pipeline(model_type, hyperparams, numeric, categorical) -> Pipeline`
  - `split_frame(x, y, chronological) -> tuple[DataFrame, DataFrame, Series, Series]`
  - `cv_splitter(chronological) -> TimeSeriesSplit | KFold`
  - `fit_and_score(model_type, hyperparams, df, target, features, time_column) -> TrainResult`
  - `cv_objective(model_type, hyperparams, df, target, features, time_column) -> tuple[float, float]`
    — **(mean, std)**, not a bare float; the std is required by the reporting rule in Global
    Constraints, and Task 7 logs it as `cv_std`.

- [x] **Step 1: Add the dependency and settings**

```bash
poetry add "scikit-learn@^1.9"
```

Add to `backend/app/config.py`, after the profiler block:

```python
    # Training (Project 2 §3.6). Seeded so a re-run of the same experiment
    # reproduces the same metrics — otherwise MLflow history is not comparable.
    train_test_size: float = 0.2
    train_test_seed: int = 42
    cv_folds: int = 5
    # Categorical columns above this many distinct values are treated as
    # identifiers, not features (§3.3).
    feature_max_cardinality: int = 20
```

- [x] **Step 2: Write the failing tests**

Create `backend/tests/test_training.py`:

```python
import numpy as np
import pandas as pd
import pytest
from sklearn.model_selection import KFold, TimeSeriesSplit

from app.training import (
    MODEL_REGISTRY,
    cv_objective,
    cv_splitter,
    fit_and_score,
    prepare,
    split_frame,
)

REGRESSORS = sorted(k for k, s in MODEL_REGISTRY.items() if s.task_type == "regression")
CLASSIFIERS = sorted(k for k, s in MODEL_REGISTRY.items() if s.task_type == "classification")


def make_frame(n: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    memory = rng.integers(4, 25, n)
    chipset = rng.choice(["a", "b", "c"], n)
    price = memory * 30.0 + rng.normal(0, 5, n)
    return pd.DataFrame({"memory": memory, "chipset": chipset, "price": price})


def make_panel(n: int = 60) -> pd.DataFrame:
    """A time-indexed frame whose target rises monotonically with time.

    That monotonicity is what makes the chronological-split test meaningful: if
    the split is honoured, every test target exceeds every train target.
    """
    df = make_frame(n)
    df["as_of"] = pd.date_range("2015-01-01", periods=n, freq="QE")
    df["price"] = np.arange(n, dtype=float) * 10.0
    return df


def make_labels(n: int = 60) -> pd.DataFrame:
    df = make_frame(n)
    df["direction"] = np.where(df["memory"] > 14, "up", "down")
    return df


def test_prepare_drops_null_target_rows():
    df = make_frame(10)
    df.loc[0:2, "price"] = None
    x, y = prepare(df, "price", ["memory", "chipset"], None)
    assert len(x) == len(y) == 7
    assert not y.isna().any()


def test_prepare_rejects_missing_target():
    with pytest.raises(ValueError, match="target"):
        prepare(make_frame(5), "nope", ["memory"], None)


def test_prepare_rejects_all_null_target():
    df = make_frame(5)
    df["price"] = None
    with pytest.raises(ValueError, match="non-null"):
        prepare(df, "price", ["memory"], None)


def test_prepare_sorts_by_the_time_column_and_drops_it_from_features():
    df = make_panel(12).sample(frac=1, random_state=1)  # deliberately shuffled
    x, y = prepare(df, "price", ["memory", "as_of"], "as_of")
    assert "as_of" not in x.columns
    assert list(y) == sorted(y)


def test_prepare_rejects_an_unknown_time_column():
    with pytest.raises(ValueError, match="time column"):
        prepare(make_frame(5), "price", ["memory"], "nope")


def test_chronological_split_puts_the_latest_rows_in_test():
    x, y = prepare(make_panel(50), "price", ["memory", "chipset"], "as_of")
    _, _, y_train, y_test = split_frame(x, y, chronological=True)
    assert y_train.max() < y_test.min()


def test_random_split_does_not_preserve_time_order():
    x, y = prepare(make_panel(50), "price", ["memory", "chipset"], "as_of")
    _, _, y_train, y_test = split_frame(x, y, chronological=False)
    assert y_train.max() > y_test.min()


def test_cv_splitter_is_time_aware_only_when_chronological():
    assert isinstance(cv_splitter(chronological=True), TimeSeriesSplit)
    assert isinstance(cv_splitter(chronological=False), KFold)


@pytest.mark.parametrize("model_type", REGRESSORS)
def test_every_regressor_fits_and_scores(model_type):
    result = fit_and_score(model_type, {}, make_frame(), "price", ["memory", "chipset"], None)
    assert result.status == "FINISHED"
    assert set(result.metrics) == {"rmse", "mae", "r2"}
    assert result.metrics["rmse"] > 0
    assert result.model is not None
    assert result.error is None


@pytest.mark.parametrize("model_type", CLASSIFIERS)
def test_every_classifier_fits_and_scores(model_type):
    result = fit_and_score(model_type, {}, make_labels(), "direction", ["memory"], None)
    assert result.status == "FINISHED"
    assert set(result.metrics) == {"accuracy", "f1_macro", "precision_macro", "recall_macro"}
    assert 0.0 <= result.metrics["f1_macro"] <= 1.0


def test_every_registry_entry_declares_a_coherent_direction():
    # The review's point 3: a maximising metric under a minimising study
    # silently selects the worst model. Assert the pairing, do not trust it.
    for name, spec in MODEL_REGISTRY.items():
        assert spec.task_type in {"regression", "classification"}, name
        assert spec.direction in {"minimize", "maximize"}, name
        if spec.task_type == "regression":
            assert spec.direction == "minimize", name
        else:
            assert spec.direction == "maximize", name


def test_fit_is_deterministic():
    args = ("random_forest", {}, make_frame(), "price", ["memory", "chipset"], None)
    assert fit_and_score(*args).metrics == fit_and_score(*args).metrics


def test_unknown_model_type_fails_without_raising():
    result = fit_and_score("nope", {}, make_frame(), "price", ["memory"], None)
    assert result.status == "FAILED"
    assert result.metrics == {}
    assert result.model is None
    assert "nope" in (result.error or "")


def test_bad_hyperparams_fail_without_raising():
    result = fit_and_score(
        "random_forest", {"n_estimators": -5}, make_frame(), "price", ["memory"], None
    )
    assert result.status == "FAILED"
    assert result.error


def test_unseen_category_at_predict_time_does_not_crash():
    df = make_frame(60)
    df.loc[df.index[-5:], "chipset"] = "rare"
    result = fit_and_score("ridge", {}, df, "price", ["memory", "chipset"], None)
    assert result.status == "FINISHED"


def test_cv_objective_returns_a_mean_and_a_std():
    mean, std = cv_objective("ridge", {}, make_frame(), "price", ["memory", "chipset"], None)
    assert mean > 0
    assert std >= 0


def test_cv_objective_is_positive_for_a_maximising_classifier():
    mean, _ = cv_objective("logistic_regression", {}, make_labels(), "direction", ["memory"], None)
    assert 0.0 <= mean <= 1.0
```

- [x] **Step 3: Run the tests to verify they fail**

Run: `poetry run pytest backend/tests/test_training.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.training'`

- [x] **Step 4: Implement `app/training.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (
    GradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    precision_score,
    r2_score,
    recall_score,
    root_mean_squared_error,
)
from sklearn.model_selection import KFold, TimeSeriesSplit, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from app.config import settings

# One search-space entry: (kind, low, high, log). `kind` is "int" or "float".
SearchSpace = dict[str, tuple[str, float, float, bool]]


@dataclass(frozen=True)
class ModelSpec:
    """One registered model.

    `objective_metric` and `direction` are per entry, never global: a maximising
    metric optimised by a minimising study picks the worst model and says
    nothing about it (design review, point 3).
    """

    task_type: str  # "regression" | "classification"
    factory: Callable[..., Any]
    search_space: SearchSpace
    objective_metric: str  # the key in `metrics` this model is ranked on
    direction: str  # "minimize" | "maximize" — must agree with cv_scoring
    cv_scoring: str  # an sklearn scorer name for cross_val_score


@dataclass(frozen=True)
class TrainResult:
    status: str  # "FINISHED" | "FAILED"
    metrics: dict[str, float]
    params: dict[str, Any]
    error: str | None
    model: Any | None


# Each entry carries the estimator, its search space, AND how it is scored, so
# /train, /tune, and the Optuna study can never disagree about any of the three.
MODEL_REGISTRY: dict[str, ModelSpec] = {
    "ridge": ModelSpec(
        task_type="regression",
        factory=Ridge,
        search_space={"alpha": ("float", 1e-3, 1e3, True)},
        objective_metric="rmse",
        direction="minimize",
        cv_scoring="neg_root_mean_squared_error",
    ),
    "random_forest": ModelSpec(
        task_type="regression",
        factory=RandomForestRegressor,
        search_space={
            "n_estimators": ("int", 50, 400, False),
            "max_depth": ("int", 2, 20, False),
            "min_samples_leaf": ("int", 1, 10, False),
        },
        objective_metric="rmse",
        direction="minimize",
        cv_scoring="neg_root_mean_squared_error",
    ),
    "gradient_boosting": ModelSpec(
        task_type="regression",
        factory=GradientBoostingRegressor,
        search_space={
            "n_estimators": ("int", 50, 400, False),
            "learning_rate": ("float", 1e-3, 0.3, True),
            "max_depth": ("int", 2, 8, False),
        },
        objective_metric="rmse",
        direction="minimize",
        cv_scoring="neg_root_mean_squared_error",
    ),
    "logistic_regression": ModelSpec(
        task_type="classification",
        factory=LogisticRegression,
        search_space={"C": ("float", 1e-3, 1e2, True)},
        objective_metric="f1_macro",
        direction="maximize",
        cv_scoring="f1_macro",
    ),
    "random_forest_clf": ModelSpec(
        task_type="classification",
        factory=RandomForestClassifier,
        search_space={
            "n_estimators": ("int", 50, 400, False),
            "max_depth": ("int", 2, 20, False),
            "min_samples_leaf": ("int", 1, 10, False),
        },
        objective_metric="f1_macro",
        direction="maximize",
        cv_scoring="f1_macro",
    ),
}


def prepare(
    df: pd.DataFrame, target: str, features: list[str], time_column: str | None
) -> tuple[pd.DataFrame, pd.Series]:
    """Select features and target, dropping rows with a null target.

    When `time_column` is given, rows are sorted by it and the column itself is
    excluded from the features — it is the split axis, not a predictor. Sorting
    here (rather than trusting the CSV) is what makes `split_frame` and
    `cv_splitter` correct no matter how the file arrived.
    """
    if target not in df.columns:
        raise ValueError(f"target column {target!r} is not in the dataset")
    if time_column is not None and time_column not in df.columns:
        raise ValueError(f"time column {time_column!r} is not in the dataset")
    features = [f for f in features if f != time_column]
    missing = [f for f in features if f not in df.columns]
    if missing:
        raise ValueError(f"feature columns not in the dataset: {missing}")

    keep = [*features, target] if time_column is None else [*features, target, time_column]
    frame = df[keep].dropna(subset=[target])
    if time_column is not None:
        frame = frame.sort_values(time_column, kind="stable").drop(columns=[time_column])
    if frame.empty:
        raise ValueError(f"no rows have a non-null {target!r}")
    return frame[features], frame[target]


def split_frame(
    x: pd.DataFrame, y: pd.Series, chronological: bool
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    """Holdout split. Chronological means the test set is the LATEST rows.

    `prepare` has already sorted by time, so the cut is a positional slice.
    """
    if chronological:
        cut = int(len(x) * (1 - settings.train_test_size))
        return x.iloc[:cut], x.iloc[cut:], y.iloc[:cut], y.iloc[cut:]
    return train_test_split(
        x, y, test_size=settings.train_test_size, random_state=settings.train_test_seed
    )


def cv_splitter(chronological: bool) -> TimeSeriesSplit | KFold:
    """Expanding-window CV for time series, shuffled k-fold otherwise.

    `TimeSeriesSplit` never puts a later row in a fold used to train for an
    earlier one, which is the whole point.
    """
    if chronological:
        return TimeSeriesSplit(n_splits=settings.cv_folds)
    return KFold(n_splits=settings.cv_folds, shuffle=True, random_state=settings.train_test_seed)


def _column_kinds(x: pd.DataFrame) -> tuple[list[str], list[str]]:
    numeric = [c for c in x.columns if pd.api.types.is_numeric_dtype(x[c])]
    return numeric, [c for c in x.columns if c not in numeric]


def build_pipeline(
    model_type: str, hyperparams: dict[str, Any], numeric: list[str], categorical: list[str]
) -> Pipeline:
    if model_type not in MODEL_REGISTRY:
        raise ValueError(f"unknown model_type {model_type!r}; known: {sorted(MODEL_REGISTRY)}")
    # Scaling lives INSIDE the pipeline so cross_val_score refits it per fold.
    # Scaling before the split fits the scaler on the test rows — a quiet leak
    # that no metric reveals (design §3.6).
    # sparse_output=False keeps the matrix dense: at these row counts the memory
    # cost is nil, and every estimator accepts it without a sparse-support caveat.
    pre = ColumnTransformer(
        [
            (
                "num",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="median")),
                        ("scale", StandardScaler()),
                    ]
                ),
                numeric,
            ),
            (
                "cat",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        ("ohe", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
                    ]
                ),
                categorical,
            ),
        ],
        remainder="drop",
    )
    estimator = MODEL_REGISTRY[model_type].factory(**hyperparams)
    return Pipeline([("pre", pre), ("model", estimator)])


def _score(task_type: str, y_true: Any, pred: Any) -> dict[str, float]:
    if task_type == "regression":
        return {
            "rmse": float(root_mean_squared_error(y_true, pred)),
            "mae": float(mean_absolute_error(y_true, pred)),
            "r2": float(r2_score(y_true, pred)),
        }
    return {
        "accuracy": float(accuracy_score(y_true, pred)),
        "f1_macro": float(f1_score(y_true, pred, average="macro", zero_division=0)),
        "precision_macro": float(precision_score(y_true, pred, average="macro", zero_division=0)),
        "recall_macro": float(recall_score(y_true, pred, average="macro", zero_division=0)),
    }


def fit_and_score(
    model_type: str,
    hyperparams: dict[str, Any],
    df: pd.DataFrame,
    target: str,
    features: list[str],
    time_column: str | None = None,
) -> TrainResult:
    """Fit on the train split, score on the held-out test split.

    When `time_column` is given the split is chronological: the test set is the
    latest rows, never a random sample. Never raises — a bad model_type or bad
    hyperparams come back as status="FAILED" so the caller can still record the
    failure as history (§8).
    """
    try:
        if model_type not in MODEL_REGISTRY:
            raise ValueError(f"unknown model_type {model_type!r}; known: {sorted(MODEL_REGISTRY)}")
        spec = MODEL_REGISTRY[model_type]
        x, y = prepare(df, target, features, time_column)
        numeric, categorical = _column_kinds(x)
        pipeline = build_pipeline(model_type, hyperparams, numeric, categorical)
        x_train, x_test, y_train, y_test = split_frame(x, y, chronological=time_column is not None)
        pipeline.fit(x_train, y_train)
        pred = pipeline.predict(x_test)
        return TrainResult(
            "FINISHED", _score(spec.task_type, y_test, pred), dict(hyperparams), None, pipeline
        )
    except Exception as exc:  # noqa: BLE001 — failures are data, not crashes (§8)
        return TrainResult("FAILED", {}, dict(hyperparams), f"{type(exc).__name__}: {exc}", None)


def cv_objective(
    model_type: str,
    hyperparams: dict[str, Any],
    df: pd.DataFrame,
    target: str,
    features: list[str],
    time_column: str | None = None,
) -> tuple[float, float]:
    """Cross-validated score on the TRAIN split only, as (mean, std).

    Optuna optimises this, never the test split — tuning against the split you
    then report is not a measurement. The std comes back with it because a
    ~180-row train split cannot separate two models on a point estimate
    (Global Constraints); Task 7 logs it as `cv_std` beside the mean.

    The sign is normalised here: sklearn's `neg_*` scorers are higher-is-better,
    so a "neg_" prefix means the raw score must be negated to recover the metric
    the registry's `direction` refers to.
    """
    if model_type not in MODEL_REGISTRY:
        raise ValueError(f"unknown model_type {model_type!r}; known: {sorted(MODEL_REGISTRY)}")
    spec = MODEL_REGISTRY[model_type]
    chronological = time_column is not None
    x, y = prepare(df, target, features, time_column)
    numeric, categorical = _column_kinds(x)
    x_train, _, y_train, _ = split_frame(x, y, chronological=chronological)
    pipeline = build_pipeline(model_type, hyperparams, numeric, categorical)
    scores = cross_val_score(
        pipeline,
        x_train,
        y_train,
        cv=cv_splitter(chronological),
        scoring=spec.cv_scoring,
    )
    if spec.cv_scoring.startswith("neg_"):
        scores = -scores
    return float(scores.mean()), float(scores.std())
```

- [x] **Step 5: Run the tests to verify they pass**

Run: `poetry run pytest backend/tests/test_training.py -v`
Expected: PASS, 21 tests (5 parametrized across the two task types).

- [x] **Step 6: Run the full gate and commit**

```bash
make check
git add backend/app/training.py backend/app/config.py backend/tests/test_training.py pyproject.toml poetry.lock
git commit -m "feat: app/training.py — task-typed, time-aware sklearn core with a model registry"
```

---

## Task 4: Feature inference from the DataFrame

Keeps the endpoints domain-agnostic (D1) without hard-coding column names.

**This corrects an error in the design, found by the review (point 7).** The earlier draft
inferred features from `datasets.profile_json`, reading a per-column `n_unique` key. **That
key does not exist.** `app/profiler.py:46` emits exactly `{"name", "dtype", "n_null"}` per
column; cardinality lives only in `categorical_summary`, which `profile_dataframe` **empties
to `{}`** whenever the profile degrades past its token budget. So the profile-based version
would have silently classed every categorical as unusable on exactly the wide datasets where
inference matters most.

Infer from the DataFrame instead. The route already parses `data_csv` into a DataFrame to
train on, so this costs nothing and reads the real dtypes rather than a serialized summary of
them.

**Files:**
- Modify: `backend/app/training.py`
- Test: `backend/tests/test_training_features.py`

**Interfaces:**
- Consumes: the DataFrame the route already builds via `dataset_io.load_csv()`.
- Produces:
  `infer_feature_columns(df: DataFrame, target: str, max_cardinality: int, time_column: str | None = None) -> list[str]`

- [x] **Step 1: Confirm the profile really lacks `n_unique`, so the correction is on record**

```bash
poetry run python -c "
import json, pandas as pd
from app.profiler import profile_dataframe
df = pd.read_csv('data-sources/prepared/revenue_nowcast.csv')
p = profile_dataframe(df, sample_rows=2, max_cardinality=20, max_corr_cols=30, top_corr_pairs=25, token_budget=8000)
print('column keys:', sorted(p['columns'][0]))
print('degraded:', p.get('degraded'))
" | sed 's/^/| /'
```

Expected: `column keys: ['dtype', 'n_null', 'name']` — no `n_unique`. Paste this output into
the PR description; it is the evidence for the design amendment recorded in Task 11.

- [x] **Step 2: Write the failing tests**

Create `backend/tests/test_training_features.py`:

```python
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
    assert "ticker" in got                # 5 distinct values — a real categorical
    assert "revenue_usd" in got
    assert "as_of" not in got             # excluded as the split axis
    # `quarter_end` survives read_csv as a high-cardinality string, so it is the
    # cardinality rule — not the dtype rule — that drops it. Assert it either way.
    assert "quarter_end" not in got
    assert "revenue_next_usd" not in got  # the target
```

**One consequence worth knowing before Task 6:** `dataset_io.load_csv()` does not parse dates,
so `as_of` arrives as an ISO-8601 **string**. Sorting on it in `prepare()` is still correct —
ISO-8601 sorts lexicographically in date order — and that is precisely why the prepared CSV
must keep ISO dates. Do not "improve" `prepare()` by coercing the time column to datetime;
do not change the date format in `prepare_dataset.py`.

- [x] **Step 3: Run the tests to verify they fail**

Run: `poetry run pytest backend/tests/test_training_features.py -v`
Expected: FAIL — `ImportError: cannot import name 'infer_feature_columns'`

- [x] **Step 4: Implement it in `app/training.py`**

Append to `backend/app/training.py`:

```python
def infer_feature_columns(
    df: pd.DataFrame,
    target: str,
    max_cardinality: int,
    time_column: str | None = None,
) -> list[str]:
    """Pick features from the DataFrame itself (design §3.3).

    Numeric columns, plus categoricals at or below `max_cardinality` distinct
    values. Excluded: the target, the time column, anything datetime-like, and
    high-cardinality text — an identifier one-hot-encodes into one column per
    row, which is memorisation, not a feature.

    Deliberately NOT driven by `datasets.profile_json`: that structure carries
    no per-column cardinality (`app/profiler.py:46` emits name/dtype/n_null
    only), and its `categorical_summary` is emptied whenever the profile
    degrades past its token budget.
    """
    if target not in df.columns:
        raise ValueError(f"target column {target!r} is not in the dataset")
    features: list[str] = []
    for name in df.columns:
        if name == target or name == time_column:
            continue
        series = df[name]
        if pd.api.types.is_datetime64_any_dtype(series):
            continue
        if pd.api.types.is_bool_dtype(series):
            features.append(str(name))
            continue
        if pd.api.types.is_numeric_dtype(series):
            features.append(str(name))
            continue
        if series.nunique(dropna=True) <= max_cardinality:
            features.append(str(name))
    if not features:
        raise ValueError(f"no usable feature columns for target {target!r}")
    return features
```

- [x] **Step 5: Run the tests to verify they pass**

Run: `poetry run pytest backend/tests/test_training_features.py -v`
Expected: PASS, 9 tests.

- [x] **Step 6: Commit**

```bash
make check
git add backend/app/training.py backend/tests/test_training_features.py
git commit -m "feat: infer feature columns from the DataFrame, not the profile"
```

---

## Task 5: `app/experiment_log.py` — the MLflow seam

The only module that imports `mlflow`. Tested against **real MLflow** on a per-test SQLite
tracking store, because a mock of the one module whose entire job is SDK access proves
nothing.

**Files:**
- Create: `backend/app/experiment_log.py`
- Test: `backend/tests/test_experiment_log.py`

**Interfaces:**
- Consumes: `app.training.TrainResult`, `app.config.settings.mlflow_tracking_uri`.
- Produces:
  - `RunData(run_id: str, status: str, params: dict[str, str], metrics: dict[str, float])`
  - `log_run(experiment_name, model_type, task_type, params, result, dataset_id, dataset_version, target, features, time_column=None) -> str`
  - `fetch_runs(run_ids: list[str]) -> dict[str, RunData]`
  - `search_runs(metric_filters, param_filters, statuses) -> list[str]`

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_experiment_log.py`:

```python
import pandas as pd
import pytest

from app import experiment_log
from app.training import TrainResult, fit_and_score


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A real MLflow tracking store, per test.

    Must be sqlite:// — MLflow 3.15 refuses a file:// backend outright.
    """
    uri = f"sqlite:///{tmp_path}/mlflow.db"
    monkeypatch.setattr(experiment_log.settings, "mlflow_tracking_uri", uri)
    monkeypatch.setattr(experiment_log.settings, "mlflow_artifact_root", str(tmp_path / "art"))
    return uri


def frame():
    return pd.DataFrame({"memory": [4, 8, 12, 16, 20, 24] * 5, "price": [1.0, 2, 3, 4, 5, 6] * 5})


def test_log_run_records_params_metrics_and_target(store):
    result = fit_and_score("ridge", {"alpha": 0.5}, frame(), "price", ["memory"])
    run_id = experiment_log.log_run(
        "adhoc", "ridge", "regression", {"alpha": 0.5}, result,
        "ds-1", "hash-abc", "price", ["memory"],
    )
    fetched = experiment_log.fetch_runs([run_id])[run_id]
    assert fetched.status == "FINISHED"
    assert fetched.params["model_type"] == "ridge"
    assert fetched.params["task_type"] == "regression"
    assert fetched.params["target_column"] == "price"
    assert fetched.params["feature_columns"] == "memory"
    assert fetched.metrics["rmse"] >= 0


def test_a_random_split_is_recorded_as_such(store):
    result = fit_and_score("ridge", {}, frame(), "price", ["memory"])
    run_id = experiment_log.log_run(
        "adhoc", "ridge", "regression", {}, result, None, None, "price", ["memory"]
    )
    assert experiment_log.fetch_runs([run_id])[run_id].params["split"] == "random"


def test_a_chronological_split_is_recorded_with_its_time_column(store):
    result = fit_and_score("ridge", {}, frame(), "price", ["memory"])
    run_id = experiment_log.log_run(
        "adhoc", "ridge", "regression", {}, result, None, None, "price", ["memory"],
        time_column="as_of",
    )
    params = experiment_log.fetch_runs([run_id])[run_id].params
    assert params["split"] == "chronological"
    assert params["time_column"] == "as_of"


def test_failed_result_is_logged_as_a_failed_run(store):
    failed = TrainResult("FAILED", {}, {"alpha": 1}, "ValueError: boom", None)
    run_id = experiment_log.log_run(
        "adhoc", "ridge", "regression", {"alpha": 1}, failed, None, None, "price", ["memory"]
    )
    fetched = experiment_log.fetch_runs([run_id])[run_id]
    assert fetched.status == "FAILED"
    assert fetched.metrics == {}


def test_fetch_runs_is_one_call_for_many_ids(store):
    ids = [
        experiment_log.log_run(
            "adhoc",
            "ridge",
            "regression",
            {"alpha": a},
            fit_and_score("ridge", {"alpha": a}, frame(), "price", ["memory"]),
            None,
            None,
            "price",
            ["memory"],
        )
        for a in (0.1, 0.2, 0.3)
    ]
    fetched = experiment_log.fetch_runs(ids)
    assert set(fetched) == set(ids)


def test_fetch_runs_of_nothing_makes_no_call(store):
    assert experiment_log.fetch_runs([]) == {}


def test_search_runs_filters_by_status(store):
    ok = experiment_log.log_run(
        "adhoc", "ridge", "regression", {},
        fit_and_score("ridge", {}, frame(), "price", ["memory"]),
        None, None, "price", ["memory"],
    )
    experiment_log.log_run(
        "adhoc", "ridge", "regression", {}, TrainResult("FAILED", {}, {}, "boom", None),
        None, None, "price", ["memory"],
    )
    assert experiment_log.search_runs(None, None, ["FINISHED"]) == [ok]


def test_empty_tracking_uri_fails_fast(monkeypatch):
    monkeypatch.setattr(experiment_log.settings, "mlflow_tracking_uri", "")
    with pytest.raises(RuntimeError, match="MLFLOW_TRACKING_URI"):
        experiment_log.fetch_runs(["anything"])
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `poetry run pytest backend/tests/test_experiment_log.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.experiment_log'`

- [x] **Step 3: Implement `app/experiment_log.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import mlflow
import mlflow.sklearn
from mlflow.entities import Run

from app.config import settings
from app.training import TrainResult


@dataclass(frozen=True)
class RunData:
    run_id: str
    status: str
    params: dict[str, str]  # MLflow stores every param as a string
    metrics: dict[str, float]


def _require_uri() -> str:
    """MLflow 3.x refuses a filesystem backend, so an unset URI is not a
    silent fallback to ./mlruns — it is a confusing library-internal error.
    Turn it into a clear one."""
    if not settings.mlflow_tracking_uri:
        raise RuntimeError(
            "MLFLOW_TRACKING_URI is not set. Run `make db-up && make mlflow-init`, "
            "then set mlflow_tracking_uri in .env."
        )
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    return settings.mlflow_tracking_uri


def _experiment_id(name: str) -> str:
    existing = mlflow.get_experiment_by_name(name)
    if existing is not None:
        return str(existing.experiment_id)
    return str(mlflow.create_experiment(name, artifact_location=settings.mlflow_artifact_root))


def _to_run_data(run: Run) -> RunData:
    return RunData(
        run_id=str(run.info.run_id),
        status=str(run.info.status),
        params={str(k): str(v) for k, v in run.data.params.items()},
        metrics={str(k): float(v) for k, v in run.data.metrics.items()},
    )


def log_run(
    experiment_name: str,
    model_type: str,
    task_type: str,
    params: dict[str, Any],
    result: TrainResult,
    dataset_id: str | None,
    dataset_version: str | None,
    target: str,
    features: list[str],
    time_column: str | None = None,
) -> str:
    """Write one run. Returns its mlflow_run_id.

    target/features are logged as params, not tags: without them "which model
    performed best" would compare runs trained against different targets.
    `task_type` joins them for the same reason — an rmse and an f1_macro are not
    on a common scale, so a leaderboard that mixes them is meaningless.
    `time_column` records HOW the run was split; a run logged without it was
    split randomly, and that distinction must survive into the history.
    """
    _require_uri()
    run = mlflow.start_run(experiment_id=_experiment_id(experiment_name))
    status = "FAILED"
    try:
        mlflow.log_params(
            {
                "model_type": model_type,
                "task_type": task_type,
                "target_column": target,
                "feature_columns": ",".join(features),
                "time_column": time_column or "",
                "split": "chronological" if time_column else "random",
                **{k: str(v) for k, v in params.items()},
            }
        )
        mlflow.set_tags(
            {"dataset_id": dataset_id or "", "dataset_version": dataset_version or ""}
        )
        if result.status == "FINISHED":
            mlflow.log_metrics(result.metrics)
            if result.model is not None:
                mlflow.sklearn.log_model(result.model, name="model")
            status = "FINISHED"
        else:
            mlflow.set_tag("error", result.error or "")
    finally:
        mlflow.end_run(status=status)
    return str(run.info.run_id)


def fetch_runs(run_ids: list[str]) -> dict[str, RunData]:
    """Params and metrics for many runs in ONE search call.

    Verified against mlflow 3.15.1: `attributes.run_id IN (...)` is supported.
    A per-id get_run loop here would be an N+1 across a process boundary.
    """
    if not run_ids:
        return {}
    _require_uri()
    quoted = ",".join(f"'{r}'" for r in run_ids)
    runs = mlflow.search_runs(
        search_all_experiments=True,
        filter_string=f"attributes.run_id IN ({quoted})",
        output_format="list",
    )
    return {str(r.info.run_id): _to_run_data(r) for r in runs}


def search_runs(
    metric_filters: list[str] | None,
    param_filters: list[str] | None,
    statuses: list[str] | None,
) -> list[str]:
    """Run ids matching MLflow-side filters. This is D15's structured stage —
    Phase 3's agent calls it too, rather than reaching for the SDK itself."""
    _require_uri()
    clauses = [*(metric_filters or []), *(param_filters or [])]
    if statuses:
        clauses.append("attributes.status IN ({})".format(",".join(f"'{s}'" for s in statuses)))
    runs = mlflow.search_runs(
        search_all_experiments=True,
        filter_string=" and ".join(clauses) if clauses else "",
        output_format="list",
    )
    return [str(r.info.run_id) for r in runs]
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `poetry run pytest backend/tests/test_experiment_log.py -v`
Expected: PASS, 8 tests.

- [x] **Step 5: Commit**

```bash
make check
git add backend/app/experiment_log.py backend/tests/test_experiment_log.py
git commit -m "feat: app/experiment_log.py — the single MLflow boundary"
```

---

## Task 6: `POST /experiments/train` (Flow A)

**Files:**
- Create: `backend/app/routes/experiments.py`
- Modify: `backend/app/schemas.py`, `backend/app/main.py`, `backend/app/models.py`
- Create: one Alembic migration adding `experiments.task_type` and `experiments.notes_status`
- Test: `backend/tests/test_routes_experiments_train.py`

**Interfaces:**
- Consumes: `training.fit_and_score`, `training.infer_feature_columns`,
  `training.MODEL_REGISTRY`, `experiment_log.log_run`, `dataset_io.load_csv`,
  `models.Dataset`, `models.Experiment`.
- Produces: `TrainRequest`, `ExperimentOut`, `_validate_columns`, `_resolve_features`, and
  `_load_training_frame(session, dataset_id) -> tuple[DataFrame, Dataset]`, reused by Task 7.

- [x] **Step 1: Add `task_type` and `notes_status` to the `Experiment` model**

Two columns, one migration — a second Alembic revision for a sibling column on the same table
is pure churn.

`task_type`: a leaderboard that mixes an `rmse` and an `f1_macro` compares nothing, so the
discriminator has to be a column, not something reconstructed from `model_type` at read time.

`notes_status`: **D20** — an LLM-written note is a draft until a human has read it. Nothing
generated may present itself as reviewed, so the status is set at creation (`"draft"`) and can
only be changed through the review endpoint in Task 8, to `"approved"` or `"rejected"`. Phase 3
embeds approved notes only; a run created here with empty notes is still a draft, because
"nobody has looked at this" is exactly what the column means.

In `backend/app/models.py`, on `Experiment`, beside `model_type`:

```python
    task_type: Mapped[str] = mapped_column(String(32), nullable=False, server_default="regression")
    notes_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
```

`server_default` rather than a Python default on both, so the migration backfills whatever rows
Phase 1 already wrote without a separate data step.

```bash
make migration m="add experiments.task_type and notes_status"
# Review the generated file: it must touch ONLY app.experiments, and it must add
# exactly two columns. If it proposes dropping anything in the mlflow schema, the
# app_schema_only filter is broken — stop and fix that first (CLAUDE.md).
make migrate
```

- [x] **Step 2: Write the failing tests**

Create `backend/tests/test_routes_experiments_train.py`:

```python
import io

import pytest

from app import experiment_log
from app.models import Experiment

CSV = "memory,chipset,price\n" + "".join(
    f"{4 * (i % 6) + 4},{'abc'[i % 3]},{100 + i}\n" for i in range(40)
)

# A tiny temporal panel: `as_of` ascends, `price` ascends with it.
PANEL_CSV = "as_of,memory,price\n" + "".join(
    f"20{20 + i // 4:02d}-{3 * (i % 4) + 1:02d}-01,{4 * (i % 6) + 4},{100 + i}\n"
    for i in range(40)
)


@pytest.fixture
def dataset_id(client):
    resp = client.post("/datasets", files={"file": ("t.csv", io.BytesIO(CSV.encode()), "text/csv")})
    assert resp.status_code == 200
    return resp.json()["id"]


@pytest.fixture
def panel_id(client):
    resp = client.post(
        "/datasets", files={"file": ("p.csv", io.BytesIO(PANEL_CSV.encode()), "text/csv")}
    )
    assert resp.status_code == 200
    return resp.json()["id"]


@pytest.fixture(autouse=True)
def mlflow_store(tmp_path, monkeypatch):
    monkeypatch.setattr(
        experiment_log.settings, "mlflow_tracking_uri", f"sqlite:///{tmp_path}/mlflow.db"
    )
    monkeypatch.setattr(experiment_log.settings, "mlflow_artifact_root", str(tmp_path / "art"))


def test_train_returns_ids_and_metrics(client, dataset_id):
    resp = client.post(
        "/experiments/train",
        json={"model_type": "ridge", "dataset_id": dataset_id, "target_column": "price"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "FINISHED"
    assert body["mlflow_run_id"]
    assert body["task_type"] == "regression"
    assert body["metrics"]["rmse"] >= 0


def test_a_classifier_returns_classification_metrics(client, dataset_id):
    # `chipset` is the 3-class label; `memory` and `price` are the features.
    resp = client.post(
        "/experiments/train",
        json={
            "model_type": "logistic_regression",
            "dataset_id": dataset_id,
            "target_column": "chipset",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["task_type"] == "classification"
    assert "f1_macro" in body["metrics"]
    assert "rmse" not in body["metrics"]


def test_a_time_column_records_a_chronological_split(client, panel_id, db_session):
    resp = client.post(
        "/experiments/train",
        json={
            "model_type": "ridge",
            "dataset_id": panel_id,
            "target_column": "price",
            "time_column": "as_of",
        },
    )
    assert resp.status_code == 200
    run_id = resp.json()["mlflow_run_id"]
    params = experiment_log.fetch_runs([run_id])[run_id].params
    assert params["split"] == "chronological"
    assert params["time_column"] == "as_of"
    # The split axis must never also be a feature.
    assert "as_of" not in params["feature_columns"].split(",")


def test_omitting_the_time_column_falls_back_to_a_random_split(client, panel_id):
    resp = client.post(
        "/experiments/train",
        json={"model_type": "ridge", "dataset_id": panel_id, "target_column": "price"},
    )
    run_id = resp.json()["mlflow_run_id"]
    assert experiment_log.fetch_runs([run_id])[run_id].params["split"] == "random"


def test_an_unknown_time_column_is_422_not_a_silent_random_split(client, panel_id):
    # The dangerous failure mode is a typo'd time_column quietly producing a
    # leaky random split that still returns 200 with flattering metrics.
    resp = client.post(
        "/experiments/train",
        json={
            "model_type": "ridge",
            "dataset_id": panel_id,
            "target_column": "price",
            "time_column": "as_off",
        },
    )
    assert resp.status_code == 422


def test_train_persists_an_experiment_row_with_the_dataset_hash(client, dataset_id, db_session):
    resp = client.post(
        "/experiments/train",
        json={
            "model_type": "ridge",
            "dataset_id": dataset_id,
            "target_column": "price",
            "notes": "baseline",
        },
    )
    row = db_session.get(Experiment, resp.json()["experiment_id"])
    assert row is not None
    assert row.dataset_id == dataset_id
    assert row.model_type == "ridge"
    assert row.notes == "baseline"
    assert len(row.dataset_version or "") == 64  # the dataset's SHA-256 content hash


def test_a_new_experiment_starts_as_an_unreviewed_draft(client, dataset_id, db_session):
    # D20: nothing the machine writes may present itself as reviewed. Even a note
    # typed by hand at train time is a draft — the route is not a review.
    resp = client.post(
        "/experiments/train",
        json={
            "model_type": "ridge",
            "dataset_id": dataset_id,
            "target_column": "price",
            "notes": "typed by a human, still unreviewed",
        },
    )
    row = db_session.get(Experiment, resp.json()["experiment_id"])
    assert row is not None
    assert row.notes_status == "draft"


def test_a_failed_fit_is_200_and_still_recorded(client, dataset_id, db_session):
    resp = client.post(
        "/experiments/train",
        json={
            "model_type": "random_forest",
            "hyperparams": {"n_estimators": -1},
            "dataset_id": dataset_id,
            "target_column": "price",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "FAILED"
    assert db_session.get(Experiment, resp.json()["experiment_id"]) is not None


def test_unknown_model_type_is_422(client, dataset_id):
    resp = client.post(
        "/experiments/train",
        json={"model_type": "nope", "dataset_id": dataset_id, "target_column": "price"},
    )
    assert resp.status_code == 422


def test_missing_dataset_is_404(client):
    resp = client.post(
        "/experiments/train",
        json={"model_type": "ridge", "dataset_id": "nope", "target_column": "price"},
    )
    assert resp.status_code == 404


def test_target_not_a_column_is_422(client, dataset_id):
    resp = client.post(
        "/experiments/train",
        json={"model_type": "ridge", "dataset_id": dataset_id, "target_column": "nope"},
    )
    assert resp.status_code == 422
```

- [x] **Step 3: Add the `db_session` fixture**

These tests assert on rows the route wrote, which needs a session on the *same* SQLite file
the app is using. `conftest.py` currently builds its engine inside `client`, so there is
nothing to share. Lift it into its own fixture — `client` keeps working unchanged:

```python
@pytest.fixture
def db_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True).execution_options(
        schema_translate_map={"app": None}
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def client(db_engine) -> Iterator[TestClient]:
    testing_session = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)

    def override_get_session() -> Iterator[Session]:
        with testing_session() as session:
            yield session

    app = create_app(init_on_startup=False)
    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db_session(db_engine) -> Iterator[Session]:
    """A session on the same SQLite file the app writes to, for asserting on
    persisted rows. expire_on_commit=False so objects stay readable after the
    route's own commit."""
    with sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)() as session:
        yield session
```

Run `poetry run pytest backend/tests -q` after this edit and before writing any new code —
every existing test must still pass. If any does not, the refactor is wrong; fix it before
continuing.

- [x] **Step 4: Run the new tests to verify they fail**

Run: `poetry run pytest backend/tests/test_routes_experiments_train.py -v`
Expected: FAIL — 404 on `/experiments/train` (router not registered).

- [x] **Step 5: Add the schemas**

Widen the import at the top of `backend/app/schemas.py` — it currently imports only
`BaseModel, ConfigDict`:

```python
import datetime as dt

from pydantic import BaseModel, ConfigDict, Field
```

Then append:

```python
# Pydantic v2 reserves the `model_` prefix for its own attributes, so a field
# named `model_type` emits a protected-namespace warning unless the namespace is
# cleared. Every schema below carries a model_type, so every one clears it.
_ML = ConfigDict(protected_namespaces=())


class TrainRequest(BaseModel):
    model_config = _ML

    model_type: str
    dataset_id: str
    target_column: str
    hyperparams: dict[str, Any] = Field(default_factory=dict)
    feature_columns: list[str] | None = None
    # Naming a time column switches the whole run to a chronological split
    # (§3.6). Omitting it on a temporal dataset is how leakage gets in, so the
    # route rejects an unknown name rather than silently falling back.
    time_column: str | None = None
    notes: str = ""


class ExperimentOut(BaseModel):
    model_config = _ML

    experiment_id: str
    mlflow_run_id: str
    status: str
    task_type: str
    metrics: dict[str, float]
```

- [x] **Step 6: Implement the route**

Create `backend/app/routes/experiments.py`:

```python
from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import experiment_log, training
from app.config import settings
from app.dataset_io import load_csv
from app.db import get_session
from app.models import Dataset, Experiment
from app.schemas import ExperimentOut, TrainRequest

router = APIRouter(prefix="/experiments", tags=["experiments"])

ADHOC_EXPERIMENT = "adhoc"


def _load_training_frame(session: Session, dataset_id: str) -> tuple[pd.DataFrame, Dataset]:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    # load_csv is the canonical parser (CLAUDE.md) — training must see exactly
    # the dtypes the profiler saw at upload.
    return load_csv(dataset.data_csv), dataset


def _resolve_features(
    request_features: list[str] | None,
    df: pd.DataFrame,
    target: str,
    time_column: str | None,
) -> list[str]:
    """Explicit features win; otherwise infer them from the DataFrame.

    Inference reads the frame, not `dataset.profile_json` — the profile carries
    no per-column cardinality and empties its categorical summary when it
    degrades (Task 4).
    """
    if request_features:
        return [f for f in request_features if f != time_column]
    try:
        return training.infer_feature_columns(
            df, target, settings.feature_max_cardinality, time_column
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _validate_columns(df: pd.DataFrame, target: str, time_column: str | None) -> None:
    if target not in df.columns:
        raise HTTPException(
            status_code=422, detail=f"target column {target!r} is not in the dataset"
        )
    if time_column is not None and time_column not in df.columns:
        raise HTTPException(
            status_code=422, detail=f"time column {time_column!r} is not in the dataset"
        )


@router.post("/train", response_model=ExperimentOut)
def train_experiment(
    request: TrainRequest, session: Session = Depends(get_session)
) -> ExperimentOut:
    if request.model_type not in training.MODEL_REGISTRY:
        raise HTTPException(
            status_code=422,
            detail=f"unknown model_type; known: {sorted(training.MODEL_REGISTRY)}",
        )
    spec = training.MODEL_REGISTRY[request.model_type]
    df, dataset = _load_training_frame(session, request.dataset_id)
    _validate_columns(df, request.target_column, request.time_column)
    features = _resolve_features(
        request.feature_columns, df, request.target_column, request.time_column
    )

    result = training.fit_and_score(
        request.model_type,
        request.hyperparams,
        df,
        request.target_column,
        features,
        request.time_column,
    )
    run_id = experiment_log.log_run(
        ADHOC_EXPERIMENT,
        request.model_type,
        spec.task_type,
        result.params,
        result,
        dataset.id,
        dataset.content_hash,  # D13/D5: pins the run to the exact bytes it trained on
        request.target_column,
        features,
        request.time_column,
    )
    # §8: a failed fit is history, not an error — the row is written either way.
    experiment = Experiment(
        mlflow_run_id=run_id,
        dataset_id=dataset.id,
        dataset_version=dataset.content_hash,
        model_type=request.model_type,
        task_type=spec.task_type,
        notes=request.notes,
        notes_status="draft",  # D20: unreviewed until a human says otherwise
    )
    session.add(experiment)
    session.commit()
    session.refresh(experiment)
    return ExperimentOut(
        experiment_id=experiment.id,
        mlflow_run_id=run_id,
        status=result.status,
        task_type=spec.task_type,
        metrics=result.metrics,
    )
```

Register it in `backend/app/main.py`:

```python
    from app.routes import chats, datasets, experiments

    app.include_router(datasets.router)
    app.include_router(chats.router)
    app.include_router(experiments.router)
```

- [x] **Step 7: Run the tests to verify they pass**

Run: `poetry run pytest backend/tests/test_routes_experiments_train.py -v`
Expected: PASS, 12 tests.

- [x] **Step 8: Commit**

```bash
make check
git add backend/app/routes/experiments.py backend/app/schemas.py backend/app/main.py \
        backend/app/models.py backend/alembic/versions backend/tests/
git commit -m "feat: POST /experiments/train — Flow A, task-typed and time-aware"
```

---

## Task 7: `app/tuning.py` and `POST /experiments/tune` (Flow B)

**Files:**
- Create: `backend/app/tuning.py`
- Modify: `backend/app/routes/experiments.py`, `backend/app/schemas.py`, `backend/app/config.py`, `pyproject.toml`
- Test: `backend/tests/test_tuning.py`

**Interfaces:**
- Consumes: `training.cv_objective`, `training.MODEL_REGISTRY`, `experiment_log.log_run`,
  `_load_training_frame` and `_resolve_features` from Task 6.
- Produces:
  `run_study(model_type, df, target, features, n_trials, time_column=None, on_trial=None) -> StudyResult`
  where `StudyResult(best_params, best_value, direction, trials: list[TrialRecord])` and
  `TrialRecord(number, params, value, std, status, error)`. `on_trial` is a callback invoked
  once per completed trial so the route can log and persist without `tuning.py` importing
  MLflow or the DB.

**The direction comes from the registry entry, never from a constant.** `MODEL_REGISTRY`
carries `direction` per model (Task 3) precisely so that registering `f1_macro` — a
higher-is-better metric — cannot end up under a minimising study. That failure is silent:
Optuna would dutifully return the *worst* classifier it found, labelled "best", and nothing
in the metrics or the UI would contradict it.

- [x] **Step 1: Add the dependency and settings**

```bash
poetry add "optuna@^4.0"
```

Add to `backend/app/config.py`:

```python
    # Optuna (design §3.8). Bounded so a runaway search space cannot hang the
    # endpoint — studies are synchronous by design.
    optuna_max_trials: int = 50
    optuna_trial_timeout_s: int = 60
    optuna_study_timeout_s: int = 600
```

- [x] **Step 2: Write the failing tests**

Create `backend/tests/test_tuning.py`:

```python
import pandas as pd
import pytest

from app.tuning import run_study


def frame(n: int = 60) -> pd.DataFrame:
    return pd.DataFrame(
        {"memory": [4 * (i % 6) + 4 for i in range(n)], "price": [100.0 + i for i in range(n)]}
    )


def labelled(n: int = 60) -> pd.DataFrame:
    df = frame(n)
    df["direction"] = ["up" if m > 14 else "down" for m in df["memory"]]
    return df


def test_study_runs_the_requested_number_of_trials():
    result = run_study("ridge", frame(), "price", ["memory"], n_trials=3)
    assert len(result.trials) == 3
    assert all(t.status == "FINISHED" for t in result.trials)


def test_a_minimising_study_reports_its_lowest_trial():
    result = run_study("ridge", frame(), "price", ["memory"], n_trials=4)
    assert result.direction == "minimize"
    assert result.best_value == min(t.value for t in result.trials)
    assert "alpha" in result.best_params


def test_a_maximising_study_reports_its_HIGHEST_trial():
    # The whole point of a per-registry-entry direction. Under a hard-coded
    # `direction="minimize"` this passes back the worst classifier found and
    # nothing anywhere says so.
    result = run_study("logistic_regression", labelled(), "direction", ["memory"], n_trials=4)
    assert result.direction == "maximize"
    assert result.best_value == max(t.value for t in result.trials)


def test_every_trial_carries_its_cv_standard_deviation():
    result = run_study("ridge", frame(), "price", ["memory"], n_trials=2)
    assert all(t.std is not None and t.std >= 0 for t in result.trials)


def test_every_trial_is_reported_to_the_callback():
    seen = []
    run_study("ridge", frame(), "price", ["memory"], n_trials=3, on_trial=seen.append)
    assert len(seen) == 3
    assert [t.number for t in seen] == [0, 1, 2]


def test_a_time_column_is_passed_through_to_the_objective():
    captured = {}

    import app.tuning as tuning_mod

    real = tuning_mod.training.cv_objective

    def spy(model_type, params, df, target, features, time_column=None):
        captured["time_column"] = time_column
        return real(model_type, params, df, target, features, time_column)

    tuning_mod.training.cv_objective = spy
    try:
        panel = frame()
        panel["as_of"] = pd.date_range("2015-01-01", periods=len(panel), freq="QE")
        run_study("ridge", panel, "price", ["memory"], n_trials=1, time_column="as_of")
    finally:
        tuning_mod.training.cv_objective = real
    assert captured["time_column"] == "as_of"


def test_a_failing_trial_is_recorded_not_raised(monkeypatch):
    import app.tuning as tuning_mod

    def boom(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(tuning_mod.training, "cv_objective", boom)
    result = run_study("ridge", frame(), "price", ["memory"], n_trials=2)
    assert len(result.trials) == 2
    assert all(t.status == "FAILED" for t in result.trials)
    assert result.best_params == {}


def test_unknown_model_type_raises():
    with pytest.raises(ValueError, match="unknown model_type"):
        run_study("nope", frame(), "price", ["memory"], n_trials=1)
```

- [x] **Step 3: Run the tests to verify they fail**

Run: `poetry run pytest backend/tests/test_tuning.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.tuning'`

- [x] **Step 4: Implement `app/tuning.py`**

```python
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import optuna
import pandas as pd

from app import training
from app.config import settings

logger = logging.getLogger(__name__)

# Optuna's own logging is chatty at INFO and says nothing our trial records don't.
optuna.logging.set_verbosity(optuna.logging.WARNING)


@dataclass(frozen=True)
class TrialRecord:
    number: int
    params: dict[str, Any]
    value: float | None  # the objective's mean across CV folds
    std: float | None  # its standard deviation across those folds
    status: str  # "FINISHED" | "FAILED"
    error: str | None = None


@dataclass
class StudyResult:
    best_params: dict[str, Any]
    best_value: float | None
    direction: str  # copied from the registry entry, for the caller to record
    trials: list[TrialRecord] = field(default_factory=list)


def _spec(model_type: str) -> training.ModelSpec:
    if model_type not in training.MODEL_REGISTRY:
        raise ValueError(f"unknown model_type {model_type!r}")
    return training.MODEL_REGISTRY[model_type]


def _search_space(model_type: str) -> training.SearchSpace:
    return _spec(model_type).search_space


def suggest_params(trial: optuna.Trial, model_type: str) -> dict[str, Any]:
    """Draw one point from the registry's search space, so /train and /tune
    always agree on what a hyperparameter means.

    Lives here, not in training.py: this is the one function that needs an
    optuna.Trial, and keeping it out of training.py is what lets that module
    stay importable and testable without optuna.
    """
    params: dict[str, Any] = {}
    for name, (kind, low, high, log) in _search_space(model_type).items():
        if kind == "int":
            params[name] = trial.suggest_int(name, int(low), int(high), log=log)
        else:
            params[name] = trial.suggest_float(name, low, high, log=log)
    return params


def run_study(
    model_type: str,
    df: pd.DataFrame,
    target: str,
    features: list[str],
    n_trials: int,
    time_column: str | None = None,
    on_trial: Callable[[TrialRecord], None] | None = None,
) -> StudyResult:
    """Run a bounded, in-memory Optuna study.

    No `storage=`: MLflow is the durable record of every trial, so there is no
    third schema. The study object lives only for this call.

    `on_trial` lets the caller persist each trial without this module importing
    MLflow or the DB — that separation is what keeps it unit-testable.

    The direction is the registry entry's, not a constant. `cv_objective`
    already normalises sklearn's `neg_*` sign, so the value optimised here is
    the metric as a human reads it: rmse minimised, f1_macro maximised.
    """
    spec = _spec(model_type)  # fail fast on an unknown model_type
    records: list[TrialRecord] = []

    def objective(trial: optuna.Trial) -> float:
        params = suggest_params(trial, model_type)
        try:
            value, std = training.cv_objective(
                model_type, params, df, target, features, time_column
            )
        except Exception as exc:  # noqa: BLE001 — a bad draw is data, not a crash
            record = TrialRecord(
                trial.number, params, None, None, "FAILED", f"{type(exc).__name__}: {exc}"
            )
            records.append(record)
            if on_trial is not None:
                on_trial(record)
            raise optuna.TrialPruned() from exc
        record = TrialRecord(trial.number, params, float(value), float(std), "FINISHED")
        records.append(record)
        if on_trial is not None:
            on_trial(record)
        return float(value)

    study = optuna.create_study(direction=spec.direction)
    study.optimize(
        objective,
        n_trials=n_trials,
        timeout=settings.optuna_study_timeout_s,
        catch=(Exception,),
    )

    finished = [r for r in records if r.status == "FINISHED" and r.value is not None]
    if not finished:
        return StudyResult({}, None, spec.direction, records)
    pick = max if spec.direction == "maximize" else min
    best = pick(finished, key=lambda r: r.value if r.value is not None else float("nan"))
    return StudyResult(dict(best.params), best.value, spec.direction, records)
```

- [x] **Step 5: Run the tests to verify they pass**

Run: `poetry run pytest backend/tests/test_tuning.py -v`
Expected: PASS, 8 tests.

- [x] **Step 6: Write the failing route test**

Create `backend/tests/test_routes_experiments_tune.py`, reusing the `dataset_id` and
`mlflow_store` fixtures from Task 6's test module (move them into `conftest.py` if sharing
is cleaner than duplicating):

```python
def test_tune_creates_one_experiment_row_per_trial(client, dataset_id, db_session):
    from app.models import Experiment

    resp = client.post(
        "/experiments/tune",
        json={
            "model_type": "ridge",
            "dataset_id": dataset_id,
            "target_column": "price",
            "n_trials": 3,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["n_trials"] == 3
    assert len(body["trials"]) == 3
    assert body["best_experiment_id"]
    assert db_session.query(Experiment).count() == 3


def test_n_trials_above_the_cap_is_422(client, dataset_id):
    resp = client.post(
        "/experiments/tune",
        json={
            "model_type": "ridge",
            "dataset_id": dataset_id,
            "target_column": "price",
            "n_trials": 9999,
        },
    )
    assert resp.status_code == 422
```

- [x] **Step 7: Add the schemas and the route**

Append to `backend/app/schemas.py`:

```python
class TuneRequest(BaseModel):
    model_config = _ML

    model_type: str
    dataset_id: str
    target_column: str
    n_trials: int = 20
    feature_columns: list[str] | None = None
    time_column: str | None = None
    notes: str = ""


class TrialOut(BaseModel):
    number: int
    experiment_id: str
    mlflow_run_id: str
    params: dict[str, Any]
    value: float | None
    std: float | None
    status: str


class TuneOut(BaseModel):
    model_config = _ML

    n_trials: int
    task_type: str
    objective_metric: str
    direction: str
    best_experiment_id: str | None
    best_metrics: dict[str, float]
    trials: list[TrialOut]
```

Append to `backend/app/routes/experiments.py`:

```python
@router.post("/tune", response_model=TuneOut)
def tune_experiment(request: TuneRequest, session: Session = Depends(get_session)) -> TuneOut:
    if request.model_type not in training.MODEL_REGISTRY:
        raise HTTPException(status_code=422, detail="unknown model_type")
    if not 1 <= request.n_trials <= settings.optuna_max_trials:
        raise HTTPException(
            status_code=422,
            detail=f"n_trials must be between 1 and {settings.optuna_max_trials}",
        )
    spec = training.MODEL_REGISTRY[request.model_type]
    df, dataset = _load_training_frame(session, request.dataset_id)
    _validate_columns(df, request.target_column, request.time_column)
    features = _resolve_features(
        request.feature_columns, df, request.target_column, request.time_column
    )

    stamp = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    study_name = f"tune-{request.model_type}-{stamp}"
    trials_out: list[TrialOut] = []

    def persist(record: tuning.TrialRecord) -> None:
        # Refit at the trial's params so the logged run carries holdout metrics,
        # not just the CV score Optuna optimised. Both are recorded, distinctly.
        result = training.fit_and_score(
            request.model_type,
            record.params,
            df,
            request.target_column,
            features,
            request.time_column,
        )
        # `cv_<metric>` is the score Optuna ranked on; `cv_std` is its spread
        # across folds. On a ~180-row train split the spread routinely exceeds
        # the gap between trials, so shipping the mean alone invites a
        # leaderboard that is mostly noise (Global Constraints).
        if record.value is not None:
            result.metrics[f"cv_{spec.objective_metric}"] = record.value
        if record.std is not None:
            result.metrics["cv_std"] = record.std
        run_id = experiment_log.log_run(
            study_name,
            request.model_type,
            spec.task_type,
            record.params,
            result,
            dataset.id,
            dataset.content_hash,
            request.target_column,
            features,
            request.time_column,
        )
        experiment = Experiment(
            mlflow_run_id=run_id,
            dataset_id=dataset.id,
            dataset_version=dataset.content_hash,
            model_type=request.model_type,
            task_type=spec.task_type,
            notes=request.notes,
            notes_status="draft",  # D20, same as Flow A
        )
        session.add(experiment)
        session.flush()
        trials_out.append(
            TrialOut(
                number=record.number,
                experiment_id=experiment.id,
                mlflow_run_id=run_id,
                params=record.params,
                value=record.value,
                std=record.std,
                status=record.status,
            )
        )

    study = tuning.run_study(
        request.model_type,
        df,
        request.target_column,
        features,
        request.n_trials,
        request.time_column,
        persist,
    )
    session.commit()

    # Pick with the study's own direction. `min` here regardless would report
    # the worst classifier as best — the exact bug a per-entry direction exists
    # to prevent.
    scored = [t for t in trials_out if t.value is not None]
    pick = max if study.direction == "maximize" else min
    best = pick(scored, key=lambda t: t.value or 0.0) if scored else None

    best_metrics: dict[str, float] = {}
    if study.best_value is not None:
        best_metrics[f"cv_{spec.objective_metric}"] = study.best_value
    if best is not None and best.std is not None:
        best_metrics["cv_std"] = best.std

    return TuneOut(
        n_trials=len(trials_out),
        task_type=spec.task_type,
        objective_metric=spec.objective_metric,
        direction=study.direction,
        best_experiment_id=best.experiment_id if best else None,
        best_metrics=best_metrics,
        trials=trials_out,
    )
```

Update the import block at the top of `backend/app/routes/experiments.py` to exactly this —
the `tuning` import and `dt` are new in this task:

```python
from __future__ import annotations

import datetime as dt

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import experiment_log, training, tuning
from app.config import settings
from app.dataset_io import load_csv
from app.db import get_session
from app.models import Dataset, Experiment
from app.schemas import ExperimentOut, TrainRequest, TrialOut, TuneOut, TuneRequest
```

- [x] **Step 8: Run the tests to verify they pass**

Run: `poetry run pytest backend/tests/test_routes_experiments_tune.py backend/tests/test_tuning.py -v`
Expected: PASS.

- [x] **Step 9: Commit**

```bash
make check
git add backend/app/tuning.py backend/app/routes/experiments.py backend/app/schemas.py backend/app/config.py backend/tests/ pyproject.toml poetry.lock
git commit -m "feat: Optuna tuning and POST /experiments/tune — Flow B"
```

---

## Task 8: The read and review API — `GET /experiments`, `GET /experiments/{id}`, `PATCH /experiments/{id}`

Three routes on one surface, so they land together: the reader has to expose `notes_status`
for the reviewer to act on, and the reviewer is the only thing that can move a note off
`draft` (D20). All three live in `routes/experiments.py` and share one test module.

**Files:**
- Modify: `backend/app/routes/experiments.py`, `backend/app/schemas.py`
- Test: `backend/tests/test_routes_experiments_list.py`

**Interfaces:**
- Consumes: `experiment_log.fetch_runs`, `experiment_log.search_runs`, `models.Experiment`
  (including the `task_type` and `notes_status` columns added in Task 6).
- Produces: `ExperimentDetailOut` and `ExperimentPatchRequest` — the merged read shape and the
  review payload the frontend consumes in Task 9 and the seeding script in Task 10.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_routes_experiments_list.py`. Reuse the `client`, `dataset_id`, and
`mlflow_store` fixtures from Task 6's test module — move them into `backend/tests/conftest.py`
if they are still local to it, rather than copying them a third time.

```python
def _train(client, dataset_id, model_type="ridge", target="price", **extra):
    return client.post(
        "/experiments/train",
        json={
            "model_type": model_type,
            "dataset_id": dataset_id,
            "target_column": target,
            **extra,
        },
    ).json()


def test_list_merges_mlflow_params_and_metrics(client, dataset_id):
    _train(client, dataset_id)
    body = client.get("/experiments").json()
    assert len(body) == 1
    assert body[0]["params"]["model_type"] == "ridge"
    assert "rmse" in body[0]["metrics"]
    assert body[0]["mlflow_available"] is True


def test_list_reports_the_task_type_and_the_review_status(client, dataset_id):
    _train(client, dataset_id, notes="baseline")
    row = client.get("/experiments").json()[0]
    assert row["task_type"] == "regression"
    assert row["notes_status"] == "draft"


def test_list_filters_by_model_type(client, dataset_id):
    for m in ("ridge", "random_forest"):
        _train(client, dataset_id, model_type=m)
    assert len(client.get("/experiments?model_type=ridge").json()) == 1


def test_list_filters_by_task_type(client, dataset_id):
    # A regression rmse and a classification f1_macro do not belong in one
    # leaderboard, so the page must be able to ask for one task type at a time.
    _train(client, dataset_id)
    _train(client, dataset_id, model_type="logistic_regression", target="chipset")
    rows = client.get("/experiments?task_type=classification").json()
    assert [r["model_type"] for r in rows] == ["logistic_regression"]


def test_list_filters_by_notes_status(client, dataset_id):
    a = _train(client, dataset_id)
    _train(client, dataset_id, model_type="random_forest")
    client.patch(f"/experiments/{a['experiment_id']}", json={"notes_status": "approved"})
    assert len(client.get("/experiments?notes_status=draft").json()) == 1
    assert len(client.get("/experiments?notes_status=approved").json()) == 1


def test_list_degrades_when_mlflow_is_unreachable(client, dataset_id, monkeypatch):
    _train(client, dataset_id)

    def boom(*a, **k):
        raise RuntimeError("store down")

    monkeypatch.setattr("app.routes.experiments.experiment_log.fetch_runs", boom)
    body = client.get("/experiments").json()
    assert body[0]["mlflow_available"] is False
    assert body[0]["metrics"] == {}
    assert body[0]["model_type"] == "ridge"      # our own columns still resolve
    assert body[0]["notes_status"] == "draft"


def test_status_filter_is_503_when_mlflow_is_unreachable(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("store down")

    monkeypatch.setattr("app.routes.experiments.experiment_log.search_runs", boom)
    assert client.get("/experiments?status=FINISHED").status_code == 503


def test_detail_404s_on_unknown_id(client):
    assert client.get("/experiments/nope").status_code == 404


def test_patch_updates_the_notes(client, dataset_id):
    created = _train(client, dataset_id)
    resp = client.patch(
        f"/experiments/{created['experiment_id']}", json={"notes": "observed X"}
    )
    assert resp.status_code == 200
    assert resp.json()["notes"] == "observed X"
    assert client.get(f"/experiments/{created['experiment_id']}").json()["notes"] == "observed X"


def test_editing_the_notes_alone_does_not_approve_them(client, dataset_id):
    # The seeding script in Task 10 writes through this route. If a write were an
    # implicit approval, every generated note would arrive pre-blessed and D20
    # would mean nothing.
    created = _train(client, dataset_id)
    body = client.patch(
        f"/experiments/{created['experiment_id']}", json={"notes": "generated"}
    ).json()
    assert body["notes_status"] == "draft"


def test_approving_a_note_is_an_explicit_transition(client, dataset_id):
    created = _train(client, dataset_id, notes="a real observation")
    body = client.patch(
        f"/experiments/{created['experiment_id']}", json={"notes_status": "approved"}
    ).json()
    assert body["notes_status"] == "approved"


def test_a_worthless_note_can_be_rejected_without_being_rewritten(client, dataset_id):
    # D20's third state. Rejection needs no text — the whole point is that there
    # was nothing worth keeping — so the empty-note guard must not apply here.
    created = _train(client, dataset_id)
    body = client.patch(
        f"/experiments/{created['experiment_id']}", json={"notes_status": "rejected"}
    ).json()
    assert body["notes_status"] == "rejected"


def test_an_empty_note_cannot_be_approved(client, dataset_id):
    # "Approved" has to mean a human read something. Approving an empty note is
    # the one way to get an approved-but-meaningless row into Phase 3's index.
    created = _train(client, dataset_id)
    resp = client.patch(
        f"/experiments/{created['experiment_id']}", json={"notes_status": "approved"}
    )
    assert resp.status_code == 422


def test_an_unknown_notes_status_is_rejected(client, dataset_id):
    created = _train(client, dataset_id)
    resp = client.patch(
        f"/experiments/{created['experiment_id']}", json={"notes_status": "blessed"}
    )
    assert resp.status_code == 422


def test_patch_404s_on_unknown_id(client):
    assert client.patch("/experiments/nope", json={"notes": "x"}).status_code == 404
```

- [x] **Step 2: Run to verify they fail**

Run: `poetry run pytest backend/tests/test_routes_experiments_list.py -v`
Expected: FAIL — 405/404, the GET and PATCH routes do not exist.

- [x] **Step 3: Implement**

Add to `backend/app/schemas.py`:

```python
class ExperimentDetailOut(BaseModel):
    model_config = _ML

    id: str
    mlflow_run_id: str
    dataset_id: str | None
    dataset_version: str | None
    model_type: str
    task_type: str
    notes: str
    notes_status: str
    created_at: dt.datetime
    status: str | None
    params: dict[str, str]
    metrics: dict[str, float]
    mlflow_available: bool


class ExperimentPatchRequest(BaseModel):
    """Both fields optional: an edit, an approval, or both in one call.

    `None` means "leave it alone" — distinct from `notes=""`, which clears the
    note. A bare `{}` is accepted and changes nothing.
    """

    notes: str | None = None
    notes_status: Literal["draft", "approved", "rejected"] | None = None
```

`Literal` gives the 422 on an unknown status for free, in FastAPI's own validation-error
shape — no hand-rolled check, and the allowed set appears in the OpenAPI schema. Add `Literal`
to the `typing` import at the top of `schemas.py`.

Add to the import block in `backend/app/routes/experiments.py` — `logging` and `select` are
new in this task, and `_merge` uses both:

```python
import logging

from sqlalchemy import select

from app.schemas import ExperimentDetailOut, ExperimentPatchRequest  # extend the existing import

logger = logging.getLogger(__name__)          # module level, below the router
```

Then add the routes:

```python
@router.get("", response_model=list[ExperimentDetailOut])
def list_experiments(
    model_type: str | None = None,
    task_type: str | None = None,
    dataset_id: str | None = None,
    notes_status: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
) -> list[ExperimentDetailOut]:
    query = select(Experiment).order_by(Experiment.created_at.desc())
    if model_type:
        query = query.where(Experiment.model_type == model_type)
    if task_type:
        query = query.where(Experiment.task_type == task_type)
    if dataset_id:
        query = query.where(Experiment.dataset_id == dataset_id)
    if notes_status:
        query = query.where(Experiment.notes_status == notes_status)
    if status:
        # `status` has no column of ours — it lives in MLflow. Resolve it to a
        # run-id set first (D15's structured stage), then intersect. This is the
        # one filter that cannot be answered without the tracking store.
        try:
            run_ids = experiment_log.search_runs(None, None, [status])
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=503, detail="MLflow tracking store unavailable"
            ) from exc
        if not run_ids:
            return []
        query = query.where(Experiment.mlflow_run_id.in_(run_ids))
    rows = list(session.execute(query.limit(limit).offset(offset)).scalars())
    return _merge(rows)


@router.get("/{experiment_id}", response_model=ExperimentDetailOut)
def get_experiment(
    experiment_id: str, session: Session = Depends(get_session)
) -> ExperimentDetailOut:
    row = session.get(Experiment, experiment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return _merge([row])[0]


@router.patch("/{experiment_id}", response_model=ExperimentDetailOut)
def update_experiment(
    experiment_id: str,
    request: ExperimentPatchRequest,
    session: Session = Depends(get_session),
) -> ExperimentDetailOut:
    """Edit a note, move its review status, or both (D20).

    Writing a note is NOT approving it: the seeding script in Task 10 goes
    through this route, and an implicit approval on write would mean every
    generated note arrives pre-blessed. `notes_status` only moves when the
    caller names it.
    """
    row = session.get(Experiment, experiment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    if request.notes is not None:
        row.notes = request.notes
    if request.notes_status is not None:
        if request.notes_status == "approved" and not row.notes.strip():
            raise HTTPException(
                status_code=422, detail="an empty note cannot be approved"
            )
        row.notes_status = request.notes_status
    session.commit()
    session.refresh(row)
    return _merge([row])[0]


def _merge(rows: list[Experiment]) -> list[ExperimentDetailOut]:
    """Join our columns to MLflow's params/metrics in ONE fetch.

    A GET must not 500 because the tracking store is down: the structured
    fields are ours and always available, so degrade rather than fail.
    """
    runs: dict[str, experiment_log.RunData] = {}
    available = True
    try:
        runs = experiment_log.fetch_runs([r.mlflow_run_id for r in rows])
    except Exception:  # noqa: BLE001
        logger.warning("MLflow tracking store unavailable; returning structured fields only")
        available = False
    out = []
    for row in rows:
        run = runs.get(row.mlflow_run_id)
        out.append(
            ExperimentDetailOut(
                id=row.id,
                mlflow_run_id=row.mlflow_run_id,
                dataset_id=row.dataset_id,
                dataset_version=row.dataset_version,
                model_type=row.model_type,
                task_type=row.task_type,
                notes=row.notes,
                notes_status=row.notes_status,
                created_at=row.created_at,
                status=run.status if run else None,
                params=run.params if run else {},
                metrics=run.metrics if run else {},
                mlflow_available=available,
            )
        )
    return out
```

- [x] **Step 4: Run to verify they pass**

Run: `poetry run pytest backend/tests/test_routes_experiments_list.py -v`
Expected: PASS, 14 tests.

- [x] **Step 5: Commit**

```bash
make check
git add backend/app/routes/experiments.py backend/app/schemas.py backend/tests/
git commit -m "feat: experiment read and review API — listing, detail, note approval"
```

---

## Task 9: `ExperimentsPage` — leaderboard, comparison, and note review

D9's public equivalent of the MLflow UI, plus the human half of D20: the place where a person
reads a generated note and either fixes it or approves it. Reuses the existing `ui/` primitives
and tokens. Because Vitest runs with `css: false`, **assert on roles, accessible names, `data-*`
attributes, and visible text — never CSS-module class names.**

**Files:**
- Create: `frontend/src/pages/ExperimentsPage.tsx`, `frontend/src/pages/ExperimentsPage.test.tsx`
- Modify: `frontend/src/api.ts`, `frontend/src/App.tsx`, `frontend/src/components/AppShell.tsx`

**Interfaces:**
- Consumes: `GET /experiments`, `GET /experiments/{id}`, `PATCH /experiments/{id}` from Task 8.
- Produces: route `/experiments`.

- [x] **Step 1: Write the failing test**

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import ExperimentsPage from "./ExperimentsPage";

const rows = [
  { id: "e1", mlflow_run_id: "r1", dataset_id: "d1", dataset_version: "h1",
    model_type: "ridge", task_type: "regression", notes: "baseline",
    notes_status: "draft", created_at: "2026-08-10T00:00:00Z",
    status: "FINISHED", params: { alpha: "0.5" }, metrics: { rmse: 12.5 },
    mlflow_available: true },
  { id: "e2", mlflow_run_id: "r2", dataset_id: "d1", dataset_version: "h1",
    model_type: "random_forest", task_type: "regression", notes: "deeper",
    notes_status: "approved", created_at: "2026-08-10T01:00:00Z",
    status: "FINISHED", params: { n_estimators: "200" }, metrics: { rmse: 9.1 },
    mlflow_available: true },
];

/** Records every request so the tests can assert on URLs and method/body. */
function mockFetch(payload: unknown = rows) {
  const calls: [string, RequestInit | undefined][] = [];
  global.fetch = vi.fn((url: string, init?: RequestInit) => {
    calls.push([String(url), init]);
    const body = init?.method === "PATCH" ? { ...rows[0], ...JSON.parse(String(init.body)) } : payload;
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
  }) as unknown as typeof fetch;
  return calls;
}

beforeEach(() => {
  mockFetch();
});

describe("ExperimentsPage", () => {
  it("lists every experiment with its model type and rmse", async () => {
    render(<ExperimentsPage />);
    expect(await screen.findByText("ridge")).toBeInTheDocument();
    expect(screen.getByText("random_forest")).toBeInTheDocument();
    expect(screen.getByText(/9\.1/)).toBeInTheDocument();
  });

  it("filters by task type so one leaderboard holds one metric", async () => {
    const calls = mockFetch();
    render(<ExperimentsPage />);
    await screen.findByText("ridge");
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: /task type/i }),
      "classification",
    );
    expect(calls.at(-1)?.[0]).toContain("task_type=classification");
  });

  it("marks which notes are still unreviewed drafts", async () => {
    render(<ExperimentsPage />);
    const draft = await screen.findByTestId("notes-status-e1");
    expect(draft).toHaveTextContent(/draft/i);
    expect(screen.getByTestId("notes-status-e2")).toHaveTextContent(/approved/i);
  });

  it("approves a draft note through PATCH and shows the new status", async () => {
    const calls = mockFetch();
    render(<ExperimentsPage />);
    await screen.findByText("ridge");
    await userEvent.click(screen.getByRole("button", { name: /review notes for e1/i }));
    await userEvent.click(screen.getByRole("button", { name: /^approve$/i }));

    const [url, init] = calls.at(-1)!;
    expect(url).toContain("/experiments/e1");
    expect(init?.method).toBe("PATCH");
    expect(JSON.parse(String(init?.body))).toMatchObject({ notes_status: "approved" });
    expect(await screen.findByTestId("notes-status-e1")).toHaveTextContent(/approved/i);
  });

  it("saves an edited note without approving it", async () => {
    const calls = mockFetch();
    render(<ExperimentsPage />);
    await screen.findByText("ridge");
    await userEvent.click(screen.getByRole("button", { name: /review notes for e1/i }));
    const box = screen.getByRole("textbox", { name: /notes/i });
    await userEvent.clear(box);
    await userEvent.type(box, "rewritten by hand");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    const body = JSON.parse(String(calls.at(-1)![1]?.body));
    expect(body).toMatchObject({ notes: "rewritten by hand" });
    expect(body.notes_status).toBeUndefined();   // saving is not approving
  });

  it("compares the runs the user selects", async () => {
    render(<ExperimentsPage />);
    await screen.findByText("ridge");
    const boxes = screen.getAllByRole("checkbox");
    await userEvent.click(boxes[0]);
    await userEvent.click(boxes[1]);
    const table = await screen.findByRole("table", { name: /compare/i });
    expect(table).toBeInTheDocument();
  });

  it("warns when the tracking store is unavailable", async () => {
    mockFetch([{ ...rows[0], mlflow_available: false, metrics: {} }]);
    render(<ExperimentsPage />);
    expect(await screen.findByText(/unavailable/i)).toBeInTheDocument();
  });
});
```

- [x] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/pages/ExperimentsPage.test.tsx`
Expected: FAIL — cannot resolve `./ExperimentsPage`.

- [x] **Step 3: Add the API wrappers**

Append to `frontend/src/api.ts`, matching the existing wrappers' shape:

```ts
export interface ExperimentRow {
  id: string;
  mlflow_run_id: string;
  dataset_id: string | null;
  dataset_version: string | null;
  model_type: string;
  task_type: string;
  notes: string;
  notes_status: string;
  created_at: string;
  status: string | null;
  params: Record<string, string>;
  metrics: Record<string, number>;
  mlflow_available: boolean;
}

export async function listExperiments(params: {
  modelType?: string;
  taskType?: string;
  datasetId?: string;
  notesStatus?: string;
} = {}): Promise<ExperimentRow[]> {
  const q = new URLSearchParams();
  if (params.modelType) q.set("model_type", params.modelType);
  if (params.taskType) q.set("task_type", params.taskType);
  if (params.datasetId) q.set("dataset_id", params.datasetId);
  if (params.notesStatus) q.set("notes_status", params.notesStatus);
  const qs = q.toString();
  return request<ExperimentRow[]>(`/experiments${qs ? `?${qs}` : ""}`);
}

export async function getExperiment(id: string): Promise<ExperimentRow> {
  return request<ExperimentRow>(`/experiments/${id}`);
}

/** Edit and/or approve a note. Omit a field to leave it untouched — saving
 *  text is deliberately NOT an approval (D20). */
export async function updateExperiment(
  id: string,
  patch: { notes?: string; notes_status?: "draft" | "approved" | "rejected" },
): Promise<ExperimentRow> {
  return request<ExperimentRow>(`/experiments/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}
```

**Adapt `request` to whatever the existing helper in `api.ts` is actually called** — read the
file first; do not introduce a second fetch helper.

- [x] **Step 4: Implement the page**

Build with the existing `ui/` primitives (`Card`, `Badge`, `Button`, `Textarea`, `Dialog`,
`Skeleton`). Required behaviour, in the order the tests assert it:

1. Fetch on mount; render a `Skeleton` while loading and an `ErrorBanner` on failure.
2. One row per experiment: model type, task type, status `Badge`, `created_at`, every metric,
   and the notes (truncated).
3. Two filter `<select>`s, each with an accessible name (`aria-label="Model type"` and
   `aria-label="Task type"`), refetching through `listExperiments`. The task-type select
   offers exactly `All` (value `""`), `regression`, and `classification`. Mixing an `rmse` row
   and an `f1_macro` row in one ranking compares nothing, which is why this filter is a
   requirement and not a nicety.
4. A `notes_status` `Badge` per row carrying `data-testid={`notes-status-${row.id}`}` and the
   text `draft` or `approved`.
5. A **Review notes** button per row, with accessible name `Review notes for {id}` (use
   `aria-label`), opening a `Dialog` containing: the run's params and metrics for context, a
   `Textarea` labelled *Notes*, and three buttons — **Save**
   (`updateExperiment(id, { notes })`), **Approve**
   (`updateExperiment(id, { notes_status: "approved" })`), and **Reject**
   (`updateExperiment(id, { notes_status: "rejected" })`), D20's three states. Approve is
   disabled when the textarea is empty — the backend 422s on that, and the button should not
   offer an action that cannot succeed; Reject is not, since having nothing worth keeping is
   the reason to reject. Merge the returned row back into local state so the badge updates
   without a refetch.
6. A checkbox per row; selecting two or more renders a `<table>` with an accessible name
   containing "compare", one column per selected run, one row per metric and param. Refuse to
   compare across task types — if the selection spans both, show "cannot compare a regression
   run with a classification run" instead of the table.
7. When any row has `mlflow_available === false`, render a banner containing the word
   "unavailable" and omit the metric columns.

Register the route in `App.tsx` alongside `/` and `/c/:chatId`, and add a nav entry in
`AppShell` so the page is reachable.

- [x] **Step 5: Run the frontend gate**

```bash
cd frontend && npm run type-check && npm test && npm run build
```
Expected: PASS, including the 7 new tests.

- [x] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "feat: ExperimentsPage — list, filter, compare, and review run notes"
```

---

## Task 10: Seed real experiment history as drafts (deliverable 2.10 + D20)

**The phase gate.** Phase 3 has nothing to embed and Phase 4 nothing to evaluate without
this. Per D17 this is a script, not an endpoint — it is the only Phase 2 code that calls
Claude, which is why the endpoints stay keyless.

Everything it writes is a **draft** (D20). The script never approves its own output; the last
step of this task is a human sitting in front of `ExperimentsPage` doing that, which is the
point of having built the review panel.

**Files:**
- Create: `scripts/seed_experiment_history.py`
- Modify: `Makefile` (add `seed-history`), `.env.example`

**Interfaces:**
- Consumes: `POST /experiments/tune`, `GET /experiments`, `PATCH /experiments/{id}` (Task 8),
  the Anthropic SDK.
- Produces: ≥20 `experiments` rows with observation-grade draft `notes` — Phase 3's only input.

- [x] **Step 1: Write the script**

Two passes, because they fail differently. Pass 1 runs studies through the API and needs no
key. Pass 2 writes notes and needs `ANTHROPIC_API_KEY`.

```python
"""Seed real experiment history (Project 2 deliverable 2.10).

Pass 1 runs Optuna studies via the API. Pass 2 writes each run a note that says
something the structured fields do not already say — if notes only restate
params, semantic search over them is circular and Phase 4's retrieval evals
measure nothing (design §3.11).

Every note is written as a DRAFT (D20). This script has no way to approve one:
`PATCH` is called with `{"notes": ...}` only, never with `notes_status`. A human
approves in ExperimentsPage, and Phase 3 embeds what they approved.

Resumable: pass 2 skips any experiment whose notes are already non-empty, so a
mid-run API failure costs only the remaining trials.
"""
```

Required behaviour:
1. Resolve the dataset ids from `GET /datasets` by name — `revenue-nowcast.csv` (the
   candidate-#4 panel from Task 1) and `pc-part-video-card.csv`; exit with a clear message
   naming `make prepare-data && make data-fetch` if either is missing.
2. Pass 1, in two studies, so the history is not all one shape:
   - `ridge`, `random_forest`, `gradient_boosting` × `n_trials=8` against `revenue_next_usd`
     on the revenue-nowcast panel, **with `time_column="as_of"`** — the phase's real modelling
     task, split chronologically.
   - `ridge` × `n_trials=8` against `price` on the video-card dataset, no `time_column` — a
     cross-sectional contrast so retrieval in Phase 3 has more than one kind of run to
     discriminate between.

   32 runs, over the ≥20 floor and under `optuna_max_trials`.
3. Pass 2: `GET /experiments`, skip rows with non-empty notes, and for each remaining row
   make one Claude call with that run's params, metrics (including `cv_std`), and its delta
   against the best objective value seen **within its own task type** — a regression `rmse`
   and a classification `f1_macro` are not comparable. Prompt for two to four sentences of
   observation — what the configuration did, how it compares, and one hypothesis — and
   explicitly instruct it **not to restate the hyperparameter values**.
4. Write the note back with `PATCH /experiments/{id}` carrying `{"notes": ...}` and nothing
   else. Do not write to the database directly from `scripts/` — that would bypass every
   validation the route owns — and do not send `notes_status`.
5. Print a summary: rows seeded, notes written, notes skipped, and a reminder that all of them
   are drafts awaiting review.

Use `settings.anthropic_model` and the existing Anthropic client construction from
`app/llm.py`; do not hand-roll a second client.

- [x] **Step 2: Run the seeding end to end**

```bash
make db-up
make mlflow-init
DATABASE_URL="postgresql+psycopg2://wavepoint:wavepoint@localhost:5433/wavepoint" make dev &
sleep 5
make prepare-data
make data-fetch
poetry run python scripts/seed_experiment_history.py
```

Expected: ≥20 experiments, every one with non-empty notes, every one still `draft`.

- [x] **Step 3: Verify the history is real, not just present**

```bash
curl -sS localhost:8000/experiments?limit=100 | python3 -c "
import json,sys
rows = json.load(sys.stdin)
print('rows', len(rows))
print('with notes', sum(1 for r in rows if r['notes'].strip()))
print('distinct notes', len({r['notes'] for r in rows}))
print('drafts', sum(1 for r in rows if r['notes_status'] == 'draft'))
print('with cv_std', sum(1 for r in rows if 'cv_std' in r['metrics']))
print('chronological', sum(1 for r in rows if r['params'].get('split') == 'chronological'))
"
```

Expected: `rows` ≥ 20, `with notes` == `rows`, `drafts` == `rows`, and **`distinct notes` ==
`rows`** — identical notes mean the generator collapsed and the retrieval evals would be
meaningless. `chronological` should be 24 (the panel studies) and the rest random. Read three
notes by eye and confirm each says something the params do not.

- [ ] **Step 4: Review the drafts — the human half of D20**

This is a manual step and it is not optional: Phase 3 embeds approved notes, so a history of
32 unreviewed drafts is a history Phase 3 cannot use.

1. `cd frontend && npm run dev`, open `/experiments`.
2. Open **Review notes** on each row, read the note against the run's params and metrics, and
   **Save** a correction, **Approve** it, or **Reject** it.
3. Approve at least 20. Expect to reject or rewrite some — a note that only restates
   `alpha=0.31` is exactly what the prompt was told not to produce, and catching those by hand
   is why the panel exists.
4. Confirm with:

```bash
curl -sS "localhost:8000/experiments?notes_status=approved&limit=100" \
  | python3 -c "import json,sys; print('approved', len(json.load(sys.stdin)))"
```

Expected: ≥20.

- [x] **Step 5: Commit**

```bash
make check
git add scripts/seed_experiment_history.py Makefile .env.example
git commit -m "feat: seed 32 real experiments with observation-grade draft notes (2.10)"
```

---

## Task 11: Documentation sync and phase close-out

Required by CLAUDE.md's document-sync rule before the phase's final merge.

**Files:**
- Modify: `CLAUDE.md`, `README.md`, `data-sources/README.md`,
  `doc/project-2-ml-experiment-tracker-design.md`,
  `doc/plans/2026-08-05-project-2-overall-implementation-plan.md`, this plan

- [x] **Step 1: Update `CLAUDE.md`**

Add to the commands block: `make prepare-data` and `make seed-history`. Add to the code
layout: `scripts/prepare_dataset.py`, `app/training.py`, `app/experiment_log.py`,
`app/tuning.py`, `app/routes/experiments.py`, `scripts/seed_experiment_history.py`,
`frontend/src/pages/ExperimentsPage.tsx`.

Replace the "Two source-data paths currently coexist" entry — Task 2 resolved it — and add
three "Non-obvious design decisions" entries:

```markdown
**Training is split across three modules on purpose (Project 2 §3.1).**
`app/training.py` is pure sklearn — no MLflow, no DB, no network — so it is
testable against a 40-row synthetic frame. `app/experiment_log.py` is the
**only** module that imports `mlflow`; Phase 3's agent reuses its `search_runs`
rather than reaching for the SDK. `app/tuning.py` takes an `on_trial` callback
so Optuna never imports either. Do not collapse these back together.

`ModelSpec` carries `task_type`, `objective_metric`, `direction`, and
`cv_scoring` **per registry entry**. The direction is not a module-level
constant: a study over `f1_macro` that minimises silently selects the worst
model, and the failure is invisible because every metric still looks plausible.

Two MLflow facts that cost time to rediscover: a `file://` tracking store is
**rejected** by MLflow 3.x, so tests use `sqlite:///{tmp_path}/mlflow.db`; and
`search_runs(filter_string="attributes.run_id IN (...)")` works, which is why
`fetch_runs` is one call and not an N+1.

Endpoints never call Claude or Voyage (D17). Note enrichment lives in
`scripts/seed_experiment_history.py`, so training needs no API key and no route
test needs an LLM mock.

**Temporal data is split chronologically, never shuffled (design §3.6, D18).**
`POST /experiments/train` and `/tune` take an optional `time_column`. When it is
present the holdout is the tail of the sorted frame and cross-validation is
`TimeSeriesSplit`; when it is absent the split is random. The column itself is
dropped from the features — it is the split axis, not a predictor. A typo'd
`time_column` is a **422**, not a silent fallback to a random split, because the
leaky version returns 200 with flattering metrics and nothing downstream would
notice. Every metric is reported with its cross-validation standard deviation:
the revenue panel is ~224 rows and a difference smaller than the fold spread is
noise.

**Generated notes are drafts until a human approves them (D20).**
`experiments.notes_status` is `draft` at creation from both flows, and only
`PATCH /experiments/{id}` with an explicit `notes_status` moves it to `approved`
or `rejected`. Writing note text through the same route is deliberately **not**
an approval — the seeding script writes `{"notes": ...}` and nothing else, so its
output cannot approve itself. An empty note cannot be approved (422), though it
can be rejected. Phase 3 embeds approved notes.
```

- [x] **Step 2: Update `README.md`**

- Quickstart: `make db-up` → `mlflow-init` → **`prepare-data`** → `data-fetch` →
  `seed-history`.
- The `/experiments` page in the feature list, including the note-review panel.
- **Correct candidate #4.** It currently names Micron as one of the tickers. Micron has a
  stock file but no `sec-edgar-revenue` file, so it cannot appear in a revenue panel; the
  five usable tickers are AMD, DELL, HPQ, INTC, NVDA. Replace Micron with INTC and state the
  five explicitly.

- [x] **Step 3: Update `data-sources/README.md`**

Record the amendment to D12 found in Task 1: `sec-edgar-revenue/` covers **six** tickers
(AAPL, AMD, DELL, HPQ, INTC, NVDA), not the three the design assumed, and AAPL is unusable
here for lack of a matching `company-stocks/` file. Note the two traps the same task
uncovered, next to the sources they belong to:

- `value_usd` is **cumulative year-to-date**, not quarterly — the discrete quarter is
  `cum(n months) − cum(n−3 months)` over the same `period_start`.
- The FRED PPI series marks gaps with a non-numeric token, so it must be read through
  `pd.to_numeric(errors="coerce")`; a bare `pct_change()` forward-fills across those gaps and
  hides them.
- Point-in-time dedup keys on `(ticker, period_start, period_end)` and keeps the **first**
  filing. The same window is labelled `Q3` in a 10-Q and `FY` in the later 10-K, so
  `fiscal_period` is not a key; keeping the last filing pulls in a restatement published up
  to a year later and scrambles the time axis.

- [x] **Step 4: Update the design doc's API surface**

`doc/project-2-ml-experiment-tracker-design.md` §3.7 lists four endpoints. Add
`PATCH /experiments/{id}` (notes and `notes_status`) — see "Amends the design" below.

- [x] **Step 5: Tick every checkbox in this plan and add the Phase 2a amendment**

Append to §9 of `doc/plans/2026-08-05-project-2-overall-implementation-plan.md`, recording
what actually happened including anything that diverged from this plan. Note explicitly that
Phase 2 was split, and that Phase 2b (EDA, diagnostics, the note-chunk source-type migration)
is a separate plan.

- [ ] **Step 6: Verify every Phase 2a exit criterion independently**

Do not trust the per-task "Expected" lines — re-verify:

| Criterion | How |
|---|---|
| `data-sources/prepared/revenue_nowcast.csv` rebuilds byte-identically | `make prepare-data` twice, `git diff` clean |
| A ≥20-trial study is visible in `ExperimentsPage` | Load `/experiments` in the browser |
| The same runs are in the MLflow store | `make mlflow-ui`, confirm the `tune-*` experiments |
| Every trial has params, metrics with `cv_std`, and notes | The Step 3 check in Task 10 |
| ≥20 notes are approved by a human | The Step 4 check in Task 10 |
| The panel runs are chronologically split | `params.split == "chronological"`, same check |
| CI green | Push and confirm both jobs pass |
| `make check` clean | Run it |

**Verified 2026-08-14 — seven of eight pass; this step stays unticked on the last one.**

- Rebuild is byte-identical (`make prepare-data` twice, `git diff` clean).
- `/experiments` loads in the browser and renders all 32 rows, each showing `draft`.
  The one console error is a missing `favicon.ico`; the two warnings are React
  Router v7 future-flag notices. All three predate Phase 2a.
- The MLflow store holds 32 runs across four `tune-*` experiments, and the
  `mlflow_run_id` join is exactly 1:1 — no app row without a run, no run without
  a row. Counts matching would not have proven this; the set difference does.
- All 32 rows carry params, metrics including `cv_std`, and a distinct note.
- 24 panel runs are `split == "chronological"`, the 8 component runs random.
- `make check`: 216 passed. Frontend: `tsc` clean, 84 tests across 19 files.
- **Not verified: "≥20 notes approved by a human."** 32 drafts, 0 approved. This
  is Task 10 Step 4 and it is not mine to do — a note approved by the same
  process that wrote it is precisely what D20 exists to prevent. Phase 3 embeds
  approved notes only, so **this is a real blocker on Phase 3**, not a formality.

- [x] **Step 7: Commit**

```bash
git add CLAUDE.md README.md data-sources/README.md doc/
git commit -m "docs: sync for Phase 2a and close the phase"
```

---

## Deferred to Phase 2b

Phase 2 was split after the review. **Phase 2b gets its own plan**, written once 2a lands, and
covers:

- **EDA over the prepared panel** — distributions, per-ticker coverage, the correlation
  structure between the market features and the target, and an honest look at how much signal
  ~224 rows can carry.
- **Model diagnostics** — residuals against `quarter_end`, per-ticker error, learning curves,
  and a naive persistence baseline (`revenue_next = revenue`) that any model must beat before
  it is worth reporting.
- **The `experiment_note_chunks` source-type migration** — the column that lets Phase 3
  distinguish a note chunk from other chunk sources.
- **Richer note review** — bulk approval, and a diff between the generated draft and the human
  edit. Phase 2a ships D20's three states and a one-row-at-a-time panel; reviewing 32 rows by
  hand is tolerable, reviewing Phase 2b's EDA and diagnostic drafts on top of them is not.

## Deferred beyond Phase 2 entirely

Recorded so they are not silently lost:

- **The `backend-postgres` CI job (D16).** Deferred to Phase 3, not dropped. Phase 2a produces
  no Postgres-only test — training runs on SQLite and the MLflow store is
  `sqlite:///{tmp_path}/mlflow.db` — so the job would start out green over an empty
  selection, which is worse than no job. It lands with the first `@pytest.mark.postgres`
  test, which is Phase 3's `<=>` similarity search.
- **Branch protection on `main`** — carried from Phase 1 Task 1, still unset.
- **pgvector on Render's free tier** — unverified; check before Phase 4, not during.

## Amends the design

Four amendments, all to be written into the design doc and `data-sources/README.md` by Task 11:

1. **`PATCH /experiments/{id}`** (notes and `notes_status`) is not in the §3.7 API surface. It
   is a direct consequence of D17 plus D20: once note-writing moved out of the endpoints and
   into a script, the script needs a supported way to write notes back — and once notes are
   drafts, a human needs a supported way to approve them. Reaching into the database from
   `scripts/` would bypass every validation the route owns.

2. **The dataset does not exist until we build it (D18).** The design assumed a modelling
   table could be pointed at. It cannot: SEC revenue is cumulative year-to-date, restatements
   overlap, and the market/macro sources are on four different frequencies. Task 1 adds
   `scripts/prepare_dataset.py` and `data-sources/prepared/`, which the design's file layout
   does not mention.

3. **D12 covers five tickers, not three.** `sec-edgar-revenue/` holds six (AAPL, AMD, DELL,
   HPQ, INTC, NVDA); AAPL has no `company-stocks/` file, so the panel is AMD, DELL, HPQ, INTC,
   NVDA. `README.md`'s candidate #4 names Micron, which has a stock file but no revenue file
   and therefore cannot appear at all.

4. **Feature inference reads the DataFrame, not the stored profile.** The design implied
   `infer_feature_columns` could work off `datasets.profile_json`. It cannot: `profiler.py`
   emits only `{"name", "dtype", "n_null"}` per column — there is no `n_unique` to threshold
   on — and `categorical_summary` is emptied entirely when a profile degrades, so the
   profile-based version would silently drop every categorical feature on exactly the large
   datasets where degradation happens.
