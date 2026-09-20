import json
from types import SimpleNamespace

from app.llm import AnalystResult, JudgeResult, analyst_call, image_block, judge_call, stats_block


class _FakeMessages:
    def __init__(self, response):
        self._response = response
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._response


class _FakeClient:
    def __init__(self, response):
        self.messages = _FakeMessages(response)


def _analyst_response(text, tool_calls, tin=100, tout=30):
    content = [SimpleNamespace(type="text", text=text)]
    for call in tool_calls:
        content.append(SimpleNamespace(type="tool_use", name=call["name"], input=call["args"]))
    return SimpleNamespace(
        content=content, usage=SimpleNamespace(input_tokens=tin, output_tokens=tout)
    )


def _judge_response(score, meets_bar=False, feedback="ok", gaps=None, tin=50, tout=10):
    verdict = {
        "score": score,
        "meets_bar": meets_bar,
        "feedback": feedback,
        "gaps": gaps or [],
    }
    content = [SimpleNamespace(type="tool_use", name="submit_verdict", input=verdict)]
    return SimpleNamespace(
        content=content, usage=SimpleNamespace(input_tokens=tin, output_tokens=tout)
    )


def test_image_block_shape() -> None:
    block = image_block("QUJD")
    assert block["type"] == "image"
    assert block["source"] == {"type": "base64", "media_type": "image/png", "data": "QUJD"}


def test_stats_block_is_json_text() -> None:
    block = stats_block({"mean": 5})
    assert block["type"] == "text"
    assert json.loads(block["text"].split("Statistics: ", 1)[1]) == {"mean": 5}


def test_analyst_call_parses_text_and_tool_calls() -> None:
    resp = _analyst_response("Looks linear.", [{"name": "histogram", "args": {"column": "age"}}])
    client = _FakeClient(resp)
    result = analyst_call(client, system=[{"type": "text", "text": "sys"}], messages=[])
    assert isinstance(result, AnalystResult)
    assert result.text == "Looks linear."
    assert result.tool_calls == [{"name": "histogram", "args": {"column": "age"}}]
    assert result.tokens_in == 100
    assert result.tokens_out == 30
    # analyst passes the chart tools
    assert client.messages.last_kwargs["tools"]


def test_judge_call_parses_verdict() -> None:
    client = _FakeClient(_judge_response(85, meets_bar=True, gaps=["plot income"]))
    result = judge_call(client, "q", "interp", charts=["QUJD"], stats=[{"mean": 5}])
    assert isinstance(result, JudgeResult)
    assert result.score == 85
    assert result.meets_bar is True
    assert result.gaps == ["plot income"]
    assert result.tokens_in == 50


def test_judge_call_forces_the_tool() -> None:
    client = _FakeClient(_judge_response(70))
    judge_call(client, "q", "interp", charts=[], stats=[])
    kwargs = client.messages.last_kwargs
    assert any(t["name"] == "submit_verdict" for t in kwargs["tools"])
    assert kwargs["tool_choice"] == {"type": "tool", "name": "submit_verdict"}


def test_judge_call_survives_client_error() -> None:
    class _Boom:
        class messages:
            @staticmethod
            def create(**kwargs):
                raise RuntimeError("api down")

    result = judge_call(_Boom(), "q", "interp", charts=[], stats=[])
    assert result.score is None
    assert result.meets_bar is False


def test_judge_call_survives_missing_verdict_block() -> None:
    # Response has no submit_verdict tool_use block at all (e.g. a stray text
    # block instead) — must not raise, just report score=None.
    response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="oops")],
        usage=SimpleNamespace(input_tokens=5, output_tokens=1),
    )
    client = _FakeClient(response)
    result = judge_call(client, "q", "interp", charts=[], stats=[])
    assert result.score is None
    assert result.meets_bar is False


def test_judge_call_coerces_string_gaps_to_single_item_list() -> None:
    # The tool schema declares `gaps` as an array of strings, but it's not in
    # `required` — the model sometimes writes a plain string instead (e.g. "No
    # further gaps." on a high-scoring final pass). `list("No further gaps.")`
    # would split that into one <li> per character, rendering as a very
    # narrow, very deep list in the trace UI. A string must become a single
    # one-item list, not be iterated character-by-character.
    client = _FakeClient(_judge_response(95, meets_bar=True, gaps="No further gaps."))
    result = judge_call(client, "q", "interp", charts=[], stats=[])
    assert result.gaps == ["No further gaps."]


def test_judge_call_treats_blank_string_gaps_as_empty() -> None:
    # Built directly (not via _judge_response, whose `gaps or []` default
    # would swallow "" before it ever reaches judge_call).
    verdict = {"score": 95, "meets_bar": True, "feedback": "ok", "gaps": ""}
    response = SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", name="submit_verdict", input=verdict)],
        usage=SimpleNamespace(input_tokens=50, output_tokens=10),
    )
    client = _FakeClient(response)
    result = judge_call(client, "q", "interp", charts=[], stats=[])
    assert result.gaps == []


def test_judge_call_survives_malformed_score() -> None:
    # submit_verdict block is present but score is not int-coercible — must be
    # treated as a malformed verdict (score=None), not raise.
    client = _FakeClient(_judge_response("bad"))
    result = judge_call(client, "q", "interp", charts=[], stats=[])
    assert result.score is None
    assert result.meets_bar is False
