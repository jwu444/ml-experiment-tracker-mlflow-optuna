# Project 2 — Comments on the Phases 2–4 Design (for student revision)

**Reviewed:** `doc/plans/2026-08-10-project-2-phases-2-4-design.md` and
`doc/plans/2026-08-10-project-2-phase-2-training-mlflow-optuna.md`, both on
`docs/phases-2-4-design` (branched from Phase 1's `730fe46`).

**Purpose of this doc:** this is mentor feedback, not a design doc itself. It's the
combined instruction for the student to iterate on the two docs above before any
Phase 2 code is written.

---

## Context and priority

This program is building two skillsets: (1) data science — ML/AI, data analysis,
modeling, visualization, presentation, which is the student's core competency; and
(2) AI enablement — using Claude Code to brainstorm/design/plan/build/test/deliver,
which is the enabler, not the point. Phase 2 is the phase that should carry the core
DS skill-building; Phase 3's retrieval/agent work is a helper on top of it. The
current draft optimizes Phase 2 toward "produce MLflow rows fast enough to seed
Phase 3" rather than toward a real collect → analyze → hypothesize → experiment →
eval → tune loop. Revise both docs against the points below, keeping the existing
`D#` decision-log format (add new decisions, amend existing ones, keep the
"Rejected: ..." style where relevant), then bring the revision back before writing
any code.

---

## 1. Amend D12 — use the exploratory question candidates, do both task types

Replace the current "cross-sectional regression only, temporal deferred" scoping
with a two-model sequence drawn from `README.md`'s "Exploratory ML question
candidates":

- **Regression, first:** candidate #4 (company revenue nowcasting) — dense labels,
  no null-target fighting, proves the training/tuning pipeline while it's still new.
- **Classification, second:** candidate #1 or #3 (supply-shock or macro/demand →
  price direction, up/down/flat) — this restores the parent design's actual driving
  question instead of permanently retiring it, and gives a real classification
  exercise, not a toy one.
- Candidate #2 (consumer-signal lead/lag) isn't a clean supervised target as
  written — either drop it or reframe it as a specific classification/regression
  target before treating it as a third model.
- Update §1's background facts (the "80.8%/61.3% null" framing anchored to
  `video-card.csv`) to reflect that the pipeline-proving exercise no longer depends
  on that dataset.

## 2. New decision — data joining (a real architecture gap, not a detail)

Every one of #1/#3/#4 requires joining ≥2 `data-sources/` CSVs on a date key
(price/revenue + macro/supply signal) before there's a single trainable frame. The
current D13 ("training.py never touches the filesystem, one `dataset_id` per
request") has no join step anywhere. Resolve this explicitly: the low-risk option
is an offline join script that produces one wide CSV per candidate and uploads it
through the existing `/datasets` endpoint unchanged — not a multi-dataset training
architecture (that's more machinery than this needs, and duplicates Project 1's
`chat_datasets` pattern for a different purpose). Add this as its own task in the
Phase 2 plan, not a sub-bullet of an existing one.

## 3. Amend §3.2/§3.4 (`training.py` interfaces, model registry) — task-type generalization

The plan already flags this as deliberately deferred ("no per-model-type direction
flag... adding a maximizing metric means adding one, deliberately") — that moment
is now, given both task types are in scope:

- `MODEL_REGISTRY` needs a `task_type` per entry (or a parallel classifier
  registry) with classifier counterparts (e.g. `LogisticRegression`,
  `RandomForestClassifier`, `GradientBoostingClassifier`).
- `TrainResult.metrics` needs a classification metric set (accuracy/f1/roc_auc)
  alongside rmse/mae/r2.
- `cv_objective`'s scoring and Optuna's `direction` need to vary by task type
  (classification metrics maximize; RMSE minimizes) — no more hardcoded
  `direction="minimize"`.
- Candidates #1/#3 need a **label-engineering step**: "price direction" isn't a raw
  column, it's derived from the joined time series (e.g.
  `sign(price[t+1] - price[t])`). Specify where this lives — most naturally as part
  of the join script from point 2, so `training.py` still just sees a target column
  that already exists.

## 4. New task — EDA + diagnostics, reusing Project 1's loop, not new machinery

Add an explicit EDA pass before modeling and a diagnostics pass after, both built on
the existing judge-gated analyst loop (`app/loop.py` + `app/analysis.py`/
`app/charts.py`) rather than a new agent:

- EDA: new tool schemas as needed, run once per joined training frame, before any
  model exists.
- Diagnostics: new tool schemas — predicted-vs-actual, residuals, feature
  importance, confusion matrix/ROC for the classifier — run per completed
  experiment.
- Surface both in `ExperimentsPage` (an "explore this dataset" / "explain this run"
  panel), which currently (§3.10/Task 8) is metrics-table-only.
- This is the concrete fix for the "visualization and presentation" skill gap — not
  optional polish.

## 5. New decision — HITL gate on every LLM-authored text before it's persisted or embedded

Both the experiment notes (§3.11/Task 9) and the new EDA/diagnostic
interpretations from point 4 are Claude-authored. None of it gets embedded (or,
ideally, even committed to the DB as final) without the student reviewing and
approving it first. Concretely: the seeding/enrichment step becomes two-stage —
write proposed text to a reviewable state, student approves/edits, *then* persist
via `PATCH`. This is what keeps the "identify pattern, form hypothesis" step
actually his rather than fully delegated.

## 6. Amend D6/D14/D15 — RAG content scope, finalized

Three-plus-one content types, no others. Explicitly rule out embedding external
tech/business/economic articles for style/tone grounding — considered and
rejected: it conflates fact-retrieval with style-grounding, isn't measurable
against the Phase 4 eval harness (precision@k/recall@k/MRR is scoped to known-
relevant *experiments*, not prose quality), and is disproportionate AI-engineering
surface relative to Phase 2's DS payoff. If domain grounding (not style) is ever
wanted later — e.g. referencing the real 2022 crypto-mining demand collapse when
explaining a price-direction result — that would need its own narrow, licensed,
separately-indexed source tied to a stated way of measuring whether it improves
correctness, not just readability.

| Content | Keyed by | Gate |
|---|---|---|
| Experiment notes | `experiment_id` | HITL-approved |
| EDA findings | `dataset_id` | HITL-approved |
| Diagnostic interpretations | `experiment_id` | HITL-approved |
| Research-question candidates (the 5 README entries, moved into a small table) | none (global) | static, embed once |

Schema consequence: `experiment_note_chunks`'s hard FK to `experiment_id` needs to
generalize to `source_type` + `source_id` (validated in code, not a DB FK) to
support the four content types above. Update §7's column spec and the Phase 3
module boundaries (§4) accordingly. Structured fields (params/metrics/model_type/
dataset/status) stay out of the vector index — D15's SQL/MLflow pre-filter stage is
unchanged.

## 7. Fix before implementation, independent of the rescoping

Task 3's `infer_feature_columns` reads `col.get("n_unique")` from the stored
profile, but `profile_dataframe()` (`backend/app/profiler.py`) doesn't currently
emit `n_unique` at all — only `name`/`dtype`/`n_null`. As written, every
categorical feature would be silently dropped. Add an explicit sub-step to Task 3
that updates the profiler to include cardinality (and note the token-budget
impact, since `CLAUDE.md` treats the profiler's field set as deliberately
reviewed), rather than discovering this mid-implementation.

---

## Definition of done for this revision pass

Both docs updated with the amended/new `D#` decisions above, the Phase 2 task list
re-sequenced to include the join step, the dual-task-type training core, the
EDA/diagnostics task, and the HITL review mechanism — then back for a second read
before any code gets written.
