# LLM Loop (issue #9) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-pass LLM orchestrator with a judge-gated agent loop that renders charts, feeds them back to Claude as images + stats, and iterates until a separate judge model rates the analysis good enough (or a pass cap is hit).

**Architecture:** A new `app/loop.py` owns orchestration. Per pass it (1) calls an **analyst** (existing chart tools), (2) validates + executes the new tool calls into `(png, stats)`, (3) calls a **judge** that scores the interpretation against the rendered charts, then loops with the judge's feedback until score ≥ threshold or the pass cap. `app/llm.py` shrinks to two injectable call helpers (`analyst_call`, `judge_call`). The chat route delegates chart execution to the loop and persists the best-scoring pass plus new `pass_count`/`judge_score` columns.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, Anthropic Python SDK (vision-capable Opus 4.8), pandas + matplotlib (Agg), pytest against SQLite.

## Global Constraints

- Python **3.12**; line length **100** (ruff + black); mypy **strict** on `backend/app`.
- Backend app code in `backend/app/` only; tests in `backend/tests/` only; imports absolute from `app`.
- Anthropic API key is **never** hardcoded — read from `settings.anthropic_api_key`.
- matplotlib: **Agg** backend, fresh `Figure` per call, never touch pyplot (already true in `app/analysis.py`; the loop only *calls* those functions).
- **Charts are never stored** — persisted `tool_calls` must reproduce the charts on history re-render via `app/charts.py`. Do not add chart/image columns.
- Tests run **offline** against SQLite with an injected fake Anthropic client — no API key, no network.
- Alembic is the schema authority on Postgres; SQLite tests use `create_all`. New columns must be **nullable** (no backfill).
- The public API response shape (`ChatMessageOut`) and the frontend are **unchanged**. `pass_count`/`judge_score` are persisted but NOT exposed.
- Design source of truth: `doc/project-1-llm-loop-design.md`.

---

### Task 1: Config settings for the loop

**Files:**
- Modify: `backend/app/config.py`
- Modify: `.env.example`
- Test: `backend/tests/test_config.py` (create)

**Interfaces:**
- Produces: `settings.llm_max_passes: int` (default 3), `settings.llm_quality_threshold: int` (default 80), `settings.judge_model: str` (default `""`, meaning "use `anthropic_model`").

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_config.py`:

```python
from app.config import Settings


def test_loop_settings_defaults() -> None:
    s = Settings()
    assert s.llm_max_passes == 3
    assert s.llm_quality_threshold == 80
    assert s.judge_model == ""


