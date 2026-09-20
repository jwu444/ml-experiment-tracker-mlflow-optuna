"""The retrieval agent: tool schemas, validation, and the loop.

Tool naming is D41. The tools are `search_runs`, `get_run_detail` and
`get_leaderboard` (the third added by D47) — never `search_experiments`, because
since D33 an "experiment" is an investigation containing many runs, so a tool by
the old name would make the model search for investigations when what it wants is
runs, and nothing in the transcript would look wrong.

D47 is the same rule applied to the third tool: it is named for the rows it
returns, not `recommend_next`, or the model treats its output as the
recommendation rather than as the evidence for one.

`prompts/agent.md` is part of this contract and has to be kept in step with
`TOOLS` — it went on describing two tools after the third landed, and a prompt
that undercounts the tools is a tool the model will not reach for.
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app import retrieval
from app.config import settings
from app.leaderboard import ExperimentNotFound, build_leaderboard
from app.llm import _estimate_cost
from app.schemas import LeaderboardOut
from app.tracing import span

_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "agent.md"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_runs",
        "description": (
            "Semantic search over reviewed write-ups about this project's training "
            "runs: approved run notes, EDA findings, and diagnostic interpretations. "
            "Supply the structured filters whenever the question names one — they are "
            "applied as database filters before the search runs. Returns snippets, not "
            "full records; follow up with get_run_detail for exact numbers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to look for, in natural language.",
                },
                "model_type": {
                    "type": "string",
                    "description": "Restrict to one model, e.g. 'ridge' or 'persistence'.",
                },
                "dataset_id": {
                    "type": "string",
                    "description": "Restrict to runs whose experiment used this dataset.",
                },
                "task_type": {
                    "type": "string",
                    "description": "'regression' or 'classification'.",
                },
                "experiment_id": {
                    "type": "string",
                    "description": "Restrict to one investigation.",
                },
                "status": {
                    "type": "string",
                    "description": "MLflow run status, e.g. 'FINISHED' or 'FAILED'.",
                },
                "k": {
                    "type": "integer",
                    "description": (
                        "How many sources to return. Defaults to "
                        f"{settings.retrieval_top_k}, maximum {settings.agent_max_k}."
                    ),
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_run_detail",
        "description": (
            "One run's full record: its parameters, its metrics with cross-validation "
            "bands, its parent investigation, and its reviewed notes. Takes the run_id "
            "returned by search_runs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "The run's id."},
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "get_leaderboard",
        "description": (
            "One investigation's runs, ranked by its primary metric on the holdout, "
            "with each run's cross-validation band beside it. Use this to compare "
            "what has been tried and to ground a recommendation about what to try "
            "next — it returns the ordering the app itself computed, not an "
            "impression assembled from snippets. Takes the experiment_id returned "
            "by search_runs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "experiment_id": {
                    "type": "string",
                    "description": "The investigation's id.",
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        "How many top-ranked rows to return. Defaults to all of them, "
                        f"maximum {settings.agent_max_leaderboard_rows}."
                    ),
                },
            },
            "required": ["experiment_id"],
        },
    },
]

_SCHEMAS: dict[str, Any] = {tool["name"]: tool["input_schema"] for tool in TOOLS}

_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
}

# validate_tool_call promises to return a string and never raise, so a schema
# type with no _TYPES entry would be a KeyError raised from the one function
# whose whole job is turning bad input into a message the model can act on — a
# 500 that loses the conversation. Checked here, at import, so adding a
# `"type": "number"` property to a schema fails on the next test run rather than
# on the first call that happens to pass that argument.
_unmapped = sorted(
    {prop["type"] for schema in _SCHEMAS.values() for prop in schema["properties"].values()}
    - set(_TYPES)
)
if _unmapped:  # pragma: no cover - a schema edit is what trips this, not a test
    raise RuntimeError(f"app.agent._TYPES has no entry for JSON schema type(s): {_unmapped}")


# Sent with the forced final call. Removing `tools` from the request is NOT
# enough on its own: the transcript still contains tool_use/tool_result blocks,
# and the model reads those as evidence the tools exist and emits another
# tool_use — observed live, `stop_reason="tool_use"` on a request carrying no
# tool definitions at all. The loop then breaks with no text block and the user
# gets an empty answer, which is exactly the backend-failure look the forced
# call exists to prevent. Saying so in words is what actually turns the model to
# prose.
_FINAL_TURN_INSTRUCTION = (
    "You have used your entire tool budget and no further tool calls are "
    "possible. Answer the question NOW, in prose, using only what you have "
    "already retrieved above. If what you retrieved is not enough to answer, "
    "say plainly what you found and what remains unknown."
)

# Last-resort text, used only when even the forced call returns no prose. An
# empty answer renders as a blank bubble that is indistinguishable from a
# crashed request, so the caller is told what actually happened.
_NO_ANSWER = (
    "I could not produce an answer within the tool budget for this question. "
    "Any sources found along the way are listed below; asking something "
    "narrower usually helps."
)


def load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def validate_tool_call(name: str, args: dict[str, Any]) -> str | None:
    """Check `args` against the tool's schema.

    Returns an error STRING, never raises. The string is sent back as the tool
    result, so the model sees its own mistake and corrects it on the next turn;
    an exception here ends the request with a 500 and loses the conversation.
    The message names the offending argument for the same reason — "invalid
    arguments" gives the model nothing to act on, so it retries the same call.
    """
    schema = _SCHEMAS.get(name)
    if schema is None:
        return f"Unknown tool {name!r}. Available tools: {', '.join(sorted(_SCHEMAS))}."

    properties: dict[str, Any] = schema["properties"]
    unknown = sorted(set(args) - set(properties))
    if unknown:
        return (
            f"Unknown argument(s) for {name}: {', '.join(unknown)}. "
            f"Valid arguments: {', '.join(sorted(properties))}."
        )

    missing = [key for key in schema["required"] if not str(args.get(key, "")).strip()]
    if missing:
        return f"{name} requires {', '.join(missing)}."

    for key, value in args.items():
        expected = _TYPES[properties[key]["type"]]
        # bool is a subclass of int; True is not a valid k.
        if isinstance(value, bool) or not isinstance(value, expected):
            got = type(value).__name__
            return f"{name}: {key} must be a {properties[key]['type']}, got {got}."

    k = args.get("k")
    if isinstance(k, int) and not 1 <= k <= settings.agent_max_k:
        # Rejected, not clamped: silently answering a k of 500 with 25 sources
        # tells the model the history holds 25, and it then reports that.
        return f"{name}: k must be between 1 and {settings.agent_max_k}, got {k}."

    limit = args.get("limit")
    if isinstance(limit, int) and not isinstance(limit, bool):
        if limit < 1 or limit > settings.agent_max_leaderboard_rows:
            return (
                f"{name}: limit must be between 1 and "
                f"{settings.agent_max_leaderboard_rows}, got {limit}."
            )

    return None


@dataclass(frozen=True)
class AgentStep:
    """One receipt from the transcript. Never carries retrieved text — the text
    lives once, in AgentResult.retrieved."""

    type: str  # "llm" | "tool"
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    result_summary: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class AgentResult:
    answer: str
    retrieved: list[retrieval.Hit]
    warnings: list[str]
    steps: list[AgentStep]
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int


def _default_client() -> Any:
    import anthropic

    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _summarize(hits: list[retrieval.Hit]) -> str:
    """A receipt for the trace: counts and ids only."""
    return f"{len(hits)} source(s): " + ", ".join(
        f"{hit.source_type}:{hit.source_id[:8]}" for hit in hits
    )


def _render_hits(hits: list[retrieval.Hit], warnings: list[str]) -> str:
    """The tool result the MODEL sees. Ids are included because the prompt asks
    it to cite, and it cannot cite what it was not given."""
    if not hits:
        body = "No reviewed history matched. Nothing approved matches these filters."
    else:
        body = "\n\n".join(
            f"[{hit.source_type}] run_id={hit.run_id} experiment_id={hit.experiment_id} "
            f"score={hit.score:.3f}\n{hit.snippet}"
            for hit in hits
        )
    return body + ("\n\nWarnings: " + "; ".join(warnings) if warnings else "")


def _render_detail(detail: retrieval.RunDetail) -> str:
    band = "unquantified" if detail.cv_std is None else f"{detail.cv_std:.4f}"
    return (
        f"run_id={detail.run_id} model={detail.model_type} status={detail.status}\n"
        f"experiment={detail.experiment_name!r} objective={detail.experiment_objective!r}\n"
        f"params={detail.params}\nmetrics={detail.metrics}\ncv_std={band}\n"
        f"notes ({detail.notes_status}): {detail.notes}"
    )


def _render_leaderboard(board: LeaderboardOut, experiment_id: str) -> str:
    """The tool result the MODEL sees.

    `experiment_id` is a parameter because LeaderboardOut does not carry one —
    the caller already knows the id it asked for, and widening a shipped API
    response for a tool's convenience would change the frontend contract for no
    frontend reason.

    A LeaderboardRowOut nests its run: `row.run.id`, `row.run.model_type`. The
    rank-level fields are `rank`, `value`, `cv_value`, `cv_std`, `is_best` and
    `within_noise`.

    `within_noise` is rendered rather than re-derived from cv_std. The backend
    already made that D38 judgment, over the whole investigation; a tool that
    recomputes it from the raw numbers can disagree with the leaderboard the
    user is looking at, and then two surfaces state different things about the
    same runs. cv_std is included too, and a `None` renders as "unquantified",
    never as 0.0 (D32) — a fabricated zero band makes every difference look
    significant.
    """
    if not board.rows:
        return f"Investigation {experiment_id} has no ranked runs yet."
    header = (
        f"Investigation {experiment_id}, ranked by {board.primary_metric} "
        f"({board.metric_direction}). ranked={board.ranked} "
        f"mlflow_available={board.mlflow_available}"
    )
    lines = [
        f"rank={row.rank} run_id={row.run.id} model={row.run.model_type} "
        f"{board.primary_metric}={row.value} cv={row.cv_value} "
        f"cv_std={'unquantified' if row.cv_std is None else row.cv_std}"
        + (" [best]" if row.is_best else "")
        + (" [within noise of the leader]" if row.within_noise else "")
        for row in board.rows
    ]
    return header + "\n" + "\n".join(lines)


def _execute(
    name: str, args: dict[str, Any], session: Session
) -> tuple[str, list[retrieval.Hit], list[str], str | None, str]:
    """Run one validated tool call.

    Returns (tool_result_text, hits, warnings, error, summary). Never raises: a
    tool failure is information the model can act on, and an exception here ends
    the whole request with a 500 instead.
    """
    error = validate_tool_call(name, args)
    if error:
        return error, [], [], error, "rejected"

    try:
        if name == "search_runs":
            filters = retrieval.Filters(
                model_type=args.get("model_type"),
                dataset_id=args.get("dataset_id"),
                task_type=args.get("task_type"),
                experiment_id=args.get("experiment_id"),
                status=args.get("status"),
            )
            hits, warnings = retrieval.search_runs(
                session, args["query"], filters=filters, k=args.get("k")
            )
            return _render_hits(hits, warnings), hits, warnings, None, _summarize(hits)

        if name == "get_leaderboard":
            board = build_leaderboard(session, args["experiment_id"], limit=args.get("limit"))
            return (
                _render_leaderboard(board, args["experiment_id"]),
                [],
                [],
                None,
                f"{len(board.rows)} row(s)",
            )

        detail = retrieval.get_run_detail(session, args["run_id"])
        return _render_detail(detail), [], [], None, f"run {detail.run_id[:8]}"
    except ExperimentNotFound as exc:
        # Before `except KeyError`, and a distinct message: reporting a missing
        # experiment as a missing run gives the model a correction it cannot make.
        message = f"No experiment with id {exc.args[0]!r}."
        return message, [], [], message, "not found"
    except KeyError as exc:
        message = f"No run with id {exc.args[0]!r}."
        return message, [], [], message, "not found"
    except Exception as exc:  # noqa: BLE001
        message = f"{name} failed: {exc}"
        return message, [], [], message, "failed"


def _final_turn(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The forced call's message list: a copy, with the stop-calling-tools
    instruction attached.

    Appended to the trailing tool_result message rather than sent as a new user
    turn — the Messages API rejects a user message that follows another user
    message, and the transcript at this point always ends in one.
    """
    call_messages = list(messages)
    last = call_messages[-1] if call_messages else None
    if last and last["role"] == "user" and isinstance(last["content"], list):
        call_messages[-1] = {
            "role": "user",
            "content": [*last["content"], {"type": "text", "text": _FINAL_TURN_INSTRUCTION}],
        }
    else:
        call_messages.append({"role": "user", "content": _FINAL_TURN_INSTRUCTION})
    return call_messages


