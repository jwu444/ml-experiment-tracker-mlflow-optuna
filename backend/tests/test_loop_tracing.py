"""run_loop emits spans (3.2). Proving the helpers against shipped code before
the agent depends on them."""

from app import loop
from app.llm import AnalystResult, JudgeResult


class _FakeClient:
    """Minimal stand-in: analyst_call and judge_call are both monkeypatched, so
    nothing ever reaches the client — it only has to be a non-None object, since
    run_loop falls back to a real anthropic.Anthropic when it is None."""


def _stub_calls(monkeypatch, *, score: int, model: str = "claude-sonnet-5") -> None:
    monkeypatch.setattr(
        loop,
        "analyst_call",
        lambda client, system, messages: AnalystResult(
            text="looks fine",
            tool_calls=[],
            tokens_in=10,
            tokens_out=5,
            latency_ms=1,
            model=model,
        ),
    )
    monkeypatch.setattr(
        loop,
        "judge_call",
        lambda *args, **kwargs: JudgeResult(
            score=score,
            meets_bar=True,
            feedback="good",
            gaps=[],
            tokens_in=4,
            tokens_out=2,
            latency_ms=1,
            model=model,
        ),
    )


def test_run_loop_emits_a_root_span_and_one_span_per_call(spans, monkeypatch):
    _stub_calls(monkeypatch, score=95)

    result = loop.run_loop([], {}, [], "what is the mean?", client=_FakeClient())
    assert result.pass_count == 1

    names = [s.name for s in spans.get_finished_spans()]
    assert "llm.analyst_pass" in names
    assert "charts.render" in names
    assert "llm.judge_pass" in names
    assert "llm.loop" in names
    # The root closes last: every call must be inside it, or a trace shows
    # orphaned spans with no turn to attribute them to.
    assert names[-1] == "llm.loop"


def test_loop_span_carries_counts_not_payloads(spans, monkeypatch):
    """Ids, counts and durations only — never the question or the chart PNGs."""
    _stub_calls(monkeypatch, score=99, model="m")

    loop.run_loop([], {}, [], "a question that must not appear in the trace", client=_FakeClient())
    finished = spans.get_finished_spans()
    root = next(s for s in finished if s.name == "llm.loop")
    assert root.attributes["pass_count"] == 1
    assert root.attributes["best_score"] == 99
    serialized = repr([dict(s.attributes) for s in finished])
    assert "a question that must not appear" not in serialized
    assert "looks fine" not in serialized


def test_every_pass_span_hangs_off_the_turn(spans, monkeypatch):
    _stub_calls(monkeypatch, score=95)
    loop.run_loop([], {}, [], "q", client=_FakeClient())

    finished = {s.name: s for s in spans.get_finished_spans()}
    root = finished["llm.loop"]
    for name in ("llm.analyst_pass", "charts.render", "llm.judge_pass"):
        assert finished[name].parent.span_id == root.context.span_id, name


def test_a_second_pass_emits_a_second_set_of_spans(spans, monkeypatch):
    """A failing judge score drives another pass, and the trace has to show two
    of everything — a per-turn span that recorded only the last pass would hide
    exactly the retries the loop exists to do."""
    _stub_calls(monkeypatch, score=10)

    result = loop.run_loop([], {}, [], "q", client=_FakeClient())
    # Score never improves and no charts are added, so the loop stalls out after
    # the second pass rather than running the full cap.
    assert result.pass_count == 2

    names = [s.name for s in spans.get_finished_spans()]
    assert names.count("llm.analyst_pass") == 2
    assert names.count("llm.judge_pass") == 2


def test_the_two_spans_of_one_pass_share_a_pass_index(spans, monkeypatch):
    """The analyst and judge of pass 1 are pass 1. Incrementing the counter
    between them numbered one pass twice, which reads as two passes in Jaeger."""
    _stub_calls(monkeypatch, score=95)
    loop.run_loop([], {}, [], "q", client=_FakeClient())

    finished = {s.name: s for s in spans.get_finished_spans()}
    assert finished["llm.analyst_pass"].attributes["pass_index"] == 1
    assert finished["llm.judge_pass"].attributes["pass_index"] == 1


def test_a_judge_with_no_verdict_records_a_flag_not_a_sentinel_score(spans, monkeypatch):
    """`score` must be absent, never -1.

    A -1 sentinel is silently averaged into any dashboard built on the
    attribute, which reads as a real (terrible) score rather than as a missing
    one. `span()` already drops None attributes so callers need no sentinel.
    """
    _stub_calls(monkeypatch, score=95)
    monkeypatch.setattr(
        loop,
        "judge_call",
        lambda *args, **kwargs: JudgeResult(
            score=None,
            meets_bar=False,
            feedback="",
            gaps=[],
            tokens_in=4,
            tokens_out=2,
            latency_ms=1,
            model="m",
        ),
    )

    loop.run_loop([], {}, [], "what is the mean?", client=_FakeClient())
    finished = spans.get_finished_spans()

    judge = next(s for s in finished if s.name == "llm.judge_pass")
    assert "score" not in judge.attributes
    assert judge.attributes["judge_failed"] is True

    root = next(s for s in finished if s.name == "llm.loop")
    assert "best_score" not in root.attributes


def test_the_render_span_reports_this_pass_errors_not_every_pass_so_far(spans, monkeypatch):
    """`errors` accumulates across the loop; `charts` does not.

    Reporting len(errors) on a per-pass span means pass 2 re-reports pass 1's
    failures beside a chart count that is genuinely per-pass — two different
    denominators under one span.
    """
    calls = {"n": 0}

    def analyst(client, system, messages):
        calls["n"] += 1
        # An unknown tool: validate_tool_call rejects it, so each pass appends
        # exactly one error and renders no chart.
        return AnalystResult(
            text=f"pass {calls['n']}",
            tool_calls=[{"name": "no_such_tool", "args": {}}],
            tokens_in=10,
            tokens_out=5,
            latency_ms=1,
            model="m",
        )

    monkeypatch.setattr(loop, "analyst_call", analyst)
    # Score below the threshold and never improving would stall the loop after
    # one pass (added == 0 and not improved), so climb to force a second.
    scores = iter([10, 20, 30])
    monkeypatch.setattr(
        loop,
        "judge_call",
        lambda *args, **kwargs: JudgeResult(
            score=next(scores),
            meets_bar=False,
            feedback="more",
            gaps=[],
            tokens_in=4,
            tokens_out=2,
            latency_ms=1,
            model="m",
        ),
    )

    loop.run_loop([], {}, [], "what is the mean?", client=_FakeClient())

    renders = [s for s in spans.get_finished_spans() if s.name == "charts.render"]
    assert len(renders) >= 2
    assert [s.attributes["errors"] for s in renders[:2]] == [1, 1]
    assert [s.attributes["errors_total"] for s in renders[:2]] == [1, 2]
