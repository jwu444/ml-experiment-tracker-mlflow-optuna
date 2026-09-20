"""The extraction's contract. The ranking arithmetic is already pinned in
test_ranking.py and the merge in test_routes_experiments_crud.py; what is new
here is that the function is callable without FastAPI and signals a missing
experiment with a type agent._execute cannot mistake for a missing run."""

import pytest
from app.leaderboard import ExperimentNotFound, build_leaderboard


def test_an_unknown_experiment_raises_experiment_not_found(session):
    with pytest.raises(ExperimentNotFound) as excinfo:
        build_leaderboard(session, "no-such-experiment")
    assert excinfo.value.args[0] == "no-such-experiment"


def test_experiment_not_found_is_not_a_key_error():
    """agent._execute catches KeyError for an unknown run_id. If this were a
    KeyError, a missing EXPERIMENT would be reported as a missing RUN."""
    assert issubclass(ExperimentNotFound, LookupError)
    assert not issubclass(ExperimentNotFound, KeyError)


def test_it_returns_the_ranked_rows(session, seeded_experiment):
    """LeaderboardOut carries rows/primary_metric/metric_direction/ranked/
    mlflow_available — and deliberately no experiment_id. It is a shipped API
    response, and widening it for a tool's convenience would change the
    frontend contract for no frontend reason."""
    board = build_leaderboard(session, seeded_experiment.id)
    assert board.primary_metric == seeded_experiment.primary_metric
    assert [row.rank for row in board.rows] == list(range(1, len(board.rows) + 1))


def test_limit_truncates_without_renumbering(session, seeded_experiment):
    """Ranks are over the whole investigation (D38). A truncated view whose top
    row claimed rank 1 would be a lie about a different denominator — the same
    property #51 pins for the frontend's model filter."""
    full = build_leaderboard(session, seeded_experiment.id)
    limited = build_leaderboard(session, seeded_experiment.id, limit=2)
    assert len(limited.rows) == 2
    assert [row.rank for row in limited.rows] == [row.rank for row in full.rows[:2]]


def test_the_route_still_answers_identically(client, seeded_experiment):
    """The refactor's whole claim. If this drifts, the extraction changed
    behaviour."""
    response = client.get(f"/experiments/{seeded_experiment.id}/runs")
    assert response.status_code == 200
    assert response.json()["rows"][0]["rank"] == 1


def test_the_route_still_404s_for_an_unknown_experiment(client):
    assert client.get("/experiments/nope/runs").status_code == 404
