"""The hand-rolled agent loop (3.5).

The Anthropic client is a stub throughout — no test in this file needs a key.
"""

from types import SimpleNamespace

from app import agent, retrieval


class _Block(SimpleNamespace):
    pass


def _text(value):
    return _Block(type="text", text=value)


def _tool_use(name, args, tool_id="t1"):
    return _Block(type="tool_use", name=name, input=args, id=tool_id)


class FakeAnthropic:
    """Returns a scripted response per call and records what it was sent."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        content, stop_reason = self._responses.pop(0)
        return SimpleNamespace(
            content=content,
            stop_reason=stop_reason,
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


def _hit(snippet="a note", run_id="run-1"):
    return retrieval.Hit(
        source_type="note",
        source_id=run_id,
        run_id=run_id,
        experiment_id="exp-1",
        dataset_id="ds-1",
        snippet=snippet,
        score=0.9,
    )


def test_a_direct_answer_needs_no_tools(db_session):
    client = FakeAnthropic([([_text("No reviewed history matches that.")], "end_turn")])
    result = agent.run_agent("anything?", db_session, client=client)
    assert result.answer == "No reviewed history matches that."
    assert [step.type for step in result.steps] == ["llm"]


def test_a_search_call_is_executed_and_fed_back(db_session, monkeypatch):
    monkeypatch.setattr(retrieval, "search_runs", lambda *a, **k: ([_hit()], []))
    client = FakeAnthropic(
        [
            ([_tool_use("search_runs", {"query": "ridge"})], "tool_use"),
            ([_text("Ridge won, per run-1.")], "end_turn"),
        ]
    )

    result = agent.run_agent("which model won?", db_session, client=client)
    assert result.answer == "Ridge won, per run-1."
    assert [step.type for step in result.steps] == ["llm", "tool", "llm"]
    # The second call carries the tool result back.
    assert len(client.calls[1]["messages"]) > len(client.calls[0]["messages"])


def test_retrieved_hits_are_accumulated_across_calls(db_session, monkeypatch):
    """The response's `retrieved` list is what the UI deep-links from. Keeping
    only the last search's hits would drop citations the answer actually used."""
    hits = iter([([_hit(run_id="run-1")], []), ([_hit(run_id="run-2")], [])])
    monkeypatch.setattr(retrieval, "search_runs", lambda *a, **k: next(hits))
    client = FakeAnthropic(
        [
            ([_tool_use("search_runs", {"query": "a"}, "t1")], "tool_use"),
            ([_tool_use("search_runs", {"query": "b"}, "t2")], "tool_use"),
            ([_text("Both.")], "end_turn"),
        ]
    )

    result = agent.run_agent("q", db_session, client=client)
    assert {hit.run_id for hit in result.retrieved} == {"run-1", "run-2"}


def test_a_duplicate_hit_is_not_listed_twice(db_session, monkeypatch):
    monkeypatch.setattr(retrieval, "search_runs", lambda *a, **k: ([_hit()], []))
    client = FakeAnthropic(
        [
            ([_tool_use("search_runs", {"query": "a"}, "t1")], "tool_use"),
            ([_tool_use("search_runs", {"query": "b"}, "t2")], "tool_use"),
            ([_text("Done.")], "end_turn"),
        ]
    )
    result = agent.run_agent("q", db_session, client=client)
    assert len(result.retrieved) == 1


def test_an_invalid_tool_call_returns_the_error_to_the_model(db_session):
    """The model gets a correctable message, not a 500. This is the difference
    between one wasted turn and a failed request."""
    client = FakeAnthropic(
        [
            ([_tool_use("search_runs", {})], "tool_use"),
            ([_text("Sorry — retrying.")], "end_turn"),
        ]
    )
    result = agent.run_agent("q", db_session, client=client)
    tool_step = next(step for step in result.steps if step.type == "tool")
    assert tool_step.error is not None
    assert "query" in tool_step.error
    assert result.answer == "Sorry — retrying."


