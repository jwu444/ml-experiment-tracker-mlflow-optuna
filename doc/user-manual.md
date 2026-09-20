# User Manual

How to actually use the ML Experiment Tracker: uploading data, asking questions
about it, training and comparing models, and reviewing what the system writes
about your results.

This document is task-oriented. If you want to know *why* the system is built
the way it is, read [`doc/architecture.md`](architecture.md) instead.

**Contents**

1. [What this tool is for](#1-what-this-tool-is-for)
2. [First-time setup](#2-first-time-setup)
3. [Starting the app](#3-starting-the-app)
4. [Analysing a dataset by asking questions](#4-analysing-a-dataset-by-asking-questions)
5. [Training models](#5-training-models)
6. [Comparing runs on the leaderboard](#6-comparing-runs-on-the-leaderboard)
7. [Generated write-ups and approving them](#7-generated-write-ups-and-approving-them)
8. [Observing what the system is doing](#8-observing-what-the-system-is-doing)
9. [API reference](#9-api-reference)
10. [Configuration](#10-configuration)
11. [Troubleshooting](#11-troubleshooting)
12. [Limits and things it deliberately won't do](#12-limits-and-things-it-deliberately-wont-do)

---

## 1. What this tool is for

You have a table of data and a question about it. The tool does two kinds of
work on it.

**Ask questions in plain English.** Upload a CSV, start a chat, and ask
something like *"is memory size correlated with price?"* You get back a chart,
the underlying statistics, and a written interpretation. A second, independent
AI call grades that interpretation against the chart that was actually produced
before you see it — so an answer that describes a trend the data doesn't show
gets caught and retried.

**Train and compare models.** Pick a column to predict, pick a model, and the
tool trains it, scores it on held-back data, and records the run permanently.
It can also auto-search the model's settings across many trials. Everything
lands on a leaderboard so you can tell which approach actually worked — and
whether any of them beat the trivial baseline.

It is a single-tenant tool. **There is no login and no per-user data
separation:** anyone who can reach the server can see everything in it. Don't
put confidential data in a shared deployment.

---

## 2. First-time setup

You need Python 3.12, Poetry, Node, and Docker.

```bash
# 1. Install dependencies
poetry install
cd frontend && npm install && cd ..

# 2. Configure. ANTHROPIC_API_KEY is required for anything AI-powered:
#    chat, EDA write-ups, diagnostics. Training does NOT need it.
cp .env.example .env
$EDITOR .env          # set ANTHROPIC_API_KEY=sk-ant-...

# 3. Start Postgres (port 5433, to avoid colliding with a system Postgres)
make db-up

# 4. Create MLflow's schema and tables. Run once.
make mlflow-init

# 5. Build the model-ready datasets from the committed snapshots. Offline —
#    nothing is downloaded.
make prepare-data
```

Then, with the backend running (see §3), load the datasets:

```bash
make data-fetch       # uploads the prepared CSVs via the API
make seed-history     # OPTIONAL: 4 experiments, 32 real training runs, and
                      # AI-written draft notes. Needs an API key, costs tokens.
```

`make seed-history` is worth running the first time — it gives you populated
leaderboards to explore instead of an empty page.

---

## 3. Starting the app

Two terminals:

```bash
# Terminal 1 — backend on http://localhost:8000
make dev

# Terminal 2 — frontend on http://localhost:5173
cd frontend && npm run dev
```

Open **http://localhost:5173**. The frontend proxies `/api` to the backend, so
you only ever visit port 5173.

Check the backend is alive with `curl localhost:8000/health` → `{"status":"ok"}`.
Interactive API docs are at **http://localhost:8000/docs**.

---

## 4. Analysing a dataset by asking questions

**Upload.** On the home page, choose one or more `.csv` files. Uploading the
same file twice is safe — the tool recognises identical content and reuses the
existing dataset rather than duplicating it.

**Start a chat.** Select one or more datasets and start a chat. The datasets are
fixed when the chat is created; there's no "attach another one" mid-chat. To
ask about a different combination, start a new chat.

**Ask.** Type a question in plain English. You'll get back:

- one or more **charts**
- the **statistics** behind them (expandable)
- a written **interpretation**
- a collapsible **trace** (see §8)

**What it can actually plot.** The AI picks from a fixed set of six tools. It
cannot write arbitrary code, so questions outside this menu will be answered
with whichever of these comes closest:

| Tool | What it does |
|---|---|
| `histogram` | Distribution of one column |
| `scatter` | One column against another |
| `correlation_matrix` | Correlations across numeric columns |
| `line` | A series over an ordered numeric axis |
| `error_by_group` | Error broken down by category — used mainly in diagnostics |
| `compare` | Joins **exactly two** datasets and compares an aggregated metric |

Answers can take longer than you'd expect from a single question. The tool
often runs several internal passes, re-drawing and re-grading until the answer
clears a quality bar (default: 80/100, up to 3 passes). Your question appears in
the thread as soon as you send it, marked **Sending…** until the answer arrives —
so a long wait looks like a long wait rather than a lost question. If the request
fails, the question stays put and is marked **Not sent**: nothing was saved, but
you can still copy the text rather than retype it.

**Tips.** Name columns as they appear in your file — the tool validates column
names against the real schema and will tell you rather than guess. Ask one
thing at a time; a question bundling four asks tends to get a shallow answer to
each.

---

## 5. Training models

### Runs live inside an experiment

An **experiment** is one investigation — a question, a dataset, and a target.
The **runs** inside it are the attempts at that question. The dataset, the
target column and the task type belong to the experiment, not to each run:
that is what makes its runs comparable, and comparing runs is the whole point
of a leaderboard.

There is no way to launch a run without an experiment. Create one first.

### From the UI

Go to **/experiments**. The page lists your investigations — name, objective,
dataset, and how many runs each has. **New experiment** opens a form for the
name, objective, dataset, target column and task type; the target column is
picked from the chosen dataset's real columns, so it cannot be typo'd.

Open an investigation to see its leaderboard, and use **New run** there to
launch into it. That form asks for the model, a mode, and the settings that
model actually has:

- **Model** lists only models that fit this investigation's task type. The
  list comes from the backend's registry, so it is never out of date.
- **Train** runs one attempt with the hyperparameters you type. Leave a box
  empty to keep the model's own default. A model whose settings are column
  names (the persistence baseline's `prior_column`) gets a column picker
  rather than a number box.
- **Tune** runs an Optuna search instead, and asks only for a trial count.
  It is unavailable for a model with nothing to search over — the
  persistence baseline has no settings, so N trials would be N identical
  runs.
- **Time column** makes the split chronological (holdout = the tail of the
  sorted frame). Leave it on *None* for a random split. The target column is
  never offered here — it is the answer, not an input.

Both run now, inside the request, so the dialog stays open until the work
finishes: seconds for a single train, potentially minutes for a search. The
new rows land on the leaderboard behind the dialog when it closes.

### From the API

```bash
# once per investigation
curl -X POST localhost:8000/experiments \
  -H 'Content-Type: application/json' -d '{
    "name": "revenue nowcast",
    "objective": "beat the persistence baseline",
    "dataset_id": "<dataset-id>",
    "target_column": "revenue_next_usd",
    "task_type": "regression"
  }'
# -> {"id": "<experiment-id>", ...}

# then once per attempt
curl -X POST localhost:8000/experiments/<experiment-id>/train \
  -H 'Content-Type: application/json' -d '{
    "model_type": "ridge",
    "hyperparams": {},
    "time_column": "as_of"
  }'
```

Experiment names are unique. Creating a second experiment called `revenue
nowcast` — or renaming one onto a name already in use — returns **409**. The
name is how a run finds its MLflow experiment, so two investigations sharing one
would quietly pool their runs into a single leaderboard. Pick a name that says
which question this is: `revenue nowcast (weekly)` rather than a second
`revenue nowcast`.

### The models available

| `model_type` | Predicts | Tunable settings |
|---|---|---|
| `ridge` | a number | `alpha` |
| `random_forest` | a number | `n_estimators`, `max_depth`, `min_samples_leaf` |
| `gradient_boosting` | a number | `n_estimators`, `learning_rate`, `max_depth` |
| `persistence` | a number | *(none — it's the baseline)* |
| `logistic_regression` | a category | `C` |
| `random_forest_clf` | a category | `n_estimators`, `max_depth`, `min_samples_leaf` |

### `time_column` — the one setting to get right

**If your data is a time series, you must pass `time_column`.** With it, the
tool holds back the *most recent* rows and grades the model on predicting them.
Without it, the holdout is a random sample — which lets the model learn from
the future to predict the past, and produces scores that look great and mean
nothing.

The tool cannot detect this for you, so it fails loudly instead of guessing: a
column name that doesn't exist is rejected with a **422**, never silently
ignored. The named column is used only to order and split the data — it is
never used as a predictor.

### Tuning

```bash
curl -X POST localhost:8000/experiments/<experiment-id>/tune \
  -H 'Content-Type: application/json' -d '{
    "model_type": "random_forest",
    "time_column": "as_of",
    "n_trials": 20
  }'
```

Every trial is logged as its own run *inside that experiment*, so the
leaderboard shows the whole search, not just the winner. A study is one search
within an investigation, not an investigation of its own — it is recorded as a
tag on each run rather than as a separate experiment.

Tuning `persistence` is rejected with a 422 — it has no settings, so N trials
would be N identical runs.

### Always train the baseline

Before concluding a model is good, train `persistence` on the same target. It
predicts "the same as last time" and it is the bar a real model has to clear.

```bash
curl -X POST localhost:8000/experiments/<experiment-id>/train \
  -H 'Content-Type: application/json' -d '{
    "model_type": "persistence",
    "hyperparams": {"prior_column": "revenue_usd"},
    "feature_columns": ["revenue_usd"],
    "time_column": "as_of"
  }'
```

Train it into the **same experiment** as the models you want to compare it
against. A baseline on a leaderboard of its own is a baseline nobody sees.

`prior_column` must also appear in `feature_columns` — the baseline reads that
column straight out of the feature frame, so if it isn't there the run fails.
Naming both explicitly is the safe habit.

On the bundled revenue dataset this matters more than it sounds: across 25
logged runs, **nothing beat the baseline.** Without it on the board, several
models would have looked perfectly respectable.

---

## 6. Comparing runs on the leaderboard

Open an experiment from **/experiments** to reach its leaderboard at
**/experiments/<id>**: its runs ranked on the experiment's own metric, with the
best one badged, and checkboxes to compare selected runs side by side.

Ranking happens *within* one experiment and never across them, because runs in
different investigations are not on a common scale — the revenue panel's rmse
is in the billions and a component price's is in the hundreds, so a single
combined ranking would just sort by which question was asked.

**Read the standard deviation, not just the score.** Every metric comes with
the spread across cross-validation folds. The bundled revenue panel is about
224 rows, and on data that small a gap smaller than the fold spread is noise.
When the leader's margin over second place is smaller than its own spread, the
page says **within noise** rather than presenting it as a clean win. Two models
differing by less than their spread have not been shown to differ at all.

**Filtering by model.** The **Model type** dropdown above the table narrows it
to one model — useful when a tuning sweep has buried the handful of runs you
care about under forty trials of the same estimator. Its options are built from
the runs on the leaderboard in front of you, so every model you have actually
trained is always offered, including the `persistence` baseline. Ranks are the
ones the full leaderboard assigned and are **not** renumbered: a filtered row
still shows where it placed against every run in the experiment, not against
the survivors of the filter. Changing the filter clears any comparison
selection, so a hidden run cannot stay in the compare table.

If the tracking store is unreachable the leaderboard still lists the runs,
newest-first and unranked, and says so — rather than showing you an empty page.

Each row also has actions to generate a **diagnostic** write-up (§7) and to
open its notes for review.

---

## 7. Generated write-ups and approving them

The tool can write two kinds of analysis for you:

- **EDA** — a summary of a dataset. Trigger it with **Run EDA** on the dataset's
  own page (click the dataset in the left rail), or `POST /datasets/{id}/eda`.
- **Diagnostics** — an explanation of where a trained model went wrong: its
  residuals and its learning curve. Trigger it from a leaderboard row, or
  `POST /runs/{id}/diagnostics` — diagnostics are about one run, not about the
  whole investigation.

Neither takes any options — both work entirely from what's already stored.

**Everything generated starts as a draft.** It does not count as a result until
a person approves it. You review it **where it was generated**, not in a separate
queue: an EDA write-up appears under the dataset's column list, and a run's
diagnostic appears under the leaderboard on the experiment page as soon as the
pass finishes.

**How to approve:**

1. **Read it.** The write-up is Markdown and is shown rendered, the way a chat
   answer is, in full — nothing is truncated behind a "show more".
2. **Edit it if it overstates or gets something wrong.** **Edit** swaps the
   rendered text for a textarea holding the raw Markdown; **Done editing**
   switches back. Your edit is saved alongside the original, so the difference
   between what the AI proposed and what you accepted is preserved.
3. **Approve or Reject**, one write-up at a time. If you edited the text,
   approving saves your version and approves it in one step.

Editing text is **not** the same as approving it — approving is an explicit
action. Empty text can be rejected but never approved.

**Changing your mind.** Nothing is ever deleted — rejecting only sets a status —
so a write-up rejected by mistake is still on the same page, and approving it is
one click.

Take this seriously rather than clicking through it: a later phase of the
project treats approved text as known-good ground truth for measuring
retrieval quality, so rubber-stamping quietly corrupts that measurement.

**Diagnostics only work on regression runs.** Residuals aren't defined for a
classifier, so those buttons are disabled and the endpoint returns a 409.

---

## 8. Observing what the system is doing

**The reasoning trace.** Every chat answer has a collapsible panel showing each
internal pass: what the AI tried, what the grader scored it and why, and what
it was told to fix next time. This is how you check an answer instead of
trusting it. (The system prompt is deliberately never shown.)

**MLflow's UI** — `make mlflow-ui`. The raw tracking store: every run's
parameters, metrics, and saved model file. Use it when you want the full detail
behind a leaderboard row.

**Backend logs** — the terminal running `make dev` shows every request.

**Distributed tracing (off by default).** `docker-compose.yml` starts a Jaeger
container on port 16686. Set `OTEL_ENABLED=true` in `.env` and restart the
backend, and each request exports one trace: the LLM passes, the chart renders,
the agent's tool calls and the retrieval stages all nest under it, so you can see
where the time and the calls went. Leave it off and everything still works —
nothing branches on whether tracing is on.

Traces carry **ids, counts and durations only** — never your questions, note text
or embedding vectors. An exporter is a place data leaves the process from, so
payloads deliberately never go into one.

---

## 8b. Asking about past experiments

Click **Ask history → Ask about history** in the left rail (or go to `/ask`).
Type a question about work you have already done — "which model did best on the
revenue panel, and by how much?", "what did the diagnostics say about NVDA?" —
and press **Ask**.

**It only sees text you approved.** Approved run notes, approved EDA findings,
approved diagnostics. A draft is invisible to it, and so is a rejected write-up.
That is the point: everything the agent tells you has been read by a human first.

**The index is built offline.** Approving text does not index it. After a review
session, run:

```bash
make embed
```

This reconciles the index in both directions — newly approved text is added,
edited text is re-indexed, and text you *un*-approved is removed. It needs
`VOYAGE_API_KEY` in `.env`. A no-op run costs nothing.

**Reading an answer.** Under the answer is a **Sources** list. Each entry is a
link: an EDA citation opens that dataset's page, a run note or diagnostic opens
its investigation. Follow them — that is how you check the agent rather than
trusting it. The number beside each source is its similarity score. A collapsed
**Trace** at the bottom shows the tool calls it made, with tokens and timings.

**"No reviewed history matches."** This is the honest answer for an empty or
un-refreshed index, not an error. Either nothing is approved yet, or you have
approved things since the last `make embed`. It is also what you should see if
you ask about something the project genuinely has no notes on — the agent is
instructed to say so rather than fall back on general knowledge dressed up as
project history.

Each question is independent. There is no conversation history, so ask complete
questions rather than follow-ups.

---

## 9. API reference

Base URL `http://localhost:8000`. Full interactive docs at `/docs`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `POST` | `/datasets` | Upload a CSV (multipart `file`) |
| `GET` | `/datasets` | List datasets, newest first |
| `GET` | `/datasets/{id}` | One dataset |
| `POST` | `/datasets/{id}/eda` | Generate an EDA draft *(no body)* |
| `POST` | `/chats` | Start a chat over `{dataset_ids: [...]}` |
| `POST` | `/chats/{id}/messages` | Ask `{question}` |
| `GET` | `/chats/{id}` | Full history, charts re-rendered |
| `POST` | `/experiments` | Create an investigation |
| `GET` | `/experiments` | List investigations |
| `GET` | `/experiments/{id}` | One investigation |
| `PATCH` | `/experiments/{id}` | Update `name` / `objective` |
| `GET` | `/experiments/{id}/runs` | Its leaderboard, ranked |
| `POST` | `/experiments/{id}/train` | Train one model into it |
| `POST` | `/experiments/{id}/tune` | Optuna search inside it |
| `GET` | `/runs` | All runs, filterable |
| `GET` | `/runs/{id}` | One run |
| `PATCH` | `/runs/{id}` | Update `notes` / `notes_status` |
| `POST` | `/runs/{id}/diagnostics` | Generate a diagnostic draft *(no body)* |
| `GET` | `/findings` | Review queue; `?status=&source_type=` |
| `PATCH` | `/findings/{id}` | Update `text` / `status` |
| `POST` | `/agent/chat` | Ask the retrieval agent one question (stateless) |

**Status codes you'll actually hit:** `400` unparseable or empty CSV · `404`
unknown id · `409` diagnostics on a classifier, or the saved model file is
missing · `413` upload over the size cap · `422` unknown model, target,
`time_column`, tuning `persistence`, or approving empty text.

---

## 10. Configuration

Set in `.env` (see `.env.example`). Defaults shown.

| Variable | Default | What it does |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **Required** for chat, EDA, diagnostics. Not needed for training. |
| `ANTHROPIC_MODEL` | `claude-sonnet-5` | Model for the analyst call |
| `JUDGE_MODEL` | *(empty)* | Grader model; empty means use the same one |
| `VOYAGE_API_KEY` | — | **Required** for `make embed` and `/agent/chat`. Not needed for anything else. |
| `VOYAGE_MODEL` | `voyage-4` | Embedding model. Changing it invalidates the whole index — re-run `make embed`. |
| `AGENT_MAX_TURNS` | `6` | Tool-calling turns the agent may take before it must answer |
| `OTEL_ENABLED` | `false` | Export traces to the local Jaeger (port 16686) |
| `LLM_QUALITY_THRESHOLD` | `80` | Score an answer must reach (0–100) |
| `LLM_MAX_PASSES` | `3` | Cap on internal retry passes |
| `DATABASE_URL` | Postgres on `:5433` | App database |
| `MLFLOW_TRACKING_URI` | same server, `mlflow` schema | Tracking store |
| `MAX_UPLOAD_BYTES` | `52428800` (50 MB) | Upload size cap |
| `MAX_ROWS` | `1000000` | Row cap per upload |
| `CV_FOLDS` | `5` | Cross-validation folds |
| `TRAIN_TEST_SIZE` | `0.2` | Holdout fraction |
| `TRAIN_TEST_SEED` | `42` | Seed for random (non-temporal) splits |
| `OPTUNA_MAX_TRIALS` | `50` | Ceiling on `n_trials` |
| `OPTUNA_STUDY_TIMEOUT_S` | `600` | Search time limit |

Lower `LLM_MAX_PASSES` to `1` if you want fast, cheap answers and are willing
to lose the quality gate.

---

## 11. Troubleshooting

**Chat returns an error about the API key.** `ANTHROPIC_API_KEY` isn't set in
`.env`, or the backend was started before you set it. Restart `make dev`.

**The leaderboard is empty or shows no metrics.** MLflow isn't reachable. Check
`make db-up` is running and that you've run `make mlflow-init` once. The UI
degrades rather than erroring, so missing metrics look like a display bug when
they're a connection problem.

**"Port 5432 already in use."** You're not meant to use 5432 — this project
runs Postgres on **5433** specifically to coexist with a system Postgres. Check
your `DATABASE_URL`.

**Training returns 422.** Read the message: it's almost always a column name
that doesn't exist in the dataset, most often `time_column`. This is
intentional — the alternative is a silent random split on time-series data.

**Diagnostics returns 409.** Either the run is a classifier (residuals aren't
defined), or its saved model file is gone. The tool refuses to re-train a
lookalike and report it as the run you asked about.

**Scores look implausibly good on time-series data.** You almost certainly
forgot `time_column`. Re-train with it and expect the numbers to get worse and
truer.

**A model barely beats the baseline.** Check the standard deviation. On a
~224-row dataset, most "improvements" are inside the noise.

---

## 12. Limits and things it deliberately won't do

- **No accounts, no login, no data isolation.** Single-tenant by design.
- **No arbitrary code execution.** The AI picks from six fixed chart tools. It
  cannot run code you supply or invent new analyses.
- **No background jobs.** Training and tuning run inside the HTTP request. A
  long Optuna search holds the connection open; that's fine at this data size
  and would be the first thing to change at a larger one.
- **No file paths as inputs.** Data enters one way: uploaded to the `datasets`
  table. Preparing a new input means building a CSV offline and uploading it.
- **Charts aren't stored.** They're redrawn from the data and the recorded tool
  calls on every page load. (The reasoning trace is the one exception.)
- **Retrieval over past experiments doesn't exist yet.** The approval workflow
  in §7 is groundwork for it.
- **`make eval` is a stub.** It prints a message; the real grading suite is
  authored later.
