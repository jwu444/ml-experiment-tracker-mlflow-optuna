import app.routes.chats as chats_route
from app.loop import LoopResult


def _fake_llm(monkeypatch, tool_calls, text="Looks linear.", pass_count=1, judge_score=88) -> None:
    """Fake run_loop: execute nothing, just hand back a LoopResult. Charts/stats
    are derived by the route only from tool_calls it persists, so on the POST path
    we return empty charts/stats here and let the loop's own tests cover rendering.
    To exercise the render+persist path, pass real tool_calls and set charts/stats."""

    def fake_run_loop(datasets, dfs, prior_messages, question, *, client=None):
        # Render via the same dispatch the real loop uses, so charts/stats/errors
        # match what the route will persist and re-render.
        from app.charts import _DISPATCH
        from app.tools import validate_tool_call

        profiles = {d["id"]: d["profile"] for d in datasets}
        charts, stats, errors, executed = [], [], [], []
        for call in tool_calls:
            err = validate_tool_call(call["name"], call["args"], profiles)
            if err is not None:
                errors.append(err)
                continue
            png, stat = _DISPATCH[call["name"]](dfs, call["args"])
            charts.append(png)
            stats.append(stat)
            executed.append(call)
        return LoopResult(
            interpretation=text,
            tool_calls=executed,
            charts=charts,
            stats=stats,
            errors=errors,
            tokens_in=150,
            tokens_out=40,
            cost_usd=0.002,
            latency_ms=20,
            pass_count=pass_count,
            judge_score=judge_score,
        )

    monkeypatch.setattr(chats_route, "run_loop", fake_run_loop)


def _upload(client, csv="age,score\n20,1\n30,2\n40,3\n", name="d.csv") -> str:
    resp = client.post("/datasets", files={"file": (name, csv, "text/csv")})
    return resp.json()["id"]


def test_create_chat_with_one_dataset(client) -> None:
    dataset_id = _upload(client)
    resp = client.post("/chats", json={"dataset_ids": [dataset_id]})
    assert resp.status_code == 200
    assert resp.json()["datasets"] == [{"id": dataset_id, "name": "d.csv"}]


def test_create_chat_with_multiple_datasets(client) -> None:
    id_a = _upload(client, name="a.csv")
    id_b = _upload(client, csv="region,revenue\neast,1\nwest,2\n", name="b.csv")
    resp = client.post("/chats", json={"dataset_ids": [id_a, id_b]})
    assert resp.status_code == 200
    names = [d["name"] for d in resp.json()["datasets"]]
    assert names == ["a.csv", "b.csv"]


def test_create_chat_requires_at_least_one_dataset(client) -> None:
    resp = client.post("/chats", json={"dataset_ids": []})
    assert resp.status_code == 400


def test_create_chat_unknown_dataset_404(client) -> None:
    resp = client.post("/chats", json={"dataset_ids": ["nope"]})
    assert resp.status_code == 404


