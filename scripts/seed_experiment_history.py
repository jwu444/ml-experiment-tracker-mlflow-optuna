#!/usr/bin/env python3
"""Seed real experiment history (Project 2 deliverable 2.10).

Pass 1 creates one Experiment (investigation, D33) per entry in `STUDIES` via
`POST /experiments`, then runs an Optuna study inside it via
`POST /experiments/{id}/tune` — every trial that study runs is logged as a Run
under that Experiment. Pass 2 writes each run a note that says something the
structured fields do not already say — if notes only restate params, semantic
search over them is circular and Phase 4's retrieval evals measure nothing
(design §3.11).

Every note is written as a DRAFT (D20). This script has no way to approve one:
`PATCH /runs/{id}` is called with `{"notes": ...}` only, never with
`notes_status`. A human approves in ExperimentDetailPage, and Phase 3 embeds
what they approved.

Resumable: pass 1 skips a study whose Experiment already exists; pass 2 skips
any run whose notes are already non-empty. So a mid-run API failure costs only
the remaining trials/notes.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import httpx

# The script runs from the repo root, where `backend` is not on sys.path. It is
# added here rather than in a conftest because this is not a test — it is a
# stand-alone entry point that wants the app's own settings and Anthropic client
# construction rather than a second, drifting copy of either.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import settings  # noqa: E402

API = os.environ.get("API", "http://localhost:8000")

# The names `make data-fetch` uploads under.
PANEL = "revenue-nowcast.csv"
COMPONENTS = "pc-part-video-card.csv"

# Studies of two different shapes, so the history is not all one thing. Phase 3
# retrieves over this: a corpus where every run is the same kind of run gives a
# retriever nothing to discriminate on.
STUDIES: list[dict[str, Any]] = [
    # The phase's real modelling task — a temporal panel, split chronologically.
    {"dataset": PANEL, "model_type": "ridge", "target": "revenue_next_usd", "time_column": "as_of"},
    {
        "dataset": PANEL,
        "model_type": "random_forest",
        "target": "revenue_next_usd",
        "time_column": "as_of",
    },
    {
        "dataset": PANEL,
        "model_type": "gradient_boosting",
        "target": "revenue_next_usd",
        "time_column": "as_of",
    },
    # A cross-sectional contrast: no time column, so a random split.
    {"dataset": COMPONENTS, "model_type": "ridge", "target": "price", "time_column": None},
]

N_TRIALS = 8  # 4 studies × 8 = 32 runs: over the ≥20 floor, under optuna_max_trials

# A tuning study is a long synchronous request — Optuna's own budget is
# optuna_study_timeout_s, and the client must outlast it or it will hang up on a
# study the server is still running and happily writing to MLflow.
STUDY_TIMEOUT_S = settings.optuna_study_timeout_s + 120

# A note is two to four sentences — a couple of hundred tokens at most. The rest
# of this budget is headroom for the model's own reasoning, which is emitted as a
# leading `thinking` block and counts against max_tokens. Sized at 400 the reasoning
# alone exhausted the budget on the harder rows, and the response came back
# `stop_reason: max_tokens` with no text block at all.
NOTE_MAX_TOKENS = 2000

NOTE_SYSTEM = """You are reviewing one machine-learning run for a shared experiment log.

Write two to four sentences covering what this configuration appears to have
done, how it compares to the best run against the same target, and one
hypothesis about why. Write for a colleague who can already see the numbers.

Rules:
- Do NOT restate hyperparameter values. "alpha=0.025" or "alpha≈0.03" is
  already on the row; a note that repeats it adds nothing to a search over
  these notes. Describe the setting's character instead ("near-zero
  regularisation"), never its number.
- The comparator you are given is a run against the SAME target. Do not
  speculate about units or transformations to explain a gap.
