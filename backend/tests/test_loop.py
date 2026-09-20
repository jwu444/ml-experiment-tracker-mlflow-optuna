from types import SimpleNamespace

import pandas as pd
from app import loop as loop_module
from app.config import settings
from app.loop import LoopResult, run_loop

PROFILE = {
    "columns": [
        {"name": "age", "dtype": "int64", "n_null": 0},
        {"name": "score", "dtype": "int64", "n_null": 0},
    ]
}
DATASETS = [{"id": "d1", "name": "d.csv", "profile": PROFILE}]


def _dfs():
    return {"d1": pd.DataFrame({"age": [20, 30, 40], "score": [1, 2, 3]})}


def _analyst(text, tool_calls, tin=100, tout=30):
    content = [SimpleNamespace(type="text", text=text)]
    for c in tool_calls:
        content.append(SimpleNamespace(type="tool_use", name=c["name"], input=c["args"]))
    return SimpleNamespace(
        content=content, usage=SimpleNamespace(input_tokens=tin, output_tokens=tout)
    )


def _judge(score, meets_bar=False, gaps=None, tin=50, tout=10):
    v = {"score": score, "meets_bar": meets_bar, "feedback": "f", "gaps": gaps or []}
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", name="submit_verdict", input=v)],
        usage=SimpleNamespace(input_tokens=tin, output_tokens=tout),
    )


