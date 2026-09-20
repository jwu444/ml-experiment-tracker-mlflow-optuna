"""The prompt is a source file with a contract, so its load-bearing rules are
pinned like any other. These assertions are deliberately about the RULES being
present, not about their wording — a reworded prompt that keeps the rules
should not fail."""

from pathlib import Path

PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "agent.md"


def test_the_prompt_names_all_three_tools():
    text = PROMPT.read_text()
    for tool in ("search_runs", "get_run_detail", "get_leaderboard"):
        assert tool in text


def test_a_recommendation_must_be_grounded_in_the_leaderboard():
    """The failure mode D47 exists to prevent: a fluent suggestion assembled
    from snippets, with no ordering behind it."""
    text = PROMPT.read_text().lower()
    assert "recommend" in text
    assert "get_leaderboard" in text


def test_the_prompt_still_forbids_an_unsourceable_margin():
    """Pre-existing rule. A recommendation rule is exactly the kind of addition
    that quietly overrides it — "suggest the next thing to try" invites stating
    a margin nothing measured."""
    text = PROMPT.read_text().lower()
    assert "within noise" in text or "cv_std" in text or "unquantified" in text
