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
from app.tracing import span


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
    # Per-pass trace (issue #9 review) surfaced in the UI: one record per analyst/
    # judge pass in order. The assembled system prompt is deliberately NOT included
    # (it can leak guardrail language) — it never leaves the backend.
    trace: list[dict[str, Any]] = field(default_factory=list)


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
        system.append({"type": "text", "text": header + json.dumps(entry["profile"], default=str)})
    return system


def _revision_text(verdict: JudgeResult) -> str:
    """The judge's critique rephrased as the instruction fed into the next pass.
    Stored verbatim in the trace as that pass's `revision_instruction`."""
    return (
        f"A reviewer scored this {verdict.score}/100. Feedback: {verdict.feedback} "
        f"Gaps: {verdict.gaps}. Revise: add charts if useful and improve the "
        "interpretation to address the gaps."
    )


def _feedback_turn(snap: _Snapshot, revision: str) -> list[dict[str, Any]]:
    """Represent the prior pass as a text assistant turn plus a user turn that
    shows the rendered charts (images + stats), any errors, and the judge's
    critique — so the next analyst pass can revise or add charts."""
    content: list[dict[str, Any]] = []
    for png, stat in zip(snap.charts, snap.stats, strict=True):
        content.append(image_block(png))
        content.append(stats_block(stat))
    if snap.errors:
        content.append({"type": "text", "text": "Errors: " + "; ".join(snap.errors)})
    content.append({"type": "text", "text": revision})
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
    trace: list[dict[str, Any]] = []

    with span("llm.loop", max_passes=settings.llm_max_passes) as loop_span:
        for _ in range(max(1, settings.llm_max_passes)):
            # Counted before the call so the analyst and judge spans of one pass
            # carry the SAME pass_index, and the same number as the trace record's
            # `pass_no`. Incrementing between them numbers one pass twice.
            passes += 1
            with span("llm.analyst_pass", pass_index=passes) as analyst_span:
                analyst = analyst_call(client, system, messages)
                analyst_span.set_attribute("model", analyst.model)
                analyst_span.set_attribute("tokens_in", analyst.tokens_in)
                analyst_span.set_attribute("tokens_out", analyst.tokens_out)
                analyst_span.set_attribute("tool_calls", len(analyst.tool_calls))
            analyst_cost = _estimate_cost(analyst.model, analyst.tokens_in, analyst.tokens_out)
            tokens_in += analyst.tokens_in
            tokens_out += analyst.tokens_out
            latency_ms += analyst.latency_ms
            cost_usd += analyst_cost

            added = 0
            # `errors` accumulates across the whole loop, so the count before
            # this pass is what makes the span's number a per-pass one. Reading
            # len(errors) after the loop would report pass 1's failures again on
            # every later pass, beside a `charts` count that IS per-pass.
            errors_before = len(errors)
            with span("charts.render", tool_calls=len(analyst.tool_calls)) as charts_span:
                for call in analyst.tool_calls:
                    err = validate_tool_call(call["name"], call["args"], profiles)
                    if err is not None:
                        errors.append(err)
                        continue
                    key = _call_key(call)
                    if key in seen_keys:
                        continue
                    try:
                        png, stat = _DISPATCH[call["name"]](dfs, call["args"])
                    except (KeyError, ValueError) as exc:
                        errors.append(f"{call['name']}: {exc}")
                        continue
                    seen_keys.add(key)
                    charts.append(png)
                    stats.append(stat)
                    executed.append(call)
                    added += 1
                charts_span.set_attribute("charts", added)
                charts_span.set_attribute("errors", len(errors) - errors_before)
                charts_span.set_attribute("errors_total", len(errors))

            with span("llm.judge_pass", pass_index=passes) as judge_span:
                verdict = judge_call(client, question, analyst.text, charts, stats)
                judge_span.set_attribute("model", verdict.model)
                judge_span.set_attribute("tokens_in", verdict.tokens_in)
                judge_span.set_attribute("tokens_out", verdict.tokens_out)
                # Set only when there IS a score. A `-1` sentinel would be
                # averaged into any dashboard built on this attribute, and
                # span() already drops None-valued attributes precisely so
                # callers do not have to invent one. A judge that failed to
                # return a verdict is a different fact, recorded as one.
                if verdict.score is None:
                    judge_span.set_attribute("judge_failed", True)
                else:
                    judge_span.set_attribute("score", verdict.score)
            judge_cost = _estimate_cost(verdict.model, verdict.tokens_in, verdict.tokens_out)
            tokens_in += verdict.tokens_in
            tokens_out += verdict.tokens_out
            latency_ms += verdict.latency_ms
            cost_usd += judge_cost

            snap = _Snapshot(
                interpretation=analyst.text,
                tool_calls=list(executed),
                charts=list(charts),
                stats=list(stats),
                errors=list(errors),
                score=verdict.score,
            )
            if best is None or (
                snap.score is not None and (best.score is None or snap.score > best.score)
            ):
                best = snap

            # Record this pass's trace (revision_instruction filled in only if the
            # loop continues to another pass below).
            pass_record: dict[str, Any] = {
                "pass_no": passes,
                "analyst": {
                    "model": analyst.model,
                    "tokens_in": analyst.tokens_in,
                    "tokens_out": analyst.tokens_out,
                    "latency_ms": analyst.latency_ms,
                    "cost_usd": analyst_cost,
                    "interpretation": analyst.text,
                },
                "charts": list(charts),
                "stats": list(stats),
                "errors": list(errors),
                "judge": {
                    "model": verdict.model,
                    "tokens_in": verdict.tokens_in,
                    "tokens_out": verdict.tokens_out,
                    "latency_ms": verdict.latency_ms,
                    "cost_usd": judge_cost,
                    "score": verdict.score,
                    "feedback": verdict.feedback,
                    "gaps": list(verdict.gaps),
                },
                "revision_instruction": "",
            }
            trace.append(pass_record)

            # Stop conditions.
            if verdict.score is None:  # judge failed -> terminal
                break
            if verdict.score >= settings.llm_quality_threshold:
                break
            improved = prev_score is None or verdict.score > prev_score
            if added == 0 and not improved:
                break
            prev_score = verdict.score
            revision = _revision_text(verdict)
            pass_record["revision_instruction"] = revision
            messages.extend(_feedback_turn(snap, revision))
        loop_span.set_attribute("pass_count", passes)
        if best is not None and best.score is not None:
            loop_span.set_attribute("best_score", best.score)

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
        trace=trace,
    )