def test_a_tool_that_raises_becomes_an_error_result_not_a_500(db_session, monkeypatch):
    def boom(*a, **k):
        raise retrieval.TrackingStoreUnavailable("connection refused")

    monkeypatch.setattr(retrieval, "get_run_detail", boom)
    client = FakeAnthropic(
        [
            ([_tool_use("get_run_detail", {"run_id": "run-1"})], "tool_use"),
            ([_text("The tracking store is down.")], "end_turn"),
        ]
    )

    result = agent.run_agent("q", db_session, client=client)
    tool_step = next(step for step in result.steps if step.type == "tool")
    assert "connection refused" in tool_step.error
    assert result.answer == "The tracking store is down."


def test_an_unknown_run_id_is_reported_to_the_model(db_session, monkeypatch):
    def missing(session, run_id):
        raise KeyError(run_id)

    monkeypatch.setattr(retrieval, "get_run_detail", missing)
    client = FakeAnthropic(
        [
            ([_tool_use("get_run_detail", {"run_id": "nope"})], "tool_use"),
            ([_text("That run does not exist.")], "end_turn"),
        ]
    )
    result = agent.run_agent("q", db_session, client=client)
    tool_step = next(step for step in result.steps if step.type == "tool")
    assert "nope" in tool_step.error


def test_hitting_the_turn_cap_still_produces_an_answer(db_session, monkeypatch):
    """THE cap test. Without the forced final call the user gets an empty answer,
    which is indistinguishable from a backend failure."""
    monkeypatch.setattr(agent.settings, "agent_max_turns", 2)
    monkeypatch.setattr(retrieval, "search_runs", lambda *a, **k: ([_hit()], []))
    client = FakeAnthropic(
        [
            ([_tool_use("search_runs", {"query": "a"}, "t1")], "tool_use"),
            ([_tool_use("search_runs", {"query": "b"}, "t2")], "tool_use"),
            ([_text("Best effort from what I found.")], "end_turn"),
        ]
    )

    result = agent.run_agent("q", db_session, client=client)
    assert result.answer == "Best effort from what I found."


def test_the_forced_final_call_has_no_tools(db_session, monkeypatch):
    """Offering tools to a call whose whole purpose is to stop using them
    invites another tool_use, and the loop never terminates."""
    monkeypatch.setattr(agent.settings, "agent_max_turns", 1)
    monkeypatch.setattr(retrieval, "search_runs", lambda *a, **k: ([_hit()], []))
    client = FakeAnthropic(
        [
            ([_tool_use("search_runs", {"query": "a"}, "t1")], "tool_use"),
            ([_text("Done.")], "end_turn"),
        ]
    )

    agent.run_agent("q", db_session, client=client)
    assert "tools" in client.calls[0]
    assert "tools" not in client.calls[-1] or client.calls[-1]["tools"] == []


def test_the_forced_final_call_also_says_so_in_words(db_session, monkeypatch):
    """Removing `tools` is not enough. The transcript still carries tool_use and
    tool_result blocks, and the model reads those as evidence the tools exist and
    emits another tool_use — observed live, with stop_reason "tool_use" on a
    request carrying no tool definitions. The loop then breaks with no text block
    and the user gets an empty answer."""
    monkeypatch.setattr(agent.settings, "agent_max_turns", 1)
    monkeypatch.setattr(retrieval, "search_runs", lambda *a, **k: ([_hit()], []))
    client = FakeAnthropic(
        [
            ([_tool_use("search_runs", {"query": "a"}, "t1")], "tool_use"),
            ([_text("Done.")], "end_turn"),
        ]
    )

    agent.run_agent("q", db_session, client=client)
    final = client.calls[-1]["messages"][-1]
    assert final["role"] == "user"
    # Attached to the trailing tool_result message, not sent as a second user
    # turn: the Messages API rejects a user message following another one.
    assert any(block.get("type") == "tool_result" for block in final["content"])
    assert "tool budget" in final["content"][-1]["text"]


