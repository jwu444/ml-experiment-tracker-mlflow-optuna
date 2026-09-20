"""Tool schemas, argument validation, and the agent's system prompt (3.5)."""

from app import agent
from app.config import settings


def test_the_tools_are_named_for_runs_not_experiments():
    """D41: since D33 an 'experiment' is an INVESTIGATION. A tool called
    search_experiments makes the model search for investigations when what it
    wants is runs, and the mistake is invisible in the transcript. D47 adds a
    third tool, get_leaderboard — named for what it returns, not the
    recommendation the model might draw from it."""
    assert {tool["name"] for tool in agent.TOOLS} == {
        "search_runs",
        "get_run_detail",
        "get_leaderboard",
    }


def test_search_runs_requires_only_a_query():
    schema = next(t for t in agent.TOOLS if t["name"] == "search_runs")
    assert schema["input_schema"]["required"] == ["query"]
    properties = schema["input_schema"]["properties"]
    for name in ("model_type", "dataset_id", "task_type", "experiment_id", "status", "k"):
        assert name in properties


def test_get_run_detail_requires_a_run_id():
    schema = next(t for t in agent.TOOLS if t["name"] == "get_run_detail")
    assert schema["input_schema"]["required"] == ["run_id"]


def test_every_tool_has_a_description():
    """The description is the model's only documentation of when to use a tool."""
    assert all(tool["description"].strip() for tool in agent.TOOLS)


def test_a_valid_search_call_passes():
    assert agent.validate_tool_call("search_runs", {"query": "ridge on the panel"}) is None


def test_a_missing_query_is_rejected():
    error = agent.validate_tool_call("search_runs", {})
    assert error is not None
    assert "query" in error


def test_an_unknown_tool_is_rejected():
    error = agent.validate_tool_call("drop_tables", {"query": "x"})
    assert error is not None
    assert "drop_tables" in error


def test_an_unknown_argument_is_rejected_by_name():
    """The error string goes back to the model as the tool result, so it has to
    say which argument was wrong — 'invalid arguments' gives it nothing to
    correct and it retries the same call."""
    error = agent.validate_tool_call("search_runs", {"query": "x", "modle_type": "ridge"})
    assert error is not None
    assert "modle_type" in error


def test_a_non_integer_k_is_rejected():
    error = agent.validate_tool_call("search_runs", {"query": "x", "k": "many"})
    assert error is not None
    assert "k" in error


def test_a_k_above_the_ceiling_is_rejected_rather_than_clamped():
    """Every returned source's snippet lands in the model's context, and stage 2
    over-fetches k * chunk_overfetch chunks to produce them, so an unbounded k is
    a way for one tool call to blow the context window. Rejected, not clamped:
    answering a k of 500 with 25 sources tells the model the history holds 25."""
    error = agent.validate_tool_call("search_runs", {"query": "x", "k": 500})
    assert error is not None
    assert str(settings.agent_max_k) in error


def test_the_k_ceiling_is_inclusive():
    assert (
        agent.validate_tool_call("search_runs", {"query": "x", "k": settings.agent_max_k}) is None
    )


def test_the_documented_k_range_matches_what_validation_enforces():
    """The description is the model's only documentation of the bound. If it
    drifts, the model asks for a k that is rejected and has no way to know why."""
    schema = next(t for t in agent.TOOLS if t["name"] == "search_runs")
    description = schema["input_schema"]["properties"]["k"]["description"]
    assert str(settings.retrieval_top_k) in description
    assert str(settings.agent_max_k) in description


def test_every_schema_type_has_a_validator_entry():
    """validate_tool_call promises never to raise, but it looked its expected
    Python type up with `_TYPES[...]`. A schema property typed "number" would
    therefore KeyError out of the one function whose job is turning bad input
    into a message the model can act on — a 500 that loses the conversation.
    Importing app.agent now fails instead; this pins that the guard is honest."""
    used = {
        prop["type"] for tool in agent.TOOLS for prop in tool["input_schema"]["properties"].values()
    }
    assert used <= set(agent._TYPES)


def test_validation_returns_a_string_and_never_raises():
    """A raised exception ends the turn with a 500. A returned string goes back
    as the tool result and the model corrects itself on the next turn."""
    for args in ({}, {"query": 5}, {"query": "x", "k": -1}, None):
        result = agent.validate_tool_call("search_runs", args if args is not None else {})
        assert result is None or isinstance(result, str)


def test_the_system_prompt_demands_citations():
    prompt = agent.load_system_prompt().lower()
    assert "cite" in prompt or "citation" in prompt


def test_the_system_prompt_covers_the_missing_cv_std_case():
    """The band is absent on runs logged before 3.0. Without this instruction the
    model reports a difference as significant because nothing said it could not."""
    prompt = agent.load_system_prompt().lower()
    assert "unquantified" in prompt


def test_the_system_prompt_covers_the_empty_retrieval_case():
    """Before `make embed` has run, retrieval returns nothing. The model must say
    so rather than answer from its own priors about ridge regression."""
    prompt = agent.load_system_prompt().lower()
    assert "no reviewed history" in prompt
