"""One investigation's runs, ranked by its primary metric (D38).

Extracted out of `routes/experiments.py`'s `GET /{experiment_id}/runs` handler
so Task 10's `get_leaderboard` agent tool can reach the same logic without
importing `HTTPException` into the tool layer — a 404 raised at a model is not
an HTTP concern, and `app.agent._execute` never raises.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Experiment, Run
from app.ranking import rank_runs
from app.routes.shared import merge_runs
from app.schemas import LeaderboardOut, LeaderboardRowOut, RunDetailOut
from app.tracing import span


class ExperimentNotFound(LookupError):
    """Raised when no experiment answers to an id.

    `LookupError`, deliberately not `KeyError`: `agent._execute` already
    catches `KeyError` for an unknown `run_id`, and a missing experiment
    reported as a missing run is a wrong message with nothing about it
    looking wrong.
    """


def build_leaderboard(
    session: Session, experiment_id: str, *, limit: int | None = None
) -> LeaderboardOut:
    """One investigation's runs, ranked by its primary metric (D38).

    Ranking the whole table would compare a revenue rmse against a GPU-price
    rmse — two numbers on unrelated scales. An experiment is what defines the
    comparable set.
    """
    with span("leaderboard.build", experiment_id=experiment_id, limit=limit) as board_span:
        experiment = session.get(Experiment, experiment_id)
        if experiment is None:
            raise ExperimentNotFound(experiment_id)
        runs = list(
            session.execute(
                select(Run)
                .where(Run.experiment_id == experiment_id)
                .order_by(Run.created_at.desc())
            ).scalars()
        )
        # merge_runs reads inherited fields off each run's own `experiment`
        # relationship, which is exactly what every run here has, since they
        # were all just filtered by experiment_id.
        details: list[RunDetailOut] = merge_runs(runs)
        available = all(d.mlflow_available for d in details) and bool(details)
        if not details or not available:
            rows = [
                LeaderboardRowOut(
                    run=d,
                    rank=None,
                    value=None,
                    cv_value=None,
                    cv_std=None,
                    is_best=False,
                    within_noise=False,
                )
                for d in details
            ]
            if limit is not None:
                # Truncate AFTER ranking. The ranks are over the whole
                # investigation (D38); renumbering a truncated view would
                # report a different denominator as the same one.
                rows = rows[:limit]
            board_span.set_attribute("rows", len(rows))
            return LeaderboardOut(
                primary_metric=experiment.primary_metric,
                metric_direction=experiment.metric_direction,
                ranked=False,
                mlflow_available=available if details else True,
                rows=rows,
            )

        by_id = {d.id: d for d in details}
        ranked = rank_runs(
            [(d.id, d.metrics) for d in details],
            experiment.primary_metric,
            experiment.metric_direction,
        )
        rows = [
            LeaderboardRowOut(
                run=by_id[r.run_id],
                rank=r.rank,
                value=r.value,
                cv_value=r.cv_value,
                cv_std=r.cv_std,
                is_best=r.is_best,
                within_noise=r.within_noise,
            )
            for r in ranked
        ]
        if limit is not None:
            rows = rows[:limit]
        board_span.set_attribute("rows", len(rows))
        return LeaderboardOut(
            primary_metric=experiment.primary_metric,
            metric_direction=experiment.metric_direction,
            ranked=True,
            mlflow_available=True,
            rows=rows,
        )
