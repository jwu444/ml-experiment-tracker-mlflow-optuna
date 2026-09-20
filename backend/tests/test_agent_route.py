"""POST /agent/chat (3.6).

`run_agent` is stubbed exactly as routes/chats.py's tests stub `run_loop` — the
route's job is serialization, and exercising the loop again here would need a
key for no extra coverage.
"""

from app import agent as agent_module
from app.agent import AgentResult, AgentStep
from app.retrieval import Hit


def _hit(source_type="note", run_id="run-1", dataset_id="ds-1"):
    return Hit(
        source_type=source_type,
        source_id=run_id if source_type != "eda" else dataset_id,
        run_id=None if source_type == "eda" else run_id,
        experiment_id=None if source_type == "eda" else "exp-1",
        dataset_id=dataset_id,
        snippet="the snippet",
        score=0.87,
    )


def _result(**overrides):
    base = dict(
        answer="Ridge won.",
        retrieved=[_hit()],
        warnings=[],
        steps=[AgentStep(type="llm", model="claude-sonnet-5", tokens_in=10, tokens_out=5)],
        tokens_in=10,
        tokens_out=5,
        cost_usd=0.001,
        latency_ms=1200,
    )
    base.update(overrides)
    return AgentResult(**base)


def _stub(monkeypatch, result):
    """Patch the name the ROUTE module bound, not app.agent's — the route does
    `from app.agent import run_agent`, so patching the source has no effect."""
    from app.routes import agent as route_module

    calls = []

    def fake(question, session, **kwargs):
        calls.append(question)
        return result

    monkeypatch.setattr(route_module, "run_agent", fake)
    return calls


def test_a_question_returns_the_answer_and_its_sources(client, monkeypatch):
    calls = _stub(monkeypatch, _result())
    resp = client.post("/agent/chat", json={"question": "which model won?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "Ridge won."
    assert calls == ["which model won?"]
    assert len(body["retrieved"]) == 1
    assert body["retrieved"][0]["run_id"] == "run-1"
    assert body["retrieved"][0]["score"] == 0.87


def test_an_eda_hit_carries_a_null_run_id(client, monkeypatch):
    """The UI switches its deep link on this: an eda finding is about a dataset,
    so linking it to a run would send the reader somewhere it is not."""
    _stub(monkeypatch, _result(retrieved=[_hit(source_type="eda")]))
    hit = client.post("/agent/chat", json={"question": "q"}).json()["retrieved"][0]
    assert hit["run_id"] is None
    assert hit["dataset_id"] == "ds-1"


def test_the_trace_reports_tokens_cost_and_steps(client, monkeypatch):
    _stub(monkeypatch, _result())
    trace = client.post("/agent/chat", json={"question": "q"}).json()["trace"]
    assert trace["tokens_in"] == 10
    assert trace["tokens_out"] == 5
    assert trace["cost_usd"] == 0.001
    assert trace["latency_ms"] == 1200
    assert [step["type"] for step in trace["steps"]] == ["llm"]
    assert trace["steps"][0]["model"] == "claude-sonnet-5"


def test_a_tool_step_reports_its_args_and_summary(client, monkeypatch):
    _stub(
        monkeypatch,
        _result(
            steps=[
                AgentStep(
                    type="tool",
                    tool_name="search_runs",
                    tool_args={"query": "ridge"},
                    result_summary="2 source(s): note:abc12345",
                )
            ]
        ),
    )
    step = client.post("/agent/chat", json={"question": "q"}).json()["trace"]["steps"][0]
    assert step["tool_name"] == "search_runs"
    assert step["tool_args"] == {"query": "ridge"}
    assert step["result_summary"] == "2 source(s): note:abc12345"


def test_a_tool_error_is_reported_in_the_trace_not_as_a_500(client, monkeypatch):
    _stub(
        monkeypatch,
        _result(
            steps=[AgentStep(type="tool", tool_name="get_run_detail", error="No run with id 'x'.")]
        ),
    )
    resp = client.post("/agent/chat", json={"question": "q"})
    assert resp.status_code == 200
    assert resp.json()["trace"]["steps"][0]["error"] == "No run with id 'x'."


def test_warnings_reach_the_client(client, monkeypatch):
    """A degraded status filter (3.4a) is something the reader has to see."""
    _stub(monkeypatch, _result(warnings=["tracking store unreachable; status filter dropped"]))
    assert client.post("/agent/chat", json={"question": "q"}).json()["warnings"] == [
        "tracking store unreachable; status filter dropped"
    ]


def test_the_system_prompt_is_never_returned(client, monkeypatch):
    """Same rule as the loop trace (issue #9): the assembled prompt can leak
    guardrail language, so it never leaves the backend."""
    _stub(monkeypatch, _result())
    body = client.post("/agent/chat", json={"question": "q"}).json()
    assert "system_prompt" not in body
    assert "system_prompt" not in body["trace"]
    assert all("system_prompt" not in step for step in body["trace"]["steps"])


def test_a_blank_question_is_a_422(client, monkeypatch):
    _stub(monkeypatch, _result())
    assert client.post("/agent/chat", json={"question": "   "}).status_code == 422
    assert client.post("/agent/chat", json={"question": ""}).status_code == 422


def test_a_missing_question_is_a_422(client, monkeypatch):
    _stub(monkeypatch, _result())
    assert client.post("/agent/chat", json={}).status_code == 422


def test_an_empty_retrieval_is_a_200_with_no_hits(client, monkeypatch):
    """Before `make embed` has run this is the normal state, and it is an answer,
    not an error."""
    _stub(monkeypatch, _result(answer="No reviewed history matches.", retrieved=[]))
    body = client.post("/agent/chat", json={"question": "q"}).json()
    assert body["retrieved"] == []
    assert "No reviewed history" in body["answer"]


def test_the_route_takes_no_chat_id(client, monkeypatch):
    """Stateless and single-shot: no agent_chats table, no history (3.6)."""
    _stub(monkeypatch, _result())
    resp = client.post("/agent/chat", json={"question": "q", "chat_id": "whatever"})
    assert resp.status_code == 422


def test_the_route_is_registered_at_agent_not_under_experiments(client, monkeypatch):
    """D42: the agent answers ACROSS investigations."""
    _stub(monkeypatch, _result())
    assert client.post("/agent/chat", json={"question": "q"}).status_code == 200
    assert client.post("/experiments/agent/chat", json={"question": "q"}).status_code == 404


def test_module_import_needs_no_api_key(monkeypatch):
    """Importing the route must not construct an Anthropic client — the whole
    test suite runs without a key."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert agent_module.TOOLS
