# Project 1 — CSV Analysis Assistant — Design

**Status:** Approved design (revisable)
**Date:** 2026-06-23 (revised 2026-06-25; storage/identity reframe 2026-06-25; raw-CSV storage 2026-06-29; D2 superseded by the judge-gated LLM loop 2026-07-29, issue #9 — see `doc/project-1-llm-loop-design.md`)
**Program:** AI Engineering Workshop Summer 2026 — Project 1 (Weeks 1–4)
**Source spec:** `ai-engineering-workshop/doc/workshop-program-overview.md` §3.1
**Repo:** `csv-analysis-assistant-fastapi-react`

---

## 1. Summary

Upload a CSV, ask questions about it in natural language, and get plots + statistics +
an LLM-written interpretation. The system uses Claude with **tool-calling over a fixed
menu of pandas/plot functions**, driven by a **judge-gated multi-pass loop** (issue #9,
`app/loop.py` — see D2 and `doc/project-1-llm-loop-design.md`): an analyst pass reads a
rich profile of the dataset, selects which analysis function(s) to run, and writes an
interpretation; the backend executes those functions deterministically and renders the
charts; a separate judge pass then scores the attempt against the **actual rendered
charts and stats**, and the loop repeats — feeding the analyst its own prior output and
the judge's feedback — until the score clears a threshold or a hard pass cap is hit. This
replaced an earlier **single-LLM-pass** design, in which the interpretation was written
from the profile alone, before any chart was rendered.

The build is deliberately **single-datastore and identity-free**: Postgres is the only
persistence layer (no object store, no auth), a dataset is addressed by a shareable link,
and charts are re-rendered on demand rather than stored. This keeps every §3.1 learning goal
that matters (full-stack Postgres, persistence across sessions) while cutting the two pieces —
auth and a second storage system — that teach no AI-engineering lesson.

This is Project 1 of a 3-project compounding arc; Project 2 forks this repo. Design choices
favor a lean, understandable Weeks 1–4 build that still establishes the disciplines
(tool use, context engineering, evals, engineering standards) the later projects harden.

---

## 2. Key decisions (and why)

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| D1 | **Analysis engine** | Tool-calling over a fixed function menu | Safe (no arbitrary code execution), deterministic, easy to eval. Teaches tool use early — compounds into Project 2's single-agent loop and Project 3's multi-agent system. |
| D2 | **LLM loop shape** | ~~Single-pass~~ **Superseded (issue #9): judge-gated multi-pass loop** — an analyst pass selects/adds tools and interprets, charts are rendered, a separate judge scores the attempt against the real rendered output, and the loop repeats to a threshold or pass cap | Single-pass was the simplest Weeks-1–4 starting point but produced interpretations grounded in a *prediction* of the charts, not the charts themselves. The Week-3 go/no-go (§8) triggered the revisit; rather than a fixed 2-pass split, a quality-gated loop was chosen so cost/latency stay bounded (hard pass cap) while quality is measured, not assumed. See `doc/project-1-llm-loop-design.md` for the full design. |
| D3 | **Per-question context** | **Bounded rich profile** of the dataset | Schema, `describe()`, null counts, cardinality-aware value counts, correlations, sample rows — **width-capped to a token budget** (§4) so it stays a summary, not a data dump. Enough for honest single-pass interpretation. Cacheable. This *is* the Project 1 context-engineering lesson. |
| D4 | **Authentication** | **None — dataset-link identity** | Auth teaches no AI-engineering lesson, so it is cut entirely (not just minimized). No `users` table; a dataset id *is* its shareable link. Softens §3.1's "sign up." Full auth/isolation is the Project 2 fork's job. |
| D5 | **Data storage** | **Raw CSV in Postgres; no object store; charts re-rendered on demand** | Single datastore. Uploaded data is stored verbatim as raw CSV text in the `datasets` row (`data_csv text`); the profile JSON is cached alongside it. No parquet/pyarrow step — the stored CSV re-parses with the same pandas reader used at upload, so a reload is faithful to what the user uploaded. Trade-off: no compression (a 50MB CSV stays ~50MB), bounded by the §5 upload cap. Charts are a pure function of stored data + `tool_calls`, so they are re-rendered on reload, never persisted. Satisfies "history persists across sessions" with one durable store. |
| D6 | **Eval v0 assertions** | **Tool selection + columns (deterministic) + keyword guards on prose** | Stable pass/fail without judge-model cost or snapshot brittleness. LLM-as-judge deferred to Project 2/3 eval maturity. |

### Known simplifications / revision points
- **D2 single-pass (superseded, issue #9):** interpretation was originally written from the
  profile, not from freshly computed per-question numbers. The Week-3 go/no-go (prose-keyword
  pass rate on the golden set below **80%**) triggered the revisit; the design landed on a
  **judge-gated multi-pass loop** rather than a fixed 2-pass split — see
  `doc/project-1-llm-loop-design.md` for the full replacement design (analyst → render →
  judge → iterate to threshold **80** or cap **3** passes, return best-scoring pass).
- **D4 no auth:** no users, passwords, or sessions, and therefore no user isolation. The
  trade-off (a public URL anyone can reach) is handled operationally, not by login — see the
  rate limit + daily token ceiling in §7. Real auth/isolation arrives when Project 2 forks.
- **D5 raw-CSV-in-Postgres:** keeps the upload size cap (§5) so the uncompressed CSV text stays
  within comfortable `text`-column range; revisit (parquet compression / object store) only if
  Project 2 needs larger datasets.

---

## 3. Architecture

```
┌────────────┐   HTTPS/JSON   ┌─────────────────────────────┐
│ React + Vite│ ─────────────▶ │ FastAPI backend             │
│ - dataset   │                │                             │
│   link/pick │                │  /datasets  (upload→profile)│
│ - upload CSV│ ◀───────────── │  /chat      (ask question)  │
│ - chat +    │                │                             │
│   inline    │                │  ┌───────────────────────┐  │
│   charts    │                │  │ Analysis engine        │ │
└────────────┘                 │  │  fixed pandas/plot fns │  │
                               │  │  (charts re-rendered    │ │
                               │  │   on demand)            │  │
                               │  └───────────────────────┘  │
                               │           │                  │
                               │           ▼                  │
                               │     Anthropic Claude         │
                               │  (analyst + judge loop,      │
                               │   issue #9 — see D2)         │
                               └──────────────┬──────────────┘
                                              ▼
                                     ┌──────────────────┐
                                     │ Postgres (only)  │
                                     │ datasets         │
                                     │  (meta + profile │
                                     │   + raw CSV text)│
                                     │ chat_messages    │
                                     └──────────────────┘
```

**Deployment note:** Postgres is the single source of truth, so the ephemeral local
filesystem of Render/Fly free tiers is a non-issue — there is no object store to provision and
nothing durable on local disk. The uploaded data lives as raw CSV text in the `datasets`
row; charts are regenerated from that data on each request, so no chart files are ever stored.

---

## 4. Components

Each component has one job, a defined interface, and is testable in isolation. The
data-touching components (Profiler, Analysis engine) are prototyped in a Jupyter notebook for
fast EDA iteration, then refactored into typed, docstringed, unit-tested Python modules — the
prototype → module cycle from §3.1.

1. **Frontend (React + Vite)** — CSV upload, dataset picker (datasets addressed by link/id),
   chat thread with charts rendered inline alongside Claude's text. No login. Talks only to
   FastAPI.
2. **Profiler** — on upload, loads the CSV into pandas once, computes the **bounded rich
   profile** (below), and stores the data as **raw CSV text** plus the profile JSON in the
   `datasets` row. The profile is deliberately width-bounded so it stays a *summary*, not a
   data dump — this is the Project 1 context-engineering lesson made concrete:

   - **`describe()`** on all numeric columns; **null counts** on all columns.
   - **`value_counts`** only for object/categorical columns with **cardinality ≤ 20** (top-20);
     high-cardinality columns (IDs, free text, timestamps) are skipped — they bloat context
     and teach Claude nothing.
   - **Correlations:** full matrix up to **30 numeric columns**; beyond that, only the **top-25
     strongest pairs**.
   - **Sample rows:** a fixed **5**.
   - A **profile-token budget**: if the assembled profile exceeds it, degrade gracefully to
     schema + `describe()` + top correlations only.

   These thresholds are **configuration parameters** (a single source of truth in `Settings`,
   overridable per-environment via `.env` — see `.env.example`), not magic numbers: the
   stated values are the defaults — `PROFILE_MAX_CARDINALITY=20`, `PROFILE_MAX_CORR_COLS=30`,
   `PROFILE_TOP_CORR_PAIRS=25`, `PROFILE_SAMPLE_ROWS=5`, `PROFILE_TOKEN_BUDGET=8000`.
3. **Analysis engine** — the fixed menu of typed functions (`histogram`, `scatter`,
   `correlation_matrix`, `box_plot`, `describe`, `value_counts`, …). Each takes a DataFrame +
   column args and returns `(chart, stats dict)`. The *only* code that touches the data; no
   arbitrary code execution. Rendering uses the matplotlib **`Agg` backend with a fresh
   `Figure` per call — never the global `pyplot` state**, which is not thread-safe under
   FastAPI's concurrency.
4. **LLM loop** (`app/loop.py`, issue #9 — see D2) — builds the prompt (system prompt +
   cached profile + recent turns + question), then runs an **analyst → render → judge**
   cycle: an analyst call picks/adds chart tools and writes an interpretation, the backend
   validates and invokes the chosen functions, and a separate judge call scores the
   attempt against the rendered charts + stats. The loop repeats (feeding the analyst its
   own prior turn, the rendered images/stats, and the judge's feedback) until the score
   clears a threshold or a hard pass cap, then returns the best-scoring pass.
5. **Persistence layer** — **Postgres only**: `datasets` (metadata + profile + raw CSV text)
   and `chat_messages`. No object store. Because charts are a pure function of the stored data
   and the message's `tool_calls`, reloading a thread **re-renders** its charts from those two
   inputs rather than reading saved image files.

---

## 5. Data flow

### Flow A — Upload a dataset
```
User picks CSV ─▶ POST /datasets (multipart)
   ├─ validate (is CSV, size cap ~50MB / ~1M rows, >0 rows; reject over cap before profiling)
   ├─ load once into pandas ─▶ Profiler computes bounded profile; data kept as raw CSV
   └─ INSERT datasets row (id, name, n_rows, n_cols, profile_json, data_csv)
        ◀─ returns dataset_id (the shareable link) + summary card to UI
```

### Flow B — Ask a question (judge-gated loop, tool-calling; issue #9, see D2)
```
User types question in a dataset's chat ─▶ POST /chats/{id}/messages {question}
   0. Rate-limit / daily-budget check (§7); reject early if exceeded
   1. Load attached dataset(s); pull cached profile_json (no recompute)
   2. Build prompt: system prompt + profile(s) (cache-controlled) + recent chat turns + question
   3. Loop (up to llm_max_passes, default 3):
        a. Analyst call with fixed functions exposed as tools
             └─ returns: tool_use block(s) {fn, columns} + NL interpretation text
        b. Backend validates + re-parses data_csv into pandas, runs the new function(s)
             └─ each yields a freshly rendered chart + a stats dict (no files persisted)
        c. Judge call scores the attempt against the actual rendered charts/stats (0-100)
        d. Stop if score ≥ llm_quality_threshold (default 80) or the pass cap is hit;
           otherwise feed the analyst its prior turn + rendered charts/stats + judge
           feedback and loop
   4. INSERT chat_messages: user Q row, assistant row from the **best-scoring** pass
        (interpretation + cumulative tool_calls + summed token/cost/latency +
         pass_count + judge_score)
        ◀─ returns {interpretation, [charts], stats} ─▶ UI appends to thread

   On history reload: charts are re-rendered from data_csv + each message's tool_calls.
```

**Grounded interpretation:** because the judge scores the analyst's prose against the
charts and stats **as actually rendered** (not a prediction of them), and can send the
analyst back to revise, interpretation and charts stay consistent — and the loop can
correct a bad first pass rather than only guaranteeing internal consistency the way the
old single-pass design did.

---

## 6. Data model (Postgres)

| Table | Key columns |
|---|---|
| `datasets` | `id` (the shareable link), `name`, `n_rows`, `n_cols`, `profile_json` (JSONB), `data_csv` (`text`), `created_at` |
| `chat_messages` | `id`, `dataset_id`, `role` (user/assistant), `content` (text), `tool_calls` (JSONB), `tokens_in/out`, `cost_usd`, `latency_ms`, `pass_count` (nullable int), `judge_score` (nullable int), `created_at` |

- No `users` table — identity is the dataset id itself (D4). Chat is scoped to a dataset;
  reopening a dataset link replays its full thread, with charts **re-rendered** from
  `data_csv` + each message's `tool_calls` (no chart files are stored).
- `tool_calls` on the assistant row is both the chart-render instruction *and* what the eval
  asserts against — a single source of truth; it now accumulates across every analyst pass
  in a turn, not just one call.
- `tokens/cost/latency` columns make the Week 1 foundations lesson (cost **and** latency)
  visible per message, and are now **summed across every analyst + judge call** in the turn
  (issue #9).
- `pass_count` / `judge_score` (both nullable — pre-loop rows and judge-failure turns stay
  `NULL`) record how many analyst passes ran and the best judge score for later eval/analysis.
  They are **not** exposed on `ChatMessageOut` or the frontend.

---

## 7. Error handling & guardrails

Heavy guardrails are Project 3's domain. Project 1 names the common Weeks 1–4 failure modes
and the theme: **validate Claude's choices against the real data before executing, and degrade
partially rather than crash.** This seeds the validation discipline formalized in Project 3.

| Failure | Handling |
|---|---|
| Bad/oversized CSV (not CSV, malformed, > cap, 0 rows) | Reject at `/datasets` with a clear 4xx + message; never partially ingest. Validate before profiling. |
| Claude picks a nonsense tool/column (missing column, histogram on text) | Backend validates tool args against the real schema before executing. On mismatch: skip that call, return a graceful note, no stack trace. |
| A function raises mid-analysis | Each call wrapped; failure becomes a per-chart error entry; other selected charts still render. |
| Claude returns no tool call (pure text / refusal) | Allowed — render the text, no chart. Eval flags only if a chart was expected. |
| Anthropic API error / timeout / rate limit | One retry with backoff, then a friendly error persisted as an assistant row marked `error`. |
| Cost control (Week 1 lesson, not a hard guard) | Profile sent with prompt caching; token/cost/latency logged per message; cheaper model configurable for dev/eval. |
| **Open public URL** (no auth — D4) — anyone who finds the URL can spend Anthropic tokens | Operational guard, not login: a **per-IP rate limit** (~20 questions/min) and a **global daily token ceiling**; over either, `/chat` returns a friendly **429** before calling Claude. Turns the Week-1 cost lesson into an enforced control. |

---

## 8. Testing & eval

Both layers run behind `make` targets.

### Unit / integration (`make test`, pytest)
- **Profiler:** known CSV → correct dtypes, stats, null counts, correlations. Deterministic.
- **Analysis functions:** each function tested directly — correct stats dict, PNG produced,
  bad args raise the expected validation error. Bulk of deterministic coverage.
- **Persistence / API:** upload→row created with a **CSV round-trip** (stored CSV re-parses
  to an identical DataFrame); chat→messages persisted with `tool_calls`; **chart
  re-render** from `data_csv` + `tool_calls` reproduces a chart on history reload; dataset
  scoping holds. Run against a test Postgres.
- **LLM loop:** Claude client **mocked** here (a scripted sequence of analyst/judge
  responses) — fast, free, deterministic. Covers threshold-met-on-pass-1, score-climbs-
  then-clears, cap-hit-without-clearing (returns best-scoring pass), stall-out, judge-error
  mid-loop, and invalid-tool-call-mid-loop. Real-LLM behavior lives in eval.

### Eval v0 (`make eval`) — 30+ Q/A golden set
Cases in JSON/YAML: `{question, dataset, acceptable_tools[], expected_columns,
interpretation_must_mention[]}`. Runner loads a fixed sample dataset, sends each question
through the **real** loop (`app.loop.run_loop`) at **temperature 0**, and asserts
against the loop's final (best-scoring) output:

```
PRIMARY (deterministic):
  ✓ Claude's chosen function ∈ the case's acceptable_tools set
  ✓ chosen columns ⊇ expected columns
SECONDARY (cheap guards on prose):
  ✓ interpretation mentions expected keyword(s)
  ✓ interpretation non-empty, no error marker
```

`acceptable_tools` is a **set**, not a single value: "show the distribution of age"
legitimately maps to `histogram` *or* `box_plot`, so a one-tool exact match would
manufacture false failures. Combined with temperature 0, this keeps the bar stable across
model updates — which matters because the Week-4 score is **frozen as the regression bar**
Project 2 inherits. Cost/flakiness control: fixed seed dataset, cheaper-model routing
allowed, results cacheable.

**Single-pass go/no-go (resolved, issue #9):** the SECONDARY prose-keyword pass rate on the
golden set was the trigger to revisit D2. Rather than a fixed 2-pass split, the design landed
on the judge-gated multi-pass loop described above — `make eval` now grades the loop's final
output, which *is* the resolution of this go/no-go.

### `make check`
`lint` (ruff) + `format --check` (black) + `type-check` (mypy) + `test`. Eval is separate
(`make eval`) since it costs tokens and hits the network.

---

## 9. Spec coverage (§3.1)

### 9.1 Acceptance criteria

| Spec criterion (§3.1) | How this design satisfies it |
|---|---|
| User can sign up, upload a CSV, ask EDA questions | **Spec softened (D4):** no sign-up — a dataset link is the identity. `/datasets` upload + `/chat` questions deliver the substance; full auth is the Project 2 fork's job |
| Generates relevant plots (histogram, scatter, correlation, box) | Fixed analysis-engine functions selected via tool-calling (D1) |
| LLM interprets charts/stats in natural language | Judge-gated multi-pass loop grounded in the actual rendered charts/stats (D2 as superseded by issue #9, D3), resolving the §8 go/no-go |
| Conversation history persists across sessions | `chat_messages` + raw-CSV-in-Postgres datasets; charts re-rendered on reload (D5) |
| Well-engineered system prompt in `prompts/` | System prompt authored and stored under `prompts/` |
| Eval v0: 30+ Q/A pairs, `make eval` | §8 eval v0 (D6) |
| `make check` passes | §8 `make check` target |
| Production URL live | Render/Fly deploy + Postgres (single datastore; no object store to provision) |
| README with setup, architecture diagram, eval results, demo GIF | Authored at hardening (Week 4) |

### 9.2 Topics introduced

| Topic (§3.1) | Where this design teaches it |
|---|---|
| AI engineering foundations (lifecycle, tokens, cost, latency, caching) | One Claude call per question (§5); `tokens/cost/latency` logged per message (§6); profile sent under prompt caching (D3) |
| Prompt engineering (structured outputs, CoT for stats) | System prompt in `prompts/`; tool schemas force structured tool selection; profile gives Claude the numbers to reason over before interpreting (D2, D3) |
| Context engineering (summaries vs. raw data, window mgmt) | **Bounded** profile instead of raw rows + recent-turns window (D3, §4 profiling policy: cardinality-aware value_counts, correlation/column caps, token budget) — the Project 1 context lesson |
| Data analysis stack (pandas, matplotlib, seaborn) | Profiler + Analysis engine (§4) |
| Jupyter prototype → module refactor cycle | Data components prototyped in a notebook, then refactored into typed/tested modules (§4) |
| Python engineering standards (Poetry, ruff/black, mypy, pytest, Makefile) | `make check` + tooling (§8, §11) |
| Eval v0 (golden set, pass/fail) | §8 eval v0 (D6) |
| Full-stack web architecture (React + FastAPI + Postgres) | §3 architecture |
| GitHub flow + Research-Plan-Implement | Program workflow (issues/PRs per the overview); design itself is the "Plan" artifact |

---

## 10. Out of scope for Project 1 (lives in later projects)
- Iterative/multi-step agent loop (Project 2 single-agent; Project 3 multi-agent)
- RAG / vector search, MLflow, Optuna (Project 2)
- Text-to-SQL, multi-agent coordination, full guardrail suite, scheduled pipelines,
  production dashboards (Project 3)
- Any authentication / user accounts / isolation (no `users` table at all) — expected at the time to be introduced at the Project 2 fork; **it was not.** Project 2 reaffirmed single-tenancy (its D2), so no `users` table exists in either project. The references to "the Project 2 fork's job" above are preserved as a record of what was believed when this design was approved.
- Object storage / external blob store — data lives as raw CSV in Postgres for Project 1

---

## 11. Tech stack
React + Vite · FastAPI · Postgres (Supabase/Neon free tier — single datastore) ·
Anthropic Claude API (tool use) · pandas + matplotlib/seaborn (`Agg` backend) ·
pyenv + Poetry · ruff + black + mypy · pytest · Makefile ·
deployed to Render or Fly.io free tier.

---

## 12. Amendments

- **Multi-dataset chat (issue #6, see `doc/project-1-multi-dataset-chat-design.md`):**
  A chat now spans one or more datasets via a new `chat_datasets` join table,
  replacing the single `chats.dataset_id` FK. Existing per-dataset tools
  (`histogram`, `scatter`, `correlation_matrix`) require a `dataset_id` argument;
  a new `compare` tool does a lightweight, in-memory, inner-join comparison
  across exactly two datasets. This is additive to D2 (the multi-dataset profile
  is assembled once per turn into a single system prompt, shared by every
  analyst pass in the loop) and D5 (joined data is computed in-memory per call
  and never persisted — raw CSV per dataset remains the only durable copy).

- **Quality-gated LLM loop (issue #9, see `doc/project-1-llm-loop-design.md`):
  supersedes D2.** The single-pass orchestrator (`llm.run_pass()`) is replaced
  by `app/loop.py`'s `run_loop()`: an analyst pass selects/adds chart tools and
  writes an interpretation, the backend validates and renders the charts (as
  before), and a separate judge pass — `app.llm.judge_call()`, scored per
  `prompts/judge.md` via a forced `submit_verdict` tool call — rates the
  attempt 0–100 against the **actual rendered** charts and stats. The loop
  repeats, feeding the analyst its own prior turn plus the judge's feedback,
  until the score clears `Settings.llm_quality_threshold` (default 80) or
  `Settings.llm_max_passes` (default 3) is reached, then returns the
  best-scoring pass. New nullable columns `chat_messages.pass_count` /
  `judge_score` persist this per turn for later eval/analysis but are **not**
  exposed on `ChatMessageOut` or the frontend — the public API response shape
  and the "charts are never stored" invariant (D5) are unchanged.
  `tokens_in/out`, `cost_usd`, `latency_ms` on the assistant row are now summed
  across every analyst + judge call in the turn. This resolves the D2 Week-3
  go/no-go (§8): the golden-set eval now grades the loop's final output rather
  than a single call.