def test_chat_runs_and_persists(client, monkeypatch) -> None:
    dataset_id = _upload(client)
    args = {"dataset_id": dataset_id, "x": "age", "y": "score"}
    _fake_llm(monkeypatch, [{"name": "scatter", "args": args}])
    chat_id = client.post("/chats", json={"dataset_ids": [dataset_id]}).json()["id"]

    resp = client.post(f"/chats/{chat_id}/messages", json={"question": "relate them"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["content"] == "Looks linear."
    assert len(body["charts"]) == 1
    assert len(body["stats"]) == 1
    assert body["errors"] == []

    from app.db import get_session
    from app.models import Analysis, Chat, ChatMessage

    session = next(client.app.dependency_overrides[get_session]())
    assert session.query(Chat).count() == 1
    assert session.query(ChatMessage).count() == 2  # user + assistant
    assert session.query(Analysis).count() == 1


def test_chat_persists_loop_metadata(client, monkeypatch) -> None:
    dataset_id = _upload(client)
    args = {"dataset_id": dataset_id, "x": "age", "y": "score"}
    _fake_llm(monkeypatch, [{"name": "scatter", "args": args}], pass_count=2, judge_score=84)
    chat_id = client.post("/chats", json={"dataset_ids": [dataset_id]}).json()["id"]
    client.post(f"/chats/{chat_id}/messages", json={"question": "relate them"})

    from app.db import get_session
    from app.models import ChatMessage

    session = next(client.app.dependency_overrides[get_session]())
    assistant = session.query(ChatMessage).filter(ChatMessage.role == "assistant").one()
    assert assistant.pass_count == 2
    assert assistant.judge_score == 84
    assert assistant.tokens_in == 150


def _trace_payload() -> list[dict]:
    """A representative two-pass trace as run_loop would emit it."""

    def _pass(n, score, revision):
        return {
            "pass_no": n,
            "analyst": {
                "model": "claude-sonnet-5",
                "tokens_in": 100,
                "tokens_out": 30,
                "latency_ms": 12,
                "cost_usd": 0.001,
                "interpretation": f"v{n}",
            },
            "charts": ["iVBORw0KGgoPNG"] * n,  # stored PNGs, n of them
            "stats": [{"kind": "hist"}] * n,
            "errors": [],
            "judge": {
                "model": "claude-sonnet-5",
                "tokens_in": 50,
                "tokens_out": 10,
                "latency_ms": 8,
                "cost_usd": 0.0005,
                "score": score,
                "feedback": "f",
                "gaps": ["add scatter"] if revision else [],
            },
            "revision_instruction": revision,
        }

    return [_pass(1, 60, "A reviewer scored this 60/100. ..."), _pass(2, 88, "")]


def test_chat_persists_and_returns_trace(client, monkeypatch) -> None:
    dataset_id = _upload(client)
    args = {"dataset_id": dataset_id, "x": "age", "y": "score"}

    def fake_run_loop(datasets, dfs, prior_messages, question, *, client=None):
        from app.charts import _DISPATCH

        png, stat = _DISPATCH["scatter"](dfs, args)
        return LoopResult(
            interpretation="Looks linear.",
            tool_calls=[{"name": "scatter", "args": args}],
            charts=[png],
            stats=[stat],
            errors=[],
            pass_count=2,
            judge_score=88,
            trace=_trace_payload(),
        )

    monkeypatch.setattr(chats_route, "run_loop", fake_run_loop)
    chat_id = client.post("/chats", json={"dataset_ids": [dataset_id]}).json()["id"]

    # POST returns the trace.
    body = client.post(f"/chats/{chat_id}/messages", json={"question": "relate"}).json()
    trace = body["trace"]
    assert trace is not None
    # The system prompt is never included in the response.
    assert "system_prompt" not in trace
    assert len(trace["passes"]) == 2
    assert trace["passes"][0]["judge"]["score"] == 60
    assert trace["passes"][0]["revision_instruction"].startswith("A reviewer")
    assert trace["passes"][1]["revision_instruction"] == ""
    assert len(trace["passes"][1]["charts"]) == 2

    # GET history roundtrips the persisted trace verbatim (PNGs stored, not re-rendered).
    hist = client.get(f"/chats/{chat_id}").json()
    assistant = [m for m in hist["messages"] if m["role"] == "assistant"][0]
    assert assistant["trace"]["passes"][1]["judge"]["score"] == 88
    assert "system_prompt" not in assistant["trace"]

    # User rows carry no trace.
    user = [m for m in hist["messages"] if m["role"] == "user"][0]
    assert user["trace"] is None


def test_chat_invalid_tool_arg_is_graceful(client, monkeypatch) -> None:
    dataset_id = _upload(client)
    args = {"dataset_id": dataset_id, "column": "missing"}
    _fake_llm(monkeypatch, [{"name": "histogram", "args": args}])
    chat_id = client.post("/chats", json={"dataset_ids": [dataset_id]}).json()["id"]

    resp = client.post(f"/chats/{chat_id}/messages", json={"question": "hist"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["charts"] == []
    assert len(body["errors"]) == 1


def test_chat_persists_multiple_messages(client, monkeypatch) -> None:
    dataset_id = _upload(client)
    _fake_llm(monkeypatch, [])
    chat_id = client.post("/chats", json={"dataset_ids": [dataset_id]}).json()["id"]
    client.post(f"/chats/{chat_id}/messages", json={"question": "q1"})
    client.post(f"/chats/{chat_id}/messages", json={"question": "q2"})

    resp = client.get(f"/chats/{chat_id}")
    assert len(resp.json()["messages"]) == 4


def test_get_history_rerenders_charts(client, monkeypatch) -> None:
    dataset_id = _upload(client)
    args = {"dataset_id": dataset_id, "x": "age", "y": "score"}
    _fake_llm(monkeypatch, [{"name": "scatter", "args": args}])
    chat_id = client.post("/chats", json={"dataset_ids": [dataset_id]}).json()["id"]
    client.post(f"/chats/{chat_id}/messages", json={"question": "relate them"})

    resp = client.get(f"/chats/{chat_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["datasets"] == [{"id": dataset_id, "name": "d.csv"}]
    messages = body["messages"]
    assert len(messages) == 2
    assistant = [m for m in messages if m["role"] == "assistant"][0]
    assert len(assistant["charts"]) == 1
    assert len(assistant["stats"]) == 1
    assert assistant["errors"] == []


def test_message_unknown_chat_404(client, monkeypatch) -> None:
    _fake_llm(monkeypatch, [])
    resp = client.post("/chats/nope/messages", json={"question": "hi"})
    assert resp.status_code == 404


def test_get_history_unknown_chat_404(client) -> None:
    resp = client.get("/chats/nope")
    assert resp.status_code == 404


def test_compare_across_two_datasets(client, monkeypatch) -> None:
    id_a = _upload(client, csv="region,revenue\neast,10\neast,20\nwest,5\n", name="a.csv")
    id_b = _upload(client, csv="region,revenue\neast,100\nwest,200\nwest,300\n", name="b.csv")
    compare_args = {
        "dataset_a_id": id_a,
        "dataset_b_id": id_b,
        "key_a": "region",
        "key_b": "region",
        "metric_a": "revenue",
        "metric_b": "revenue",
        "agg": "mean",
    }
    _fake_llm(monkeypatch, [{"name": "compare", "args": compare_args}])
    chat_id = client.post("/chats", json={"dataset_ids": [id_a, id_b]}).json()["id"]

    resp = client.post(f"/chats/{chat_id}/messages", json={"question": "compare revenue"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["charts"]) == 1
    assert body["errors"] == []