- Output the note text only. No label, no heading, no "Observation:" prefix,
  no bullet points, no markdown. Do not open with "This run"."""


# `GET /experiments` caps `limit` at 200, so a single call cannot see a history
# larger than that. Asking for exactly the ceiling would look fine here (32 runs)
# and then quietly stop annotating anything past run 200 the moment the log grows
# — `SEED_FORCE_TUNE=1` adds 32 at a time. Page instead.
PAGE = 200


def fetch_experiments(client: httpx.Client) -> list[dict[str, Any]]:
    """Every experiment (investigation, D33), following the route's pagination
    to the end. Each row is an `ExperimentOut` — no `notes`, `metrics`, or
    `params`; those now live on its runs (`GET /runs`, see `fetch_runs`)."""
    rows: list[dict[str, Any]] = []
    while True:
        page = (
            client.get(f"{API}/experiments", params={"limit": PAGE, "offset": len(rows)})
            .raise_for_status()
            .json()
        )
        rows.extend(page)
        if len(page) < PAGE:
            return rows


def fetch_runs(client: httpx.Client) -> list[dict[str, Any]]:
    """Every run this script (or anyone else) has logged, following `GET /runs`'s
    pagination to the end. Each row is a `RunDetailOut` — `task_type`,
    `dataset_id`, and `dataset_version` are inherited from its parent
    Experiment (D34/D37) and merged in here by the route."""
    rows: list[dict[str, Any]] = []
    while True:
        page = (
            client.get(f"{API}/runs", params={"limit": PAGE, "offset": len(rows)})
            .raise_for_status()
            .json()
        )
        rows.extend(page)
        if len(page) < PAGE:
            return rows


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def resolve_datasets(client: httpx.Client) -> dict[str, str]:
    """Map the dataset names this script trains on to their ids."""
    datasets = client.get(f"{API}/datasets").raise_for_status().json()
    by_name = {d["name"]: d["id"] for d in datasets}
    missing = [name for name in (PANEL, COMPONENTS) if name not in by_name]
    if missing:
        fail(
            f"datasets not uploaded: {missing}. Run `make prepare-data && make data-fetch` "
            f"with the backend running (D13/D18 — training reads the `datasets` table, "
            f"never a file path)."
        )
    return by_name


def study_label(study: dict[str, Any]) -> str:
    """The Experiment name this study creates/reuses. Doubles as the underlying
    MLflow experiment name (`experiment_log.log_run` names it from
    `experiment.name`, D35), which is why `make mlflow-ui` shows this instead
    of the old `adhoc` bucket."""
    return f"{study['model_type']} on {study['dataset']}"


def run_studies(client: httpx.Client, by_name: dict[str, str]) -> int:
    """Pass 1. Returns the number of trials the API reported running.

    A run cannot exist outside an experiment (D34/D37) — there is no more
    implicit `adhoc` bucket — so each entry in `STUDIES` first gets its own
    Experiment via `POST /experiments` (reused if one with the same name
    already exists), then one Optuna study is launched inside it via
    `POST /experiments/{id}/tune`.

    Each study is skipped individually when its Experiment already exists.
    Tuning itself is the one part of this script that is NOT idempotent —
    nothing dedupes a study, so re-running it against an existing Experiment
    would silently double the history and leave the retrieval corpus full of
    near-duplicate runs. Set SEED_FORCE_TUNE=1 to add another round
    deliberately (into the *same* Experiment, not a duplicate one).
    """
    existing = {row["name"]: row for row in fetch_experiments(client)}
    trials = 0
    for study in STUDIES:
        label = study_label(study)
        experiment = existing.get(label)
        if experiment is not None and not os.environ.get("SEED_FORCE_TUNE"):
            print(
                f"  {label}: experiment already logged, skipping "
                f"(set SEED_FORCE_TUNE=1 to add another round)",
                flush=True,
            )
            continue
        print(f"tuning {label} ({N_TRIALS} trials) ...", flush=True)
        if experiment is None:
            experiment = (
                client.post(
                    f"{API}/experiments",
                    json={
                        "name": label,
                        "objective": f"Predict {study['target']!r} on {study['dataset']}.",
                        "dataset_id": by_name[study["dataset"]],
                        "target_column": study["target"],
                        "task_type": "regression",
                    },
                )
                .raise_for_status()
                .json()
            )
            existing[label] = experiment
        response = client.post(
            f"{API}/experiments/{experiment['id']}/tune",
            json={
                "model_type": study["model_type"],
                "time_column": study["time_column"],
                "n_trials": N_TRIALS,
            },
            timeout=STUDY_TIMEOUT_S,
        )
        if response.status_code != 200:
            fail(f"tuning {label} failed with {response.status_code}: {response.text}")
        body = response.json()
        done = len(body["trials"])
        # The study optimises the CROSS-VALIDATED score, so best_metrics is keyed
        # `cv_<objective>` — not `objective_metric` itself, which names the holdout
        # metric each run also records.
        objective = f"cv_{body['objective_metric']}"
        best = body["best_metrics"].get(objective)
        trials += done
        print(f"  {done} trials, best {objective}={best}", flush=True)
    return trials


def cohort(row: dict[str, Any]) -> tuple[str, str]:
    """The set of runs this one is fairly comparable against.

    Task type is not a fine enough key. An rmse and an f1_macro are not on one
    scale — but neither are two rmses against different targets: this history
    holds `revenue_next_usd` in raw dollars (rmse ~1e10) alongside component
    `price` (rmse ~400). Keying on task type alone told the note writer that a
    panel run was "eight orders of magnitude worse than the best regression
    run", and it responded by inventing a target transformation to explain the
    gap. A comparator that provokes confabulation is worse than none.
    """
    return (row["task_type"], str(row["params"].get("target_column", "")))


def best_by_cohort(rows: list[dict[str, Any]]) -> dict[tuple[str, str], tuple[str, float]]:
    """Best objective value seen per cohort, as (metric name, value)."""
    best: dict[tuple[str, str], tuple[str, float]] = {}
    for row in rows:
        metric = "rmse" if row["task_type"] == "regression" else "f1_macro"
        value = row["metrics"].get(metric)
        if value is None:
            continue
        lower_is_better = metric == "rmse"
        key = cohort(row)
        current = best.get(key)
        if (
            current is None
            or (lower_is_better and value < current[1])
            or (not lower_is_better and value > current[1])
        ):
            best[key] = (metric, value)
    return best


def describe(row: dict[str, Any], best: dict[tuple[str, str], tuple[str, float]]) -> str:
    """The user-turn context for one note: what this run was and how it placed."""
    metric = "rmse" if row["task_type"] == "regression" else "f1_macro"
    value = row["metrics"].get(metric)
    lines = [
        f"model: {row['model_type']}",
        f"task: {row['task_type']}",
        f"split: {row['params'].get('split', 'unknown')}",
        f"target: {row['params'].get('target_column', 'unknown')}",
        f"params: {row['params']}",
        f"metrics: {row['metrics']}",
    ]
    # cv_std is the honest read on whether a headline score is stable or a fold
    # artefact, so it goes in the prompt explicitly rather than buried in metrics.
    if "cv_std" in row["metrics"]:
        lines.append(f"cross-validated spread (cv_std): {row['metrics']['cv_std']}")
    reference = best.get(cohort(row))
    if reference and value is not None:
        target = row["params"].get("target_column", "the same target")
        lines.append(
            f"best {reference[0]} among runs predicting {target}: {reference[1]:.6g} "
            f"(this run: {value:.6g}, delta {value - reference[1]:+.6g})"
        )
    return "\n".join(lines)


def write_notes(client: httpx.Client, anthropic_client: Any) -> tuple[int, int]:
    """Pass 2. Returns (written, skipped). Operates on runs (`GET /runs`), not
    experiments — `task_type`/`model_type`/`params`/`metrics`/`notes` all live
    on `RunDetailOut` now (D34/D37), the same shape `cohort`/`best_by_cohort`/
    `describe` below already expect."""
    rows = fetch_runs(client)
    if not rows:
        fail("no runs to annotate — did pass 1 run?")
    if not any(row["mlflow_available"] for row in rows):
        fail("MLflow is unreachable, so there are no metrics to write notes about.")

    best = best_by_cohort(rows)
    written = skipped = 0
    for row in rows:
        if row["notes"].strip():
            skipped += 1  # resumable: an existing note is never overwritten
            continue
        message = anthropic_client.messages.create(
            model=settings.anthropic_model,
            max_tokens=NOTE_MAX_TOKENS,
            system=NOTE_SYSTEM,
            messages=[{"role": "user", "content": describe(row, best)}],
        )
        note = "".join(block.text for block in message.content if block.type == "text").strip()
        # A truncated response is rejected, not written. Testing `note` for
        # emptiness is not enough: running out of budget mid-sentence yields
        # *partial* text, which passes an emptiness check and lands a note that
        # stops mid-word. Leaving it empty keeps this pass resumable — the next
        # run retries exactly the rows that failed.
        if not note or message.stop_reason == "max_tokens":
            print(
                f"  {row['id']}: unusable response (stop_reason={message.stop_reason}, "
                f"{len(note)} chars), leaving the note empty to retry",
                flush=True,
            )
            continue
        # `{"notes": ...}` and nothing else. Sending notes_status here would make
        # the machine the approver, which is the one thing D20 forbids.
        client.patch(f"{API}/runs/{row['id']}", json={"notes": note}).raise_for_status()
        written += 1
        print(f"  {row['id']} ({row['model_type']}): {note[:70]}...", flush=True)
    return written, skipped


def main() -> None:
    if not settings.anthropic_api_key:
        fail(
            "ANTHROPIC_API_KEY is not set. Pass 2 writes the notes with Claude; "
            "copy .env.example to .env and set it there."
        )

    import anthropic

    anthropic_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    with httpx.Client(timeout=60.0) as client:
        try:
            by_name = resolve_datasets(client)
        except httpx.HTTPError as exc:
            fail(f"cannot reach the API at {API} — is `make dev` running? ({exc})")

        trials = run_studies(client, by_name)
        print(f"\npass 1 complete: {trials} new trials\n")

        written, skipped = write_notes(client, anthropic_client)

    print(
        f"\nran {trials} new trials; wrote {written} notes, skipped {skipped} that already had one."
        f"\nEvery note is a DRAFT. Phase 3 embeds approved notes only, so open /experiments, "
        f"open an experiment, and review its runs — this script cannot approve its own "
        f"output (D20)."
    )


if __name__ == "__main__":
    main()