def test_the_instruction_does_not_leak_into_the_stored_transcript(db_session, monkeypatch):
    """`messages` is mutated in place across turns; the forced call gets a COPY,
    so an in-place append would survive into a transcript the loop is done with."""
    monkeypatch.setattr(agent.settings, "agent_max_turns", 1)
    monkeypatch.setattr(retrieval, "search_runs", lambda *a, **k: ([_hit()], []))
    client = FakeAnthropic(
        [
            ([_tool_use("search_runs", {"query": "a"}, "t1")], "tool_use"),
            ([_text("Done.")], "end_turn"),
        ]
    )

    agent.run_agent("q", db_session, client=client)
    tool_result_turn = client.calls[0]["messages"]
    assert all("tool budget" not in str(m) for m in tool_result_turn)


def test_an_answerless_run_returns_prose_not_an_empty_string(db_session, monkeypatch):
    """Belt and braces for the case above: a forced call that STILL returns only
    a tool_use leaves `answer` empty, and an empty answer renders as a blank
    bubble indistinguishable from a crashed request."""
    monkeypatch.setattr(agent.settings, "agent_max_turns", 1)
    monkeypatch.setattr(retrieval, "search_runs", lambda *a, **k: ([_hit()], []))
    client = FakeAnthropic(
        [
            ([_tool_use("search_runs", {"query": "a"}, "t1")], "tool_use"),
            ([_tool_use("search_runs", {"query": "b"}, "t2")], "tool_use"),
        ]
    )

    result = agent.run_agent("q", db_session, client=client)
    assert result.answer.strip()
    assert "could not produce an answer" in result.answer
    # The sources it did find are still returned — they are the useful half.
    assert len(result.retrieved) == 1


def test_a_thinking_block_alongside_text_does_not_hide_the_answer(db_session):
    """Sonnet 5 returns thinking blocks by default; the answer is the text ones."""
    client = FakeAnthropic(
        [([_Block(type="thinking", thinking="hmm"), _text("The answer.")], "end_turn")]
    )
    result = agent.run_agent("q", db_session, client=client)
    assert result.answer == "The answer."


def test_tokens_are_summed_across_every_call(db_session, monkeypatch):
    monkeypatch.setattr(retrieval, "search_runs", lambda *a, **k: ([_hit()], []))
    client = FakeAnthropic(
        [
            ([_tool_use("search_runs", {"query": "a"}, "t1")], "tool_use"),
            ([_text("Done.")], "end_turn"),
        ]
    )
    result = agent.run_agent("q", db_session, client=client)
    assert result.tokens_in == 20  # two calls at 10
    assert result.tokens_out == 10


def test_steps_never_carry_the_retrieved_text(db_session, monkeypatch):
    """A step is a receipt, not a copy of the corpus. result_summary is counts
    and ids; the text lives once, in `retrieved`."""
    monkeypatch.setattr(
        retrieval, "search_runs", lambda *a, **k: ([_hit(snippet="SECRET_SNIPPET")], [])
    )
    client = FakeAnthropic(
        [
            ([_tool_use("search_runs", {"query": "a"}, "t1")], "tool_use"),
            ([_text("Done.")], "end_turn"),
        ]
    )
    result = agent.run_agent("q", db_session, client=client)
    assert all("SECRET_SNIPPET" not in (step.result_summary or "") for step in result.steps)


def test_the_system_prompt_is_sent_but_never_returned(db_session):
    """Same rule as the loop trace (issue #9): the assembled system prompt can
    carry guardrail language and never leaves the backend."""
    client = FakeAnthropic([([_text("ok")], "end_turn")])
    result = agent.run_agent("q", db_session, client=client)
    assert client.calls[0]["system"]
    assert not hasattr(result, "system_prompt")


def test_retrieval_warnings_reach_the_result(db_session, monkeypatch):
    monkeypatch.setattr(
        retrieval, "search_runs", lambda *a, **k: ([], ["status filter was not applied"])
    )
    client = FakeAnthropic(
        [
            ([_tool_use("search_runs", {"query": "a", "status": "FINISHED"}, "t1")], "tool_use"),
            ([_text("Partial.")], "end_turn"),
        ]
    )
    result = agent.run_agent("q", db_session, client=client)
    assert result.warnings == ["status filter was not applied"]