def test_loop_settings_overridable(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MAX_PASSES", "5")
    monkeypatch.setenv("LLM_QUALITY_THRESHOLD", "90")
    monkeypatch.setenv("JUDGE_MODEL", "claude-haiku-4-5")
    s = Settings()
    assert s.llm_max_passes == 5
    assert s.llm_quality_threshold == 90
    assert s.judge_model == "claude-haiku-4-5"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest backend/tests/test_config.py -v`
Expected: FAIL with `AttributeError`/assertion — `llm_max_passes` not defined on `Settings`.

- [ ] **Step 3: Add the settings**

In `backend/app/config.py`, after the `anthropic_max_tokens` line (before `settings = Settings()`), add:

```python
    # LLM loop (issue #9). A turn runs up to llm_max_passes analyst passes; a
    # separate judge scores each 0-100 and the loop stops at >= threshold or the
    # cap, returning the best-scoring pass. judge_model="" reuses anthropic_model.
    llm_max_passes: int = 3
    llm_quality_threshold: int = 80
    judge_model: str = ""
```

- [ ] **Step 4: Document in `.env.example`**

Append to `.env.example`:

```
# LLM loop (issue #9)
LLM_MAX_PASSES=3
LLM_QUALITY_THRESHOLD=80
# JUDGE_MODEL="" reuses ANTHROPIC_MODEL for the judge call
JUDGE_MODEL=
```

- [ ] **Step 5: Run test to verify it passes**

Run: `poetry run pytest backend/tests/test_config.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py .env.example backend/tests/test_config.py
git commit -m "feat(config): add LLM loop settings (issue #9)"
```

---

### Task 2: Loop metadata columns + migration

**Files:**
- Modify: `backend/app/models.py:94-113` (`ChatMessage`)
- Create: `backend/alembic/versions/9f3c1a7d2e40_add_loop_metadata_to_chat_messages.py`
- Test: `backend/tests/test_models.py` (add one test)

**Interfaces:**
- Produces: `ChatMessage.pass_count: int | None`, `ChatMessage.judge_score: int | None` (both nullable, default NULL).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_models.py`:

```python
def test_chat_message_has_loop_metadata_columns(db_session) -> None:
    from app.models import Chat, ChatMessage

    chat = Chat()
    db_session.add(chat)
    db_session.flush()
    msg = ChatMessage(
        chat_id=chat.id, role="assistant", content="ok", pass_count=3, judge_score=85
    )
    db_session.add(msg)
    db_session.flush()
    fetched = db_session.get(ChatMessage, msg.id)
    assert fetched.pass_count == 3
    assert fetched.judge_score == 85
```

> If `test_models.py` has no `db_session` fixture, use the same session-construction pattern already in that file (match its existing tests). The assertion content — `pass_count`/`judge_score` round-tripping — is what matters.

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest backend/tests/test_models.py -v -k loop_metadata`
Expected: FAIL with `TypeError: 'pass_count' is an invalid keyword argument for ChatMessage`.

- [ ] **Step 3: Add the columns to the model**

In `backend/app/models.py`, inside `ChatMessage`, after the `latency_ms` line add:

```python
    # LLM loop (issue #9): how many analyst passes ran and the best judge score.
    # Nullable — pre-loop rows and (rare) judge-failure turns stay NULL.
    pass_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    judge_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest backend/tests/test_models.py -v -k loop_metadata`
Expected: PASS (SQLite tests build the schema via `create_all`, so the columns appear automatically).

- [ ] **Step 5: Hand-write the Alembic migration (for Postgres)**

First confirm the current head:

Run: `poetry run alembic -c backend/alembic.ini heads` (or inspect `backend/alembic/versions/`).
Expected head: `f280d48505b3` (initial schema). If it differs, use the actual head as `down_revision` below.

Create `backend/alembic/versions/9f3c1a7d2e40_add_loop_metadata_to_chat_messages.py`:

```python
"""add loop metadata to chat_messages (issue #9)

Revision ID: 9f3c1a7d2e40
Revises: f280d48505b3
Create Date: 2026-07-29

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "9f3c1a7d2e40"
down_revision = "f280d48505b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_messages", sa.Column("pass_count", sa.Integer(), nullable=True), schema="app"
    )
    op.add_column(
        "chat_messages", sa.Column("judge_score", sa.Integer(), nullable=True), schema="app"
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "judge_score", schema="app")
    op.drop_column("chat_messages", "pass_count", schema="app")
```

- [ ] **Step 6: Sanity-check the migration imports**

Run: `poetry run python -c "import importlib.util, glob; f=glob.glob('backend/alembic/versions/*loop_metadata*.py')[0]; spec=importlib.util.spec_from_file_location('m', f); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print(m.revision, m.down_revision)"`
Expected: prints `9f3c1a7d2e40 f280d48505b3`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/ backend/tests/test_models.py
git commit -m "feat(db): add pass_count/judge_score to chat_messages (issue #9)"
```

---

### Task 3: Prompts — analyst edit + judge prompt

**Files:**
- Modify: `prompts/system.md`
- Create: `prompts/judge.md`
- Test: `backend/tests/test_prompts.py` (create)

**Interfaces:**
- Produces: `prompts/judge.md` file readable by `judge_call` in Task 5.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_prompts.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest backend/tests/test_prompts.py -v`
Expected: FAIL — `system.md` still contains "single pass"; `judge.md` does not exist.

- [ ] **Step 3: Edit `prompts/system.md`**

Replace the final line `Work in a single pass: choose your tools and write your interpretation together.` with:

```
You work in a loop: you choose tools and write an interpretation, your charts are
rendered and shown back to you as images with their computed statistics, and a
reviewer may ask you to revise the prose or add charts. Ground every statement in
what the rendered charts and statistics actually show.
```

Then fix the stale single-dataset wording in the "Role & objective" section: change `the single CSV dataset they have uploaded` to `the CSV dataset(s) they have uploaded` (the app is multi-dataset since issue #6).

- [ ] **Step 4: Create `prompts/judge.md`**

```markdown
# Role

You are a strict reviewer of a data-analysis assistant's answer. You are shown the
user's question, the assistant's written interpretation, and the charts it produced
(as images) together with each chart's computed statistics.

# Task

Score the answer from 0 to 100 on these criteria, weighted roughly equally:

1. **Grounded** — every claim is traceable to the shown statistics or visuals; no
   invented numbers, columns, or trends. Hallucinated specifics should score low.
2. **Answers the question** — the interpretation directly addresses what the user
   asked, not a tangent.
3. **Charts appropriate & sufficient** — the right tool(s) for the question, and
   nothing important left unplotted (e.g. a distribution the question implies).
4. **Concise & well-structured** — leads with the key insight; not padded.

# Output

Call the `submit_verdict` tool exactly once. Set `meets_bar` to true only if the
answer is genuinely good enough to show the user as-is. In `gaps`, list concrete,
actionable improvements the assistant can make next (e.g. "distribution of `income`
unexamined — add a histogram of `income`"). Keep `feedback` to one or two sentences.
```

- [ ] **Step 5: Run test to verify it passes**

Run: `poetry run pytest backend/tests/test_prompts.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add prompts/system.md prompts/judge.md backend/tests/test_prompts.py
git commit -m "feat(prompts): loop-aware system prompt + judge rubric (issue #9)"
```

---

### Task 4: `analyst_call` + content-block helpers in `llm.py`

**Files:**
- Modify: `backend/app/llm.py`
- Test: `backend/tests/test_llm.py` (rewrite — see note)

**Interfaces:**
- Consumes: `settings.anthropic_model`, `TOOL_DEFS`, existing `_system_prompt`, `_assemble_dataset_profiles`, `_estimate_cost`.
- Produces:
  - `image_block(png_b64: str) -> dict` → `{"type":"image","source":{"type":"base64","media_type":"image/png","data": png_b64}}`
  - `stats_block(stat: dict) -> dict` → `{"type":"text","text": "Statistics: " + json.dumps(stat)}`
  - `@dataclass AnalystResult(text: str, tool_calls: list[dict], tokens_in: int, tokens_out: int, latency_ms: int, model: str)` where each tool call is `{"name": str, "args": dict}`.
  - `analyst_call(client, system: list[dict], messages: list[dict]) -> AnalystResult` — one Anthropic call with `tools=TOOL_DEFS`; parses text + `tool_use` blocks exactly like the old `run_pass`.

**Note:** The old `test_llm.py` tests `run_pass`, which is being removed in Task 6. This task rewrites `test_llm.py` to cover the new helpers. It's acceptable for `run_pass` to still exist after this task (removed in Task 6); just stop testing it here.

- [ ] **Step 1: Write the failing test**

Replace `backend/tests/test_llm.py` with:

```python
import json
from types import SimpleNamespace

from app.llm import AnalystResult, analyst_call, image_block, stats_block


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
        content.append(
            SimpleNamespace(type="tool_use", name=call["name"], input=call["args"])
        )
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest backend/tests/test_llm.py -v`
Expected: FAIL with `ImportError: cannot import name 'AnalystResult'`.

- [ ] **Step 3: Implement the helpers**

In `backend/app/llm.py`, add near the top imports (keep existing ones) and after the existing `LLMResult` dataclass add:

```python
@dataclass
class AnalystResult:
    text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    model: str = ""


def image_block(png_b64: str) -> dict[str, Any]:
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": png_b64},
    }


def stats_block(stat: dict[str, Any]) -> dict[str, Any]:
    return {"type": "text", "text": "Statistics: " + json.dumps(stat, default=str)}


def analyst_call(
    client: Any, system: list[dict[str, Any]], messages: list[dict[str, Any]]
) -> AnalystResult:
    """One analyst pass: pick/add chart tools and write an interpretation."""
    start = time.monotonic()
    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=settings.anthropic_max_tokens,
        system=system,
        tools=TOOL_DEFS,
        messages=messages,
    )
    latency_ms = int((time.monotonic() - start) * 1000)

    tool_calls: list[dict[str, Any]] = []
    text_parts: list[str] = []
    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            tool_calls.append({"name": block.name, "args": dict(block.input)})
        elif getattr(block, "type", None) == "text":
            text_parts.append(block.text)

    return AnalystResult(
        text="".join(text_parts).strip(),
        tool_calls=tool_calls,
        tokens_in=int(response.usage.input_tokens),
        tokens_out=int(response.usage.output_tokens),
        latency_ms=latency_ms,
        model=settings.anthropic_model,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest backend/tests/test_llm.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/llm.py backend/tests/test_llm.py
git commit -m "feat(llm): analyst_call + image/stats content blocks (issue #9)"
```

---

### Task 5: `judge_call` + `submit_verdict` tool in `llm.py`

**Files:**
- Modify: `backend/app/llm.py`
- Test: `backend/tests/test_llm.py` (add cases)

**Interfaces:**
- Consumes: `settings.judge_model or settings.anthropic_model`, `image_block`, `stats_block` (Task 4), `_system_prompt` dir helpers.
- Produces:
  - `SUBMIT_VERDICT_TOOL: dict` — a single tool def named `submit_verdict` with input schema `{score:int, meets_bar:bool, feedback:str, gaps:list[str]}` (all required except gaps).
  - `@dataclass JudgeResult(score: int | None, meets_bar: bool, feedback: str, gaps: list[str], tokens_in: int, tokens_out: int, latency_ms: int, model: str)`.
  - `judge_call(client, question: str, interpretation: str, charts: list[str], stats: list[dict]) -> JudgeResult`. On any exception from the client or a missing/malformed verdict block, returns `JudgeResult(score=None, meets_bar=False, feedback="", gaps=[], ...)` (never raises).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_llm.py`:

```python
from app.llm import JudgeResult, judge_call


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest backend/tests/test_llm.py -v -k judge`
Expected: FAIL with `ImportError: cannot import name 'JudgeResult'`.

- [ ] **Step 3: Implement the judge**

In `backend/app/llm.py` add:

```python
SUBMIT_VERDICT_TOOL: dict[str, Any] = {
    "name": "submit_verdict",
    "description": "Submit your review score and feedback for the assistant's answer.",
    "input_schema": {
        "type": "object",
        "properties": {
            "score": {"type": "integer", "description": "Quality score from 0 to 100."},
            "meets_bar": {
                "type": "boolean",
                "description": "True only if good enough to show the user as-is.",
            },
            "feedback": {"type": "string", "description": "One or two sentences of critique."},
            "gaps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Concrete, actionable improvements for the next pass.",
            },
        },
        "required": ["score", "meets_bar", "feedback"],
    },
}

_JUDGE_PROMPT_PATH = _PROMPTS_DIR / "judge.md"


@dataclass
class JudgeResult:
    score: int | None
    meets_bar: bool = False
    feedback: str = ""
    gaps: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    model: str = ""


def _judge_model() -> str:
    return settings.judge_model or settings.anthropic_model


def judge_call(
    client: Any,
    question: str,
    interpretation: str,
    charts: list[str],
    stats: list[dict[str, Any]],
) -> JudgeResult:
    """Score one analyst attempt. Never raises — a failed/malformed call yields
    score=None so the loop can stop and return the best-so-far pass."""
    content: list[dict[str, Any]] = [
        {"type": "text", "text": f"User question:\n{question}"},
        {"type": "text", "text": f"Assistant interpretation:\n{interpretation}"},
    ]
    for png, stat in zip(charts, stats, strict=True):
        content.append(image_block(png))
        content.append(stats_block(stat))
    content.append({"type": "text", "text": "Review it now via submit_verdict."})

    model = _judge_model()
    start = time.monotonic()
    try:
        response = client.messages.create(
            model=model,
            max_tokens=settings.anthropic_max_tokens,
            system=_JUDGE_PROMPT_PATH.read_text(encoding="utf-8"),
            tools=[SUBMIT_VERDICT_TOOL],
            tool_choice={"type": "tool", "name": "submit_verdict"},
            messages=[{"role": "user", "content": content}],
        )
    except Exception:
        return JudgeResult(score=None, model=model)
    latency_ms = int((time.monotonic() - start) * 1000)

    verdict: dict[str, Any] | None = None
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "submit_verdict":
            verdict = dict(block.input)
            break
    if verdict is None or "score" not in verdict:
        return JudgeResult(score=None, model=model, latency_ms=latency_ms)

    return JudgeResult(
        score=int(verdict["score"]),
        meets_bar=bool(verdict.get("meets_bar", False)),
        feedback=str(verdict.get("feedback", "")),
        gaps=list(verdict.get("gaps", [])),
        tokens_in=int(response.usage.input_tokens),
        tokens_out=int(response.usage.output_tokens),
        latency_ms=latency_ms,
        model=model,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest backend/tests/test_llm.py -v -k judge`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/llm.py backend/tests/test_llm.py
git commit -m "feat(llm): judge_call + submit_verdict verdict parsing (issue #9)"
```

---

### Task 6: `run_loop` orchestrator in `app/loop.py`

**Files:**
- Create: `backend/app/loop.py`
- Modify: `backend/app/llm.py` (remove `run_pass` and `LLMResult`; keep helpers)
- Test: `backend/tests/test_loop.py` (create)

**Interfaces:**
- Consumes: `analyst_call`, `judge_call`, `image_block`, `stats_block`, `AnalystResult`, `JudgeResult`, `_system_prompt`, `_assemble_dataset_profiles`, `_estimate_cost` (from `app.llm`); `validate_tool_call` (from `app.tools`); `_DISPATCH` (from `app.charts`); `settings`.
- Produces:
  - `@dataclass LoopResult(interpretation: str, tool_calls: list[dict], charts: list[str], stats: list[dict], errors: list[str], tokens_in: int, tokens_out: int, cost_usd: float, latency_ms: int, pass_count: int, judge_score: int | None)`.
  - `run_loop(datasets: list[dict], dfs: dict[str, DataFrame], prior_messages: list[dict], question: str, *, client=None) -> LoopResult`. `datasets` items are `{"id","name","profile"}`; `dfs` maps dataset_id → DataFrame. `tool_calls`/`charts`/`stats`/`errors` come from the best-scoring pass; token/cost/latency are **summed across every analyst + judge call**; `pass_count` is passes actually run; `judge_score` is the best pass's score (may be `None`).

Semantics to implement exactly:
- Cumulative charts across passes, deduped by `json.dumps({"name","args"}, sort_keys=True)`.
- Stop when `verdict.score >= settings.llm_quality_threshold`, or after `settings.llm_max_passes` passes.
- Early stall-out: after a pass that added **no** new charts **and** whose score did **not** improve over the previous pass, stop.
- Best pass = highest non-None score; if no pass ever scored, best = last pass (and `judge_score=None`).
- Judge returns `score=None` (error) → treat as terminal: stop after this pass, return best-so-far.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_loop.py`:

```python
import json
from types import SimpleNamespace

import pandas as pd

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
    client = _ScriptedClient([_analyst("v1", [HIST]), _judge(70), _analyst("v2", [SCAT]), bad_judge])
    result = run_loop(DATASETS, _dfs(), [], "explore", client=client)
    assert result.pass_count == 2
    assert result.judge_score == 70  # pass 2's judge failed -> best is pass 1
    assert result.interpretation == "v1"


def test_invalid_tool_call_is_skipped(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_max_passes", 1)
    bad = {"name": "histogram", "args": {"dataset_id": "d1", "column": "missing"}}
    client = _ScriptedClient([_analyst("v1", [bad]), _judge(50)])
    result = run_loop(DATASETS, _dfs(), [], "explore", client=client)
    assert result.charts == []
    assert len(result.errors) == 1


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest backend/tests/test_loop.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.loop'`.

- [ ] **Step 3: Implement `run_loop`**

Create `backend/app/loop.py`:

```python
"""Quality-gated LLM loop (issue #9). Replaces the single-pass orchestrator:
an analyst picks/adds chart tools and writes an interpretation, the charts are
rendered and fed back as images + stats, and a judge scores each attempt. The
loop iterates until the judge clears the threshold or the pass cap, returning the
best-scoring pass. Charts are executed here (the judge needs them rendered)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.charts import _DISPATCH
from app.config import settings
from app.llm import (
    JudgeResult,
    _assemble_dataset_profiles,
    _estimate_cost,
    _system_prompt,
    analyst_call,
    image_block,
    judge_call,
    stats_block,
)
from app.tools import validate_tool_call


@dataclass
class LoopResult:
    interpretation: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    charts: list[str] = field(default_factory=list)
    stats: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    pass_count: int = 0
    judge_score: int | None = None


@dataclass
class _Snapshot:
    interpretation: str
    tool_calls: list[dict[str, Any]]
    charts: list[str]
    stats: list[dict[str, Any]]
    errors: list[str]
    score: int | None


def _call_key(call: dict[str, Any]) -> str:
    return json.dumps({"name": call["name"], "args": call["args"]}, sort_keys=True)


def _default_client() -> Any:
    import anthropic

    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _build_system(datasets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labeled = _assemble_dataset_profiles(datasets)
    system = [{"type": "text", "text": _system_prompt()}]
    for entry in labeled:
        header = f"Dataset {entry['dataset_id']} ({entry['name']}) profile:\n"
        system.append(
            {"type": "text", "text": header + json.dumps(entry["profile"], default=str)}
        )
    return system


def _feedback_turn(snap: _Snapshot, verdict: JudgeResult) -> list[dict[str, Any]]:
    """Represent the prior pass as a text assistant turn plus a user turn that
    shows the rendered charts (images + stats), any errors, and the judge's
    critique — so the next analyst pass can revise or add charts."""
    content: list[dict[str, Any]] = []
    for png, stat in zip(snap.charts, snap.stats, strict=True):
        content.append(image_block(png))
        content.append(stats_block(stat))
    if snap.errors:
        content.append({"type": "text", "text": "Errors: " + "; ".join(snap.errors)})
    content.append(
        {
            "type": "text",
            "text": (
                f"A reviewer scored this {verdict.score}/100. Feedback: {verdict.feedback} "
                f"Gaps: {verdict.gaps}. Revise: add charts if useful and improve the "
                "interpretation to address the gaps."
            ),
        }
    )
    return [
        {"role": "assistant", "content": snap.interpretation or "(no interpretation)"},
        {"role": "user", "content": content},
    ]


def run_loop(
    datasets: list[dict[str, Any]],
    dfs: dict[str, pd.DataFrame],
    prior_messages: list[dict[str, Any]],
    question: str,
    *,
    client: Any | None = None,
) -> LoopResult:
    client = client or _default_client()
    profiles = {d["id"]: d["profile"] for d in datasets}
    system = _build_system(datasets)
    messages: list[dict[str, Any]] = [
        {"role": m["role"], "content": m["content"]} for m in prior_messages
    ]
    messages.append({"role": "user", "content": question})

    seen_keys: set[str] = set()
    charts: list[str] = []
    stats: list[dict[str, Any]] = []
    executed: list[dict[str, Any]] = []
    errors: list[str] = []

    tokens_in = tokens_out = latency_ms = 0
    cost_usd = 0.0
    best: _Snapshot | None = None
    prev_score: int | None = None
    passes = 0

    for _ in range(max(1, settings.llm_max_passes)):
        analyst = analyst_call(client, system, messages)
        passes += 1
        tokens_in += analyst.tokens_in
        tokens_out += analyst.tokens_out
        latency_ms += analyst.latency_ms
        cost_usd += _estimate_cost(analyst.model, analyst.tokens_in, analyst.tokens_out)

        added = 0
        for call in analyst.tool_calls:
            err = validate_tool_call(call["name"], call["args"], profiles)
            if err is not None:
                errors.append(err)
                continue
            key = _call_key(call)
            if key in seen_keys:
                continue
            png, stat = _DISPATCH[call["name"]](dfs, call["args"])
            seen_keys.add(key)
            charts.append(png)
            stats.append(stat)
            executed.append(call)
            added += 1

        verdict = judge_call(client, question, analyst.text, charts, stats)
        tokens_in += verdict.tokens_in
        tokens_out += verdict.tokens_out
        latency_ms += verdict.latency_ms
        cost_usd += _estimate_cost(verdict.model, verdict.tokens_in, verdict.tokens_out)

        snap = _Snapshot(
            interpretation=analyst.text,
            tool_calls=list(executed),
            charts=list(charts),
            stats=list(stats),
            errors=list(errors),
            score=verdict.score,
        )
        if best is None or (snap.score is not None and (best.score is None or snap.score > best.score)):
            best = snap

        # Stop conditions.
        if verdict.score is None:  # judge failed -> terminal
            break
        if verdict.score >= settings.llm_quality_threshold:
            break
        improved = prev_score is None or verdict.score > prev_score
        if added == 0 and not improved:
            break
        prev_score = verdict.score
        messages.extend(_feedback_turn(snap, verdict))

    assert best is not None
    return LoopResult(
        interpretation=best.interpretation,
        tool_calls=best.tool_calls,
        charts=best.charts,
        stats=best.stats,
        errors=best.errors,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        pass_count=passes,
        judge_score=best.score,
    )
```

- [ ] **Step 4: Remove the dead single-pass code**

In `backend/app/llm.py`, delete the `LLMResult` dataclass, the `_build_messages` function, and the `run_pass` function (the loop supersedes them). Keep `_system_prompt`, `_assemble_dataset_profiles`, `_estimate_tokens`, `_estimate_cost`, `_PRICES`, `_default_client` if still referenced — note `run_loop` has its own `_default_client`, so remove the one in `llm.py` only if nothing else imports it (grep first).

Run: `poetry run python -c "import ast,sys; ast.parse(open('backend/app/llm.py').read())"` then
`grep -rn "run_pass\|LLMResult\|_build_messages" backend/` — expected: no references outside comments/docs.

- [ ] **Step 5: Run tests to verify they pass**

Run: `poetry run pytest backend/tests/test_loop.py backend/tests/test_llm.py -v`
Expected: PASS (all loop cases + the Task 4/5 helper tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/loop.py backend/app/llm.py backend/tests/test_loop.py
git commit -m "feat(loop): judge-gated multi-pass orchestrator (issue #9)"
```

---

### Task 7: Wire the chat route to `run_loop`

**Files:**
- Modify: `backend/app/routes/chats.py:84-151` (`post_message`)
- Test: `backend/tests/test_chats.py` (update mock + add persistence assertions)

**Interfaces:**
- Consumes: `run_loop` + `LoopResult` from `app.loop`.
- The route builds `dfs` from each dataset's `data_csv`, calls `run_loop`, persists the assistant `ChatMessage` (now including `pass_count`/`judge_score` and summed telemetry), writes `Analysis` rows from `result.tool_calls`+`result.stats`, and returns `ChatMessageOut(content, charts, stats, errors)` — unchanged response shape.

- [ ] **Step 1: Update the route test mock and add assertions**

In `backend/tests/test_chats.py`, replace `_fake_llm` with a loop-level fake and add a persistence test. Change the import at top from `import app.routes.chats as chats_route` (keep it) and rewrite `_fake_llm`:

```python
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
```

Then add a new test:

```python
def test_chat_persists_loop_metadata(client, monkeypatch) -> None:
    dataset_id = _upload(client)
    args = {"dataset_id": dataset_id, "x": "age", "y": "score"}
    _fake_llm(monkeypatch, [{"name": "scatter", "args": args}], pass_count=2, judge_score=84)
    chat_id = client.post("/chats", json={"dataset_ids": [dataset_id]}).json()["id"]
    client.post(f"/chats/{chat_id}/messages", json={"question": "relate them"})

    from app.db import get_session
    from app.models import ChatMessage

    session = next(client.app.dependency_overrides[get_session]())
    assistant = (
        session.query(ChatMessage).filter(ChatMessage.role == "assistant").one()
    )
    assert assistant.pass_count == 2
    assert assistant.judge_score == 84
    assert assistant.tokens_in == 150
```

The existing tests (`test_chat_runs_and_persists`, `test_chat_invalid_tool_arg_is_graceful`, `test_compare_across_two_datasets`, etc.) keep their assertions and now exercise `run_loop` through the rewritten `_fake_llm`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest backend/tests/test_chats.py -v`
Expected: FAIL — `chats_route` has no attribute `run_loop` (route still imports/uses `run_pass`).

- [ ] **Step 3: Rewrite `post_message` in `backend/app/routes/chats.py`**

Change the import line `from app.llm import run_pass` to `from app.loop import run_loop`. Remove now-unused imports `from app.charts import _DISPATCH, render_message_analysis` → keep only `render_message_analysis` (still used by `get_chat`); remove `from app.tools import validate_tool_call` (validation now lives in the loop). Replace the body of `post_message` (from the `run_pass` call through the `return`) with:

```python
    result = run_loop(
        [{"id": d.id, "name": d.name, "profile": d.profile_json} for d in datasets],
        {d.id: load_csv(d.data_csv) for d in datasets},
        prior,
        body.question,
    )

    assistant = ChatMessage(
        chat_id=chat.id,
        role="assistant",
        content=result.interpretation,
        tool_calls=result.tool_calls,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        cost_usd=result.cost_usd,
        latency_ms=result.latency_ms,
        pass_count=result.pass_count,
        judge_score=result.judge_score,
    )
    session.add(assistant)
    session.flush()

    for call, stat in zip(result.tool_calls, result.stats, strict=True):
        session.add(
            Analysis(
                message_id=assistant.id,
                chart_type=call["name"],
                params=call["args"],
                result_stats=stat,
            )
        )

    session.commit()
    return ChatMessageOut(
        id=assistant.id,
        role="assistant",
        content=result.interpretation,
        charts=result.charts,
        stats=result.stats,
        errors=result.errors,
    )
```

Delete the now-dead local variables from the old body (`profiles`, `dfs`, `charts`, `stats`, `errors`, `executed_calls`, and the per-call validate/execute loop). Ensure `load_csv` stays imported (used above and by `get_chat`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest backend/tests/test_chats.py -v`
Expected: PASS (all existing tests + `test_chat_persists_loop_metadata`).

- [ ] **Step 5: Full gate**

Run: `make check`
Expected: lint + format-check + mypy(strict) + full pytest all PASS. Fix any unused-import / type errors surfaced (e.g. remove leftover `Any` if now unused in the route).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/chats.py backend/tests/test_chats.py
git commit -m "feat(chats): drive the LLM loop from the message route (issue #9)"
```

---

### Task 8: Document sync (required before merge, per CLAUDE.md)

**Files:**
- Modify: `CLAUDE.md`
- Modify: `doc/project-1-csv-analysis-assistant-design.md`
- Modify: `README.md`
- Modify: `doc/plans/2026-07-29-project-1-llm-loop.md` (tick checkboxes as completed)

**Interfaces:** none (docs only).

- [x] **Step 1: Update `CLAUDE.md`**

- Rewrite the **Single-pass LLM (D2)** non-obvious-design bullet to describe the loop: analyst → render → judge (score 0–100) → iterate to threshold **80** or `llm_max_passes` **3**, return best pass; charts fed back as images + stats.
- In the code-layout block, replace the `llm.py` line (now `analyst_call`/`judge_call` helpers) and add `loop.py — run_loop() judge-gated orchestrator`.
- Note the two new `Settings` (`llm_max_passes`, `llm_quality_threshold`, `judge_model`) and the two new `chat_messages` columns (`pass_count`, `judge_score`; persisted, not exposed).
- Update the `make eval` paragraph: the golden set now grades the loop's final output (this *is* the D2 go/no-go resolution).

- [x] **Step 2: Update `doc/project-1-csv-analysis-assistant-design.md`**

Revise decision **D2** to record that single-pass was replaced by the judge-gated loop (reference `doc/project-1-llm-loop-design.md` and issue #9).

- [x] **Step 3: Update `README.md`**

In the feature list / quickstart, note that a chat turn may run multiple LLM passes (analyst + judge) and can therefore take longer; behavior is otherwise unchanged.

- [x] **Step 4: Verify no stale `run_pass` / single-pass references remain**

Run: `grep -rni "single pass\|run_pass" README.md CLAUDE.md doc/ backend/app/`
Expected: only the design/plan docs describing the *history* (e.g. "replaced single-pass"), no live references implying current behavior.

- [x] **Step 5: Commit**

```bash
git add CLAUDE.md README.md doc/
git commit -m "docs: sync CLAUDE/README/design for the LLM loop (issue #9)"
```

---

## Self-Review

**Spec coverage** (against `doc/project-1-llm-loop-design.md`):
- Control flow / `run_loop`, cumulative charts, return-best, stall-out, judge-error terminal → Task 6.
- Pass-2 input = images + stats → `image_block`/`stats_block` (Task 4), fed via `_feedback_turn` (loop) and judge message (Task 5).
- Separate judge LLM, score 0–100 + feedback → Task 5.
- Analyst may add charts and/or reword → Task 6 (new tool calls executed each pass).
- Bounds: max 3, threshold 80, config-driven → Task 1 + Task 6.
- Replace single-pass → `run_pass` removed in Task 6; route rewired in Task 7.
- Persist `pass_count`/`judge_score`, don't expose; sum telemetry → Task 2 (schema) + Task 6 (aggregation) + Task 7 (persist); `ChatMessageOut` unchanged.
- Prompts (system edit + judge.md) → Task 3.
- Config + `.env.example` → Task 1.
- Tests: threshold-met, cap→best, stall-out, judge-error, invalid-call, telemetry-sum → Task 6; route persistence → Task 7.
- `make eval` grades loop; doc sync → Task 8.

**Placeholder scan:** No "TBD"/"handle edge cases"/"write tests for the above" — every code + test step carries real content.

**Type consistency:** `AnalystResult`/`JudgeResult` (Task 4/5) consumed by `run_loop` (Task 6); `LoopResult` (Task 6) consumed by the route + its test (Task 7); `validate_tool_call(name, args, profiles)` and `_DISPATCH[name](dfs, args)` signatures match `app/tools.py` and `app/charts.py`; `(png, stat)` tuple contract matches `app/analysis.py`. Settings names (`llm_max_passes`, `llm_quality_threshold`, `judge_model`) are identical across Tasks 1, 5, 6.
