"""The third tool. Offline — build_leaderboard is monkeypatched, so no
Postgres and no Anthropic."""

import datetime as dt

import pytest
from app import agent
from app.agent import TOOLS, validate_tool_call
from app.config import settings
from app.leaderboard import ExperimentNotFound
from app.schemas import LeaderboardOut, LeaderboardRowOut, RunDetailOut


def _run(model_type: str) -> RunDetailOut:
    return RunDetailOut(
        id=f"run-{model_type}",
        mlflow_run_id=f"mlflow-{model_type}",
        experiment_id="e1",
        dataset_id="d1",
        dataset_version="1",
        model_type=model_type,
        task_type="regression",
        notes="",
        notes_status="draft",
        created_at=dt.datetime(2026, 1, 1),
        status="FINISHED",
        params={},
        metrics={},
        mlflow_available=True,
    )


@pytest.fixture
def fake_board() -> LeaderboardOut:
    rows = [
        LeaderboardRowOut(
            run=_run("ridge"),
            rank=1,
            value=1.0,
            cv_value=1.1,
            cv_std=0.2,
            is_best=True,
            within_noise=False,
        ),
        LeaderboardRowOut(
            run=_run("lasso"),
            rank=2,
            value=1.2,
            cv_value=1.3,
            cv_std=0.3,
            is_best=False,
            within_noise=True,
        ),
        LeaderboardRowOut(
            run=_run("persistence"),
            rank=3,
            value=1.5,
            cv_value=1.6,
            cv_std=0.1,
            is_best=False,
            within_noise=False,
        ),
    ]
    return LeaderboardOut(
        primary_metric="rmse",
        metric_direction="minimize",
        ranked=True,
        mlflow_available=True,
        rows=rows,
    )


@pytest.fixture
def fake_board_no_band() -> LeaderboardOut:
    rows = [
        LeaderboardRowOut(
            run=_run("ridge"),
            rank=1,
            value=1.0,
            cv_value=1.1,
            cv_std=None,
            is_best=True,
            within_noise=False,
        ),
        LeaderboardRowOut(
            run=_run("lasso"),
            rank=2,
            value=1.2,
            cv_value=1.3,
            cv_std=None,
            is_best=False,
            within_noise=False,
        ),
        LeaderboardRowOut(
            run=_run("persistence"),
            rank=3,
            value=1.5,
            cv_value=1.6,
            cv_std=None,
            is_best=False,
            within_noise=False,
        ),
    ]
    return LeaderboardOut(
        primary_metric="rmse",
        metric_direction="minimize",
        ranked=True,
        mlflow_available=True,
        rows=rows,
    )


@pytest.fixture
def fake_board_no_mlflow() -> LeaderboardOut:
    rows = [
        LeaderboardRowOut(
            run=_run("ridge"),
            rank=None,
            value=None,
            cv_value=None,
            cv_std=None,
            is_best=False,
            within_noise=False,
        ),
        LeaderboardRowOut(
            run=_run("lasso"),
            rank=None,
            value=None,
            cv_value=None,
            cv_std=None,
            is_best=False,
            within_noise=False,
        ),
        LeaderboardRowOut(
            run=_run("persistence"),
            rank=None,
            value=None,
            cv_value=None,
            cv_std=None,
            is_best=False,
            within_noise=False,
        ),
    ]
    return LeaderboardOut(
        primary_metric="rmse",
        metric_direction="minimize",
        ranked=False,
        mlflow_available=False,
        rows=rows,
    )


def test_the_tool_is_registered_and_named_for_what_it_returns():
    """Not `recommend_next`: a tool returning rows must not be named for the
    conclusion, or the model treats its output as the recommendation."""
    names = [tool["name"] for tool in TOOLS]
    assert "get_leaderboard" in names
    assert "recommend_next" not in names


def test_experiment_id_is_required():
    assert validate_tool_call("get_leaderboard", {}) is not None
    assert validate_tool_call("get_leaderboard", {"experiment_id": "e1"}) is None


def test_a_row_count_over_the_ceiling_is_rejected_not_clamped():
    """Answering 500 with 20 tells the model the investigation holds 20."""
    error = validate_tool_call("get_leaderboard", {"experiment_id": "e1", "limit": 500})
    assert error is not None
    assert str(settings.agent_max_leaderboard_rows) in error


def test_a_zero_or_negative_limit_is_rejected():
    assert validate_tool_call("get_leaderboard", {"experiment_id": "e1", "limit": 0}) is not None
    assert validate_tool_call("get_leaderboard", {"experiment_id": "e1", "limit": -3}) is not None


def test_an_unknown_experiment_comes_back_as_a_tool_result(monkeypatch):
    """_execute never raises (3.5). The model must be able to correct the id."""

    def _raise(session, experiment_id, **kw):
        raise ExperimentNotFound(experiment_id)

    monkeypatch.setattr(agent, "build_leaderboard", _raise)
    text, hits, warnings, error, summary = agent._execute(
        "get_leaderboard", {"experiment_id": "nope"}, session=None
    )
    assert error is not None
    assert "nope" in text
    assert "run" not in text.lower().split("experiment")[0]  # not reported as a missing RUN
    assert hits == []


def test_the_rendered_rows_carry_the_noise_band(monkeypatch, fake_board):
    """D38: a win smaller than the leader's cv_std is within noise. Without the
    band in the tool result the model cannot tell a real lead from a tied one,
    and it will call every lead real."""
    monkeypatch.setattr(agent, "build_leaderboard", lambda *a, **k: fake_board)
    text, _hits, _warnings, error, summary = agent._execute(
        "get_leaderboard", {"experiment_id": "e1"}, session=None
    )
    assert error is None
    assert "cv_std" in text
    assert "rank" in text.lower()
    # within_noise comes from the backend's own D38 judgment, not a
    # re-derivation — two surfaces must not disagree about the same runs.
    assert "within noise" in text


def test_an_absent_cv_std_renders_as_unquantified_never_zero(monkeypatch, fake_board_no_band):
    """D32. A fabricated zero band makes every difference look significant."""
    monkeypatch.setattr(agent, "build_leaderboard", lambda *a, **k: fake_board_no_band)
    text, *_ = agent._execute("get_leaderboard", {"experiment_id": "e1"}, session=None)
    assert "unquantified" in text
    assert "±0.0" not in text and "± 0.0" not in text


def test_an_unreachable_tracking_store_still_returns_rows(monkeypatch, fake_board_no_mlflow):
    """merge_runs degrades to mlflow_available=False rather than raising, and
    that must survive the extraction: the ranking is ours, in Postgres. The
    tool result has to SAY the metrics are missing, though — rows with blank
    values and no explanation read as runs that scored nothing."""
    monkeypatch.setattr(agent, "build_leaderboard", lambda *a, **k: fake_board_no_mlflow)
    text, _hits, _warnings, error, _summary = agent._execute(
        "get_leaderboard", {"experiment_id": "e1"}, session=None
    )
    assert error is None
    assert "mlflow_available=False" in text


def test_the_step_summary_carries_no_row_text(monkeypatch, fake_board):
    """AgentStep carries counts, ids and durations — never retrieved content."""
    monkeypatch.setattr(agent, "build_leaderboard", lambda *a, **k: fake_board)
    _text, _hits, _warnings, _error, summary = agent._execute(
        "get_leaderboard", {"experiment_id": "e1"}, session=None
    )
    assert "row" in summary
    assert fake_board.rows[0].run.model_type not in summary or len(summary) < 60
