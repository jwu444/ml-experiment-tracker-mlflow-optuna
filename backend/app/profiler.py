from __future__ import annotations

import json
import math
from typing import Any

import pandas as pd


def _estimate_tokens(profile: dict[str, Any]) -> int:
    # Cheap proxy: ~4 characters per token over the serialized profile.
    return len(json.dumps(profile, default=str)) // 4


def _is_na_scalar(value: Any) -> bool:
    # Guard pd.isna against array-like values (it returns an array for those).
    result = pd.isna(value)
    return bool(result) if isinstance(result, bool) else False


def _json_safe(value: Any) -> Any:
    # Postgres' json/jsonb column rejects the raw NaN/Infinity/-Infinity tokens
    # Python's json.dumps emits for non-finite floats, and pandas NA-likes
    # (NaN, NaT, pd.NA) aren't valid JSON either — normalize both to None so
    # profile_json always round-trips. describe() and corr() can produce
    # non-finite floats from divide-by-zero or zero-variance columns.
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return None if _is_na_scalar(value) else value


# Keyword defaults mirror `app.config.Settings` so the function stays unit-testable in
# isolation; the upload route passes the live `settings.profile_*` values explicitly, which
# are the single source of truth (overridable via `.env`, see design §4).
def profile_dataframe(
    df: pd.DataFrame,
    sample_rows: int = 5,
    max_cardinality: int = 20,
    max_corr_cols: int = 30,
    top_corr_pairs: int = 25,
    token_budget: int = 8000,
) -> dict[str, Any]:
    numeric = df.select_dtypes(include="number")

    columns = [
        {"name": str(c), "dtype": str(df[c].dtype), "n_null": int(df[c].isna().sum())}
        for c in df.columns
    ]

    numeric_summary: dict[str, Any] = {}
    if not numeric.empty:
        desc = numeric.describe().to_dict()
        numeric_summary = {
            str(col): {str(stat): _json_safe(float(val)) for stat, val in stats.items()}
            for col, stats in desc.items()
        }

    # Correlations: full pairwise list when within the column cap, else only the
    # strongest `top_corr_pairs` pairs (design §4).
    correlations: list[dict[str, Any]] = []
    if numeric.shape[1] >= 2:
        corr = numeric.corr().abs()
        cols = list(corr.columns)
        pairs: list[dict[str, Any]] = []
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                pairs.append(
                    {"a": str(cols[i]), "b": str(cols[j]), "abs_corr": float(corr.iloc[i, j])}
                )
        pairs.sort(key=lambda p: p["abs_corr"], reverse=True)
        correlations = pairs if numeric.shape[1] <= max_corr_cols else pairs[:top_corr_pairs]
        # A zero-variance (constant) column makes corr() emit NaN for that pair —
        # sanitize after sorting so raw floats (not None) drive the sort order.
        for pair in correlations:
            pair["abs_corr"] = _json_safe(pair["abs_corr"])

    # Cardinality-aware value_counts: only low-cardinality non-numeric columns,
    # top `max_cardinality` values. High-cardinality columns (IDs, free text,
    # timestamps) are skipped — they bloat context and teach Claude nothing.
    categorical_summary: dict[str, Any] = {}
    for col in df.select_dtypes(exclude="number").columns:
        if df[col].nunique(dropna=True) > max_cardinality:
            continue
        counts = df[col].value_counts().head(max_cardinality)
        categorical_summary[str(col)] = {str(value): int(count) for value, count in counts.items()}

    # NaN/inf -> None at the record level: a float column's `where(..., None)`
    # re-coerces None back to NaN under pandas 2.3, so normalize each scalar
    # after to_dict() instead (_json_safe covers both NA-likes and non-finite floats).
    sample = df.head(sample_rows)
    sample_records = [
        {key: _json_safe(value) for key, value in row.items()}
        for row in sample.to_dict(orient="records")
    ]

    profile: dict[str, Any] = {
        "n_rows": int(len(df)),
        "n_cols": int(df.shape[1]),
        "columns": columns,
        "numeric_summary": numeric_summary,
        "categorical_summary": categorical_summary,
        "correlations": correlations,
        "sample_rows": sample_records,
        "degraded": False,
    }

    # Profile-token budget: if the assembled profile is too large, degrade to
    # schema + describe() + correlations only (design §4).
    if _estimate_tokens(profile) > token_budget:
        profile = {
            "n_rows": profile["n_rows"],
            "n_cols": profile["n_cols"],
            "columns": columns,
            "numeric_summary": numeric_summary,
            "categorical_summary": {},
            "correlations": correlations,
            "sample_rows": [],
            "degraded": True,
        }
    return profile