def run_agent(question: str, session: Session, *, client: Any | None = None) -> AgentResult:
    """Answer `question` from reviewed experiment history.

    Deliberately separate from app/loop.py: that loop is judge-gated and renders
    charts, and folding the two together would make each carry the other's
    concerns for no shared behaviour.
    """
    client = client or _default_client()
    started = time.perf_counter()
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    steps: list[AgentStep] = []
    retrieved: list[retrieval.Hit] = []
    seen: set[tuple[str, str]] = set()
    warnings: list[str] = []
    tokens_in = tokens_out = 0
    answer = ""

    with span("agent.request", question_chars=len(question)):
        for turn in range(max(1, settings.agent_max_turns) + 1):
            # The extra iteration is the forced final call: tools removed, so the
            # user gets an answer rather than an empty string that looks like a
            # backend failure. It does not count against the cap.
            forced = turn == max(1, settings.agent_max_turns)
            kwargs: dict[str, Any] = {
                "model": settings.anthropic_model,
                "max_tokens": settings.anthropic_max_tokens,
                "system": load_system_prompt(),
                # A COPY per call: `messages` is mutated in place as the
                # transcript grows, and handing our live list to the SDK would
                # let anything that retains it observe later turns.
                "messages": _final_turn(messages) if forced else list(messages),
            }
            if not forced:
                kwargs["tools"] = TOOLS

            call_started = time.perf_counter()
            with span("agent.llm_call", turn=turn, forced=forced):
                response = client.messages.create(**kwargs)
            latency = int((time.perf_counter() - call_started) * 1000)

            call_in = int(getattr(response.usage, "input_tokens", 0) or 0)
            call_out = int(getattr(response.usage, "output_tokens", 0) or 0)
            tokens_in += call_in
            tokens_out += call_out
            steps.append(
                AgentStep(
                    type="llm",
                    model=settings.anthropic_model,
                    tokens_in=call_in,
                    tokens_out=call_out,
                    latency_ms=latency,
                )
            )

            text_parts = [b.text for b in response.content if getattr(b, "type", "") == "text"]
            if text_parts:
                answer = "\n".join(text_parts).strip()

            tool_uses = [b for b in response.content if getattr(b, "type", "") == "tool_use"]
            if forced or not tool_uses:
                break

            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in tool_uses:
                args = dict(block.input or {})
                tool_started = time.perf_counter()
                with span("agent.tool_call", tool=block.name):
                    text, hits, tool_warnings, error, summary = _execute(block.name, args, session)
                for hit in hits:
                    key = (hit.source_type, hit.source_id)
                    if key not in seen:
                        seen.add(key)
                        retrieved.append(hit)
                for warning in tool_warnings:
                    if warning not in warnings:
                        warnings.append(warning)
                steps.append(
                    AgentStep(
                        type="tool",
                        tool_name=block.name,
                        tool_args=args,
                        result_summary=summary,
                        error=error,
                        latency_ms=int((time.perf_counter() - tool_started) * 1000),
                    )
                )
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": text})
            messages.append({"role": "user", "content": results})

    return AgentResult(
        answer=answer or _NO_ANSWER,
        retrieved=retrieved,
        warnings=warnings,
        steps=steps,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=_estimate_cost(settings.anthropic_model, tokens_in, tokens_out),
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
