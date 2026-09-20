"""Analyst/judge call primitives for the quality-gated LLM loop (issue #9).

This module no longer owns any orchestration — `app.loop.run_loop()` does. It
provides the injectable, testable building blocks the loop composes: one
Anthropic call that picks/adds chart tools and writes an interpretation
(`analyst_call`), one that scores an attempt against the rendered charts/stats
(`judge_call`), the content-block helpers they share (`image_block`,
`stats_block`), and the system-prompt/profile-assembly/cost-estimation helpers
used to build each call's context."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import settings
from app.tools import TOOL_DEFS

_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
_SYSTEM_PROMPT_PATH = _PROMPTS_DIR / "system.md"
_USER_PROMPT_PATH = _PROMPTS_DIR / "user_prompt.md"

# Approx per-million-token USD prices, keyed by model id prefix. Used only for
# bookkeeping (chat_messages.cost_usd); not a billing source of truth.
_PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


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
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == "submit_verdict"
        ):
            verdict = dict(block.input)
            break
    if verdict is None or "score" not in verdict:
        return JudgeResult(score=None, model=model, latency_ms=latency_ms)

    # A present verdict may still be malformed (non-int score, missing usage, etc.);
    # treat any coercion failure as a malformed verdict → score=None, never raise.
    try:
        raw_gaps = verdict.get("gaps", [])
        # `gaps` isn't in the tool's `required` list, and the model sometimes
        # writes a plain string (e.g. "No further gaps.") instead of an array.
        # str is iterable, so a bare list(raw_gaps) would silently split it into
        # one entry per character — coerce explicitly instead.
        if isinstance(raw_gaps, str):
            gaps = [raw_gaps] if raw_gaps.strip() else []
        else:
            gaps = [str(g) for g in raw_gaps]
        return JudgeResult(
            score=int(verdict["score"]),
            meets_bar=bool(verdict.get("meets_bar", False)),
            feedback=str(verdict.get("feedback", "")),
            gaps=gaps,
            tokens_in=int(response.usage.input_tokens),
            tokens_out=int(response.usage.output_tokens),
            latency_ms=latency_ms,
            model=model,
        )
    except (ValueError, TypeError):
        return JudgeResult(score=None, model=model, latency_ms=latency_ms)


def _system_prompt() -> str:
    """System instructions (design D2, issue #8): the persona/scope/tone/guardrails
    prompt with the per-question user prompt appended into one system block."""
    system = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").rstrip()
    user = _USER_PROMPT_PATH.read_text(encoding="utf-8").strip()
    return f"{system}\n\n{user}"


def _estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    in_price, out_price = _PRICES.get(model, (0.0, 0.0))
    return (tokens_in / 1_000_000) * in_price + (tokens_out / 1_000_000) * out_price


def _estimate_tokens(payload: Any) -> int:
    return len(json.dumps(payload, default=str)) // 4


def _assemble_dataset_profiles(datasets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Label each attached dataset's stored profile with its id/name for the
    prompt. If the combined payload exceeds the per-dataset token budget scaled
    by dataset count, drop sample_rows from every profile first — the same
    cheapest-cut priority as the single-dataset degrade in profile_dataframe()."""
    profiles = [d["profile"] for d in datasets]
    budget = settings.profile_token_budget * max(len(datasets), 1)
    if _estimate_tokens(profiles) > budget:
        profiles = [{**p, "sample_rows": []} for p in profiles]
    return [
        {"dataset_id": d["id"], "name": d["name"], "profile": profile}
        for d, profile in zip(datasets, profiles, strict=True)
    ]
