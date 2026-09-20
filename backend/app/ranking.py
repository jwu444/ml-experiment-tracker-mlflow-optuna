"""Rank the runs inside one experiment (D38).

Deliberately pure: metrics in, ranked order out. The route supplies the
metrics it already fetched from MLflow, so this module has no DB session, no
tracking-store call, and no HTTP — which is what lets the three subtle rules
(missing metric, noise band, absent spread) be tested exactly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

_DIRECTIONS = {"minimize", "maximize"}


@dataclass(frozen=True)
class RankedRun:
    run_id: str
    rank: int | None  # 1-based; None when the ranking metric is absent
    value: float | None
    cv_value: float | None
    cv_std: float | None
    is_best: bool
    within_noise: bool


def rank_runs(
    rows: Sequence[tuple[str, dict[str, float]]],
    primary_metric: str,
    direction: str,
) -> list[RankedRun]:
    """Order `rows` (run id, MLflow metrics) by `primary_metric`.

    Runs missing the metric keep their incoming order and are appended
    unranked. The leader is flagged `within_noise` when its margin over second
    place is smaller than its own cross-validated spread — see §7.3.
    """
    if direction not in _DIRECTIONS:
        raise ValueError(f"direction must be one of {sorted(_DIRECTIONS)}, got {direction!r}")

    scored = [(rid, m) for rid, m in rows if primary_metric in m]
    unscored = [(rid, m) for rid, m in rows if primary_metric not in m]
    scored.sort(key=lambda pair: pair[1][primary_metric], reverse=direction == "maximize")

    # cv_rmse is named f"cv_{objective_metric}" by the training path, so the
    # noise-band key is derived rather than stored as a second column (§3.1).
    cv_key = f"cv_{primary_metric}"

    within_noise = False
    if len(scored) >= 2:
        leader_std = scored[0][1].get("cv_std")
        if leader_std is not None:
            margin = abs(scored[0][1][primary_metric] - scored[1][1][primary_metric])
            within_noise = margin < leader_std

    out = [
        RankedRun(
            run_id=rid,
            rank=i + 1,
            value=metrics[primary_metric],
            cv_value=metrics.get(cv_key),
            cv_std=metrics.get("cv_std"),
            is_best=i == 0,
            within_noise=within_noise if i == 0 else False,
        )
        for i, (rid, metrics) in enumerate(scored)
    ]
    out.extend(
        RankedRun(
            run_id=rid,
            rank=None,
            value=None,
            cv_value=metrics.get(cv_key),
            cv_std=metrics.get("cv_std"),
            is_best=False,
            within_noise=False,
        )
        for rid, metrics in unscored
    )
    return out