class _ScriptedClient:
    """Pops queued responses in call order: analyst1, judge1, analyst2, ..."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0
        self.messages = self

    def create(self, **kwargs):
        self.calls += 1
        return self._responses.pop(0)


HIST = {"name": "histogram", "args": {"dataset_id": "d1", "column": "age"}}
SCAT = {"name": "scatter", "args": {"dataset_id": "d1", "x": "age", "y": "score"}}


def test_threshold_met_on_first_pass(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_max_passes", 3)
    monkeypatch.setattr(settings, "llm_quality_threshold", 80)
    client = _ScriptedClient([_analyst("done", [HIST]), _judge(90, meets_bar=True)])
    result = run_loop(DATASETS, _dfs(), [], "show age", client=client)
    assert isinstance(result, LoopResult)
    assert result.pass_count == 1
    assert result.judge_score == 90
    assert len(result.charts) == 1
    assert client.calls == 2  # one analyst + one judge, no second loop


def test_loops_then_clears_threshold(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_max_passes", 3)
    monkeypatch.setattr(settings, "llm_quality_threshold", 80)
    client = _ScriptedClient(
        [_analyst("v1", [HIST]), _judge(60), _analyst("v2", [SCAT]), _judge(85)]
    )
    result = run_loop(DATASETS, _dfs(), [], "explore", client=client)
    assert result.pass_count == 2
    assert result.judge_score == 85
    assert len(result.charts) == 2  # cumulative across passes
    assert result.interpretation == "v2"


def test_cap_hit_returns_best_pass(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_max_passes", 3)
    monkeypatch.setattr(settings, "llm_quality_threshold", 95)
    client = _ScriptedClient(
        [
            _analyst("v1", [HIST]),
            _judge(60),
            _analyst("v2", [SCAT]),
            _judge(78),
            _analyst("v3", [{"name": "correlation_matrix", "args": {"dataset_id": "d1"}}]),
            _judge(71),
        ]
    )
    result = run_loop(DATASETS, _dfs(), [], "explore", client=client)
    assert result.pass_count == 3
    assert result.judge_score == 78  # best, not last
    assert result.interpretation == "v2"
    # The returned snapshot is pass 2's, not the final cumulative state:
    # pass 3 adds a distinct chart (correlation_matrix) so cumulative == 3,
    # but the winning pass-2 snapshot must stay at 2. Guards against a
    # shared-reference bug (charts=charts instead of charts=list(charts)).
    assert len(result.charts) == 2
    assert len(result.stats) == 2
    assert len(result.tool_calls) == 2


def test_stall_out_stops_early(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_max_passes", 4)
    monkeypatch.setattr(settings, "llm_quality_threshold", 95)
    # pass2 adds no new charts (duplicate HIST) and does not improve (60 -> 60)
    client = _ScriptedClient(
        [_analyst("v1", [HIST]), _judge(60), _analyst("v2", [HIST]), _judge(60)]
    )
    result = run_loop(DATASETS, _dfs(), [], "explore", client=client)
    assert result.pass_count == 2
    assert client.calls == 4  # stopped; did not run pass 3


def test_judge_error_returns_best_so_far(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_max_passes", 3)
    monkeypatch.setattr(settings, "llm_quality_threshold", 95)
    bad_judge = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="oops")],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    client = _ScriptedClient(
        [_analyst("v1", [HIST]), _judge(70), _analyst("v2", [SCAT]), bad_judge]
    )
    result = run_loop(DATASETS, _dfs(), [], "explore", client=client)
    assert result.pass_count == 2
    assert result.judge_score == 70  # pass 2's judge failed -> best is pass 1
    assert result.interpretation == "v1"


def test_no_pass_scores_falls_back_to_last(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_max_passes", 3)
    monkeypatch.setattr(settings, "llm_quality_threshold", 95)
    # Pass 1's judge fails (score=None) on the very first pass -> terminal stop.
    # No pass ever scored, so the loop falls back to the last/only snapshot.
    bad_judge = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="oops")],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    client = _ScriptedClient([_analyst("v1", [HIST]), bad_judge])
    result = run_loop(DATASETS, _dfs(), [], "explore", client=client)
    assert result.judge_score is None
    assert result.interpretation == "v1"
    assert result.pass_count == 1


def test_invalid_tool_call_is_skipped(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_max_passes", 1)
    bad = {"name": "histogram", "args": {"dataset_id": "d1", "column": "missing"}}
    client = _ScriptedClient([_analyst("v1", [bad]), _judge(50)])
    result = run_loop(DATASETS, _dfs(), [], "explore", client=client)
    assert result.charts == []
    assert len(result.errors) == 1


def test_render_error_is_skipped_but_loop_continues(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_max_passes", 1)

    def _raise(dfs, args):
        raise ValueError("boom")

    monkeypatch.setitem(loop_module._DISPATCH, "histogram", _raise)
    client = _ScriptedClient([_analyst("v1", [HIST]), _judge(50)])
    result = run_loop(DATASETS, _dfs(), [], "explore", client=client)
    assert isinstance(result, LoopResult)
    assert result.charts == []
    assert result.stats == []
    assert result.tool_calls == []
    assert len(result.errors) == 1
    assert "histogram" in result.errors[0]
    assert "boom" in result.errors[0]


def test_telemetry_summed_across_passes(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_max_passes", 2)
    monkeypatch.setattr(settings, "llm_quality_threshold", 95)
    client = _ScriptedClient(
        [_analyst("v1", [HIST]), _judge(60), _analyst("v2", [SCAT]), _judge(70)]
    )
    result = run_loop(DATASETS, _dfs(), [], "explore", client=client)
    # 2 analyst (100 in / 30 out each) + 2 judge (50 in / 10 out each)
    assert result.tokens_in == 2 * 100 + 2 * 50
    assert result.tokens_out == 2 * 30 + 2 * 10
    assert result.cost_usd > 0


def test_trace_has_one_entry_per_pass(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_max_passes", 3)
    monkeypatch.setattr(settings, "llm_quality_threshold", 80)
    client = _ScriptedClient(
        [
            _analyst("v1", [HIST]),
            _judge(60, gaps=["add scatter"]),
            _analyst("v2", [SCAT]),
            _judge(85),
        ]
    )
    result = run_loop(DATASETS, _dfs(), [], "explore", client=client)

    assert len(result.trace) == 2
    p1, p2 = result.trace
    assert p1["pass_no"] == 1 and p2["pass_no"] == 2

    # Per-pass analyst + judge telemetry is captured with a positive cost.
    assert p1["analyst"]["model"]  # non-empty model id
    assert p1["analyst"]["tokens_in"] == 100 and p1["analyst"]["tokens_out"] == 30
    assert p1["analyst"]["cost_usd"] > 0
    assert p1["analyst"]["interpretation"] == "v1"
    assert p1["judge"]["tokens_in"] == 50 and p1["judge"]["tokens_out"] == 10
    assert p1["judge"]["cost_usd"] > 0
    assert p1["judge"]["score"] == 60
    assert p1["judge"]["gaps"] == ["add scatter"]

    # Per-pass charts reflect the cumulative state the judge scored.
    assert len(p1["charts"]) == 1
    assert len(p2["charts"]) == 2


def test_trace_revision_instruction_between_passes(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_max_passes", 3)
    monkeypatch.setattr(settings, "llm_quality_threshold", 80)
    client = _ScriptedClient(
        [_analyst("v1", [HIST]), _judge(60), _analyst("v2", [SCAT]), _judge(85)]
    )
    result = run_loop(DATASETS, _dfs(), [], "explore", client=client)
    # Pass 1 fed a revision instruction into pass 2; the last pass has none.
    assert "60/100" in result.trace[0]["revision_instruction"]
    assert result.trace[1]["revision_instruction"] == ""


def test_trace_excludes_system_prompt(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_max_passes", 1)
    client = _ScriptedClient([_analyst("v1", [HIST]), _judge(50)])
    result = run_loop(DATASETS, _dfs(), [], "explore", client=client)
    # The system prompt is intentionally not surfaced anywhere on the result — it
    # can leak guardrail language, so it never leaves the backend.
    assert not hasattr(result, "system_prompt")
