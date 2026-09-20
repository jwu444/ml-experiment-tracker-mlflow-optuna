# Quality-gated LLM loop (issue #9)

**Status:** Implemented (2026-07-29)
**Branch:** `feat/LLM-loop`
**Supersedes:** Design decision **D2** (single-pass LLM) in `CLAUDE.md` and
`doc/project-1-csv-analysis-assistant-design.md`.

## Problem

Today the app runs a **single** Anthropic call (`run_pass()` in `app/llm.py`):
Claude reads the dataset profile, selects chart tools, **and** writes the
interpretation in one shot. Because the interpretation is produced *before* the
charts are rendered, the prose describes what Claude *predicts* the charts will
show rather than what they actually show. Issue #9 tracks the documented D2
go/no-go alternative: split the work so interpretation is grounded in the real
rendered output.

This design goes beyond the fixed 2-pass sketch in issue #9: it introduces a
**quality-gated agent loop** that can run additional passes until a separate
judge model rates the analysis good enough (or a hard cap is hit).

## Goals

- Interpretation is grounded in the **actual** rendered charts and computed
  stats, not a prediction.
- A separate **judge** LLM scores each attempt and drives iteration.
- The analyst can **add charts** across passes (e.g. plot a column the judge
  flags as unexamined), not merely reword prose.
- Cost and latency are **bounded** by a hard pass cap.
- The frontend and the public API response shape are **unchanged**. _(Superseded
  by the PR #24 review — `ChatMessageOut` gained an optional `trace` and the UI a
  `PassTrace` panel; see the Amendment at the end.)_

## Non-goals

- Streaming / incremental UI. The turn stays a single blocking request.
- Keeping the single-pass path. `run_pass()` is **removed** (see Rollout).
- New chart tools. The loop reuses the existing `TOOL_DEFS`
  (`histogram`, `scatter`, `correlation_matrix`, `compare`).

## Decisions (from brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| 1 | How later passes "see" charts | **Both** rendered PNG images *and* the stats dicts |
| 2 | Quality gate | **Separate judge LLM**, score 0–100 + actionable feedback |
| 3 | What a re-loop may change | **Charts and/or prose** (full agent loop) |
| 4 | Loop bounds | Max **3** analyst passes; stop at judge score **≥ 80**; early-stop on stall; return **best-scoring** pass |
| 5 | Rollout vs. D2 | **Replace** single-pass entirely |
| 6 | Loop metadata | **Persist** `pass_count` + `judge_score` (migration); do **not** expose in API/UI _(superseded by the Amendment below — a per-pass trace is now persisted and exposed)_ |

## Architecture

### Control flow — `run_loop()`

New module `app/loop.py` owns the orchestration. `app/llm.py` is reduced to thin,
injectable Anthropic-call helpers (`analyst_call`, `judge_call`) plus the cost /
token bookkeeping that already lives there.

```
context   = [prior messages, user question, dataset profiles]
charts_so_far = []          # cumulative, deduped by (tool name, args)
best      = None            # highest-scoring snapshot seen

for pass_i in 1 .. LLM_MAX_PASSES (=3):
    analyst = analyst_call(context)                    # text + new tool_use blocks
    for each new tool call:
        err = validate_tool_call(...)                  # existing validation
        if err: collect error, skip
        else:   render (png, stats); add to charts_so_far (dedup)
    verdict = judge_call(question, analyst.interpretation, charts_so_far)  # images + stats
    snapshot = {
        interpretation, tool_calls: charts_so_far (copy),
        charts, stats, errors,
        score: verdict.score,
        tokens_in, tokens_out, cost, latency,          # this pass only
    }
    best = argmax_score(best, snapshot)
    if verdict.score >= LLM_QUALITY_THRESHOLD (=80):   break   # good enough
    if pass added no new charts AND score did not improve: break   # stall-out
    context += analyst turn + judge feedback           # analyst sees critique next pass

return best        # best-scoring snapshot — NOT necessarily the last pass
```

Notes:

- **Cumulative charts.** `charts_so_far` accumulates across passes and is deduped
  by `(name, args)`, so re-requesting an identical chart is a no-op. Each
  snapshot stores a copy of the chart set as it stood at that pass, so returning
  an earlier best pass returns exactly the charts that pass's prose relied on.
- **Return best, not last.** If pass 2 scores 78 and pass 3 regresses to 71, we
  return pass 2.
- **Context accumulation.** Each subsequent analyst call sees the running
  conversation: its prior interpretation, the charts it produced (as image +
  stats blocks), and the judge's feedback/gaps. This is what lets it target the
  judge's critique.

### Data contracts

**Analyst call** — uses the existing `TOOL_DEFS`. Returns interpretation text +
zero or more `tool_use` blocks, parsed exactly as `run_pass()` does today. New
charts are validated by the existing `validate_tool_call()`; invalid calls are
skipped and surfaced in `errors` (unchanged behavior).

**Judge call** — a separate Anthropic request driven by `prompts/judge.md`,
**forced** to return structured output via a `submit_verdict` tool:

```json
{ "score": 0-100, "meets_bar": true, "feedback": "…", "gaps": ["…"] }
```

The judge is shown the user's question, the analyst's interpretation, and the
current charts as **image blocks + stats dicts**.

**Snapshot** (in-memory only): `{ interpretation, tool_calls, charts, stats,
errors, score, tokens_in, tokens_out, cost, latency }`.

### Prompts

