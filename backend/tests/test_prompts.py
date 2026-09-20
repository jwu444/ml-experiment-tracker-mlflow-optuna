from pathlib import Path

PROMPTS = Path(__file__).resolve().parents[2] / "prompts"


def test_system_prompt_is_not_single_pass() -> None:
    text = Path(PROMPTS / "system.md").read_text(encoding="utf-8").lower()
    assert "single pass" not in text
    assert "single csv dataset" not in text


def test_judge_prompt_exists_and_mentions_score() -> None:
    text = Path(PROMPTS / "judge.md").read_text(encoding="utf-8").lower()
    assert "score" in text
    assert "submit_verdict" in text