- `prompts/system.md` — remove the trailing "Work in a single pass…" line; fix
  the stale "single CSV dataset" wording (the app has been multi-dataset since
  issue #6); add that the analyst will be shown its **rendered** charts and may
  refine the prose or add charts across passes.
- `prompts/judge.md` (new) — rubric the judge scores against:
  1. **Grounded** — every claim traceable to the shown stats/visuals; no
     invented numbers or columns.
  2. **Answers the question** — directly addresses what the user asked.
  3. **Charts appropriate & sufficient** — right tool(s) for the question, and
     nothing important left unplotted.
  4. **Concise & well-structured** — leads with the key insight; under the prose
     budget.

  Output is a `score` plus concrete, actionable `gaps` the analyst can act on
  (e.g. "distribution of `income` unexamined — add a histogram"). The rubric is
  intentionally simple for the first cut and may be reweighted later.

### Persistence & schema

- **Migration** (Alembic, the schema authority on Postgres): add
  `chat_messages.pass_count INTEGER` and `chat_messages.judge_score INTEGER`,
  both **nullable**. Pre-existing rows stay `NULL`; no backfill.
- Persist the **best snapshot's** `interpretation` + cumulative `tool_calls`.
  Charts remain a pure function of `data_csv` + `tool_calls`, so history reads
  re-render identically via `charts.py` — the "charts are never stored"
  invariant is untouched.
- `tokens_in`, `tokens_out`, `cost_usd`, `latency_ms` on the assistant
  `ChatMessage` become **sums across all passes** (every analyst + judge call in
  the loop).
- `pass_count` and `judge_score` are stored for later eval/analysis but are
  **not** added to `DatasetOut`, `ChatMessageOut`, or the frontend.

### Config

New `Settings` fields (pydantic-settings), all `.env`-overridable and documented
in `.env.example`:

- `llm_max_passes` = **3**
- `llm_quality_threshold` = **80**
- `judge_model` = defaults to `anthropic_model` (Opus 4.8, vision-capable)

### Error handling & bounds

- **Judge call error** → treat as terminal: stop looping and return the
  best-so-far snapshot.
- **All tool calls invalid in a pass** → the pass is still judged on its prose;
  errors are collected as today.
- **Hard cap** — `llm_max_passes` bounds worst case to 3 analyst + 3 judge
  calls. Latency is accepted as a plain blocking request (no streaming, no
  wall-clock cap); the pass cap is the sole guardrail.

## API / frontend impact

**None** _(superseded — see the Amendment below; `ChatMessageOut` now carries an
optional `trace`)_. As originally designed, `POST /chats/{id}/messages` still
returned `ChatMessageOut` (`content`, `charts`, `stats`, `errors`) with the loop
metadata living only in the DB. The PR #24 review added `trace` to that response
and to history reads; see **Amendment: loop trace exposed in the UI**.

## Testing

- **Unit tests** — the injectable `client` now returns a **scripted sequence**
  of responses (analyst₁, judge₁, analyst₂, judge₂, …). New/updated cases:
  - threshold met on pass 1 → single analyst + single judge, no loop;
  - score climbs across passes then clears threshold → stop;
  - cap hit without clearing threshold → return best-scoring pass;
  - stall-out (no new charts + no score improvement) → early stop;
  - judge error mid-loop → return best-so-far;
  - invalid tool call mid-loop → skipped, error surfaced, loop continues;
  - telemetry (`tokens_*`, `cost`, `latency`) is summed across passes;
  - `pass_count` / `judge_score` persisted on the assistant message.
- Tests still run offline against SQLite with a mocked client — no API key.
- **`make eval`** — the golden set now grades the loop's final output. This *is*
  the resolution of the D2 go/no-go the eval was always meant to decide.

## Doc sync (required before merge, per CLAUDE.md)

- `CLAUDE.md` — rewrite **D2** to describe the loop; note the new `app/loop.py`,
  the two new `Settings` fields, and the `chat_messages` columns in the layout /
  constraints sections.
- `doc/project-1-csv-analysis-assistant-design.md` — update D2.
- `README.md` — update any user-facing behavior notes (e.g. that a turn may take
  longer due to multiple passes) if warranted.
- `doc/plans/` — tick off the implementation plan tasks as they complete.

## Open items deferred

- Judge rubric weighting/refinement — accepted as-is for the first cut; revisit
  after eval numbers exist.
- Cheaper judge model — `judge_model` config exists as the seam; not tuned now.

## Amendment: loop trace exposed in the UI (issue #9 review)

PR #24 review asked to surface the loop's work in the product, which **supersedes
Decision 6's "do not expose in API/UI"** and the earlier "response shape
unchanged" note:

- **Backend.** `run_loop()` returns a per-pass `trace` — one record per pass with
  the analyst (`model`, tokens, latency, cost, interpretation), the pass's
  cumulative `charts`/`stats`/`errors`, the judge (`model`, tokens, latency,
  cost, `score`, `feedback`, `gaps`), and the `revision_instruction` fed to the
  next pass. The route persists `{passes: [...]}` as JSON in a new nullable
  `chat_messages.trace_json` column and returns it as `ChatMessageOut.trace`
  (`MessageTraceOut | None`). History reads return it verbatim.
- **Frontend.** A `PassTrace` component renders a collapsed `<details>` under each
  answer.
- **System prompt (review comment 2).** **Never exposed** — not returned, not
  stored, no UI toggle. It can leak guardrail language, so it never leaves the
  backend; the trace leads with the feedback turn instead.
- **Chart storage exception.** Unlike the main charts (re-rendered from
  `tool_calls`, never stored), the trace stores each pass's rendered PNGs in
  `trace_json` so the UI shows exactly what each judge saw — a deliberate,
  reviewer-accepted exception to "charts are never stored", at a storage cost.
