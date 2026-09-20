"""Curate the retrieval corpus (D45).

Two modes:

    python scripts/apply_curation.py --plan    # read the API, write curation.yaml
    python scripts/apply_curation.py           # apply curation.yaml through the API

The manifest is committed so the corpus is REPRODUCIBLE from a clean database.
The golden set (D43) is keyed to these ids, so a corpus nobody can rebuild is a
golden set nobody can check.

Selection is by OUTCOME DIVERSITY, never by note quality: best, worst, and
evenly spaced middles within each (experiment, model) stratum. Approving the
well-written notes instead would build an unrepresentatively clean corpus —
every retrieval number measured against it optimistic in a way nothing about
the number reveals — and would delete the failures, which are the half of the
history the agent most needs in order to recommend against repeating them.

Everything goes through the API (D13); this script never touches the database.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

API = os.environ.get("API", "http://localhost:8000")
MANIFEST = Path(__file__).resolve().parents[1] / "backend" / "eval" / "curation.yaml"

# GET /runs and GET /findings both cap `limit` at 200 (Query(..., ge=1, le=200)).
# The corpus is ~32 runs and ~40 findings, well under that cap, so a single page
# is ample headroom — pagination machinery for a case that does not exist yet
# would be the untested, unexercised kind. The guard below is the point: if a
# response ever comes back holding exactly PAGE_LIMIT rows, more may exist and
# this fetch would silently truncate them rather than error.
PAGE_LIMIT = 200

# How many notes to approve per (experiment, model) stratum. 17 of 34 (D45).
# Both persistence runs: D25 makes the baseline a real logged run precisely so
# it anchors comparisons, and a corpus without it cannot answer "what is the
# baseline" — the question the baseline exists to make answerable.
QUOTAS: dict[tuple[str, str], int] = {
    ("revenue-nowcast", "ridge"): 4,
    ("revenue-nowcast", "random_forest"): 4,
    ("revenue-nowcast", "gradient_boosting"): 4,
    ("revenue-nowcast", "persistence"): 2,
    ("pc-part-video-card", "ridge"): 3,
}
DEFAULT_QUOTA = 2


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def spread_indices(n: int, quota: int) -> list[int]:
    """Positions to approve in a metric-sorted stratum of size `n`.

    Always includes index 0 (best) and n-1 (worst), with the remainder spread
    evenly between. Taking the top `quota` instead would delete every failure
    from the corpus.
    """
    if n <= 0 or quota <= 0:
        return []
    if quota >= n:
        return list(range(n))
    if quota == 1:
        return [0]
    step = (n - 1) / (quota - 1)
    return sorted({round(i * step) for i in range(quota)})


def build_manifest(runs: list[dict[str, Any]], findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Every run appears exactly once, approved or rejected with a reason —

    with one deliberate exception. A run the quota assigns to APPROVAL whose
    note is empty or whitespace-only is SKIPPED instead (neither approved nor
    rejected): D20 forbids approving an empty note (`PATCH /runs/{id}` 422s
    on it), so approving one here would abort `apply_manifest` partway
    through — the half-applied manifest this module's docstring warns about.
    It is a seeding gap, not a curation decision, so it is warned about
    (naming the run id) rather than silently rejected in its place — that
    would swap a run the quota meant to include for a decision nobody made,
    and quietly shrink the corpus the eval measures.

    An empty note is NOT a reason to skip a run the quota assigns to
    REJECTION: D20 permits rejecting an empty note (only approval 422s on
    it), so that run keeps its ordinary reject decision. Skipping it too
    would leave it a draft forever with no later step to resolve it — the
    exact failure this function's docstring otherwise warns about.

    Otherwise: a run left out of the manifest stays a draft forever and is
    silently absent from the corpus — invisible, because nothing errors.
    """
    strata: dict[tuple[str, str], list[dict[str, Any]]] = {}
    unrankable: list[dict[str, Any]] = []
    for run in runs:
        metric = _primary_metric(run)
        if metric is None:
            unrankable.append(run)
            continue
        strata.setdefault((run["experiment_name"], run["model_type"]), []).append(run)

    entries: list[dict[str, Any]] = []
    for (experiment_name, model_type), group in sorted(strata.items()):
        group.sort(key=lambda r: (_primary_metric(r), r["id"]))
        quota = QUOTAS.get((experiment_name, model_type), DEFAULT_QUOTA)
        picks = set(spread_indices(len(group), quota))
        for position, run in enumerate(group):
            if position in picks:
                notes = run.get("notes")
                if notes is not None and not notes.strip():
                    print(f"warning: {run['id']} skipped — its note is empty", file=sys.stderr)
                    continue
                where = (
                    "best" if position == 0 else "worst" if position == len(group) - 1 else "mid"
                )
                reason = (
                    f"{experiment_name}/{model_type}: {where} of {len(group)} by holdout metric"
                )
                entries.append({"id": run["id"], "decision": "approved", "reason": reason})
            else:
                entries.append(
                    {
                        "id": run["id"],
                        "decision": "rejected",
                        "reason": (
                            f"{experiment_name}/{model_type}: outside the "
                            f"{quota}-of-{len(group)} outcome-diversity sample"
                        ),
                    }
                )
    for run in unrankable:
        entries.append(
            {
                "id": run["id"],
                "decision": "rejected",
                "reason": "no holdout metric; cannot be placed in its stratum",
            }
        )

    return {
        "runs": entries,
        # All six findings: each is a distinct source about a distinct thing,
        # and the three eda ones are the only route to dataset-level questions
        # (D30 expands every matching run to an ("eda", dataset_id) key).
        # Sorted by id: the API's return order is not guaranteed stable, and an
        # unsorted manifest would differ byte-for-byte between two --plan runs
        # over an identical corpus, which is the opposite of D45's point.
        "findings": [
            {"id": f["id"], "decision": "approved", "reason": "distinct source; no redundancy"}
            for f in sorted(findings, key=lambda f: f["id"])
        ],
    }


def _primary_metric(run: dict[str, Any]) -> float | None:
    metrics = run.get("metrics") or {}
    for name in ("rmse", "mae", "accuracy"):
        if name in metrics:
            return float(metrics[name])
    return None


def apply_manifest(manifest: dict[str, Any], client: Any) -> tuple[int, int]:
    """PATCH every entry. Returns (approved, rejected).

    Sends ONLY the status field. Writing text through PATCH /runs is
    deliberately not an approval (D20); sending both would let the curation
    rewrite the corpus it is supposed to be selecting from.

    A failed PATCH raises. A half-applied manifest is a corpus that does not
    match its own committed file, and failing loudly is the only way that gets
    noticed before it silently becomes the eval's ground truth.
    """
    approved = rejected = 0
    for entry in manifest.get("runs", []):
        _patch(client, f"/runs/{entry['id']}", {"notes_status": entry["decision"]})
        approved += entry["decision"] == "approved"
        rejected += entry["decision"] == "rejected"
    for entry in manifest.get("findings", []):
        _patch(client, f"/findings/{entry['id']}", {"status": entry["decision"]})
        approved += entry["decision"] == "approved"
        rejected += entry["decision"] == "rejected"
    return approved, rejected


def _patch(client: Any, url: str, payload: dict[str, Any]) -> None:
    response = client.patch(url, json=payload)
    if response.status_code >= 400:
        raise RuntimeError(f"PATCH {url} returned {response.status_code}: {response.text}")


def _plan(client: httpx.Client) -> None:
    experiments = client.get("/experiments").json()
    names = {e["id"]: e["name"] for e in experiments}
    runs = client.get("/runs", params={"limit": PAGE_LIMIT}).json()
    if len(runs) == PAGE_LIMIT:
        fail(
            f"GET /runs returned exactly {PAGE_LIMIT} rows, the route's page cap — "
            f"the corpus has outgrown a single page and this fetch may be silently "
            f"truncated. This script does not paginate; add pagination before "
            f"running --plan again."
        )
    for run in runs:
        run["experiment_name"] = names.get(run["experiment_id"], "?")
    findings = client.get("/findings", params={"limit": PAGE_LIMIT}).json()
    if len(findings) == PAGE_LIMIT:
        fail(
            f"GET /findings returned exactly {PAGE_LIMIT} rows, the route's page cap — "
            f"the corpus has outgrown a single page and this fetch may be silently "
            f"truncated. This script does not paginate; add pagination before "
            f"running --plan again."
        )

    manifest = build_manifest(runs, findings)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(yaml.safe_dump(manifest, sort_keys=False))
    approved = sum(1 for e in manifest["runs"] if e["decision"] == "approved")
    print(f"wrote {MANIFEST} — {approved} of {len(manifest['runs'])} notes approved, ")
    print(f"and all {len(manifest['findings'])} findings. Review it before applying.")


def main() -> None:
    plan = "--plan" in sys.argv
    with httpx.Client(base_url=API, timeout=60.0) as client:
        try:
            if plan:
                _plan(client)
                return
            if not MANIFEST.exists():
                fail(f"{MANIFEST} does not exist; run with --plan first")
            manifest = yaml.safe_load(MANIFEST.read_text())
            approved, rejected = apply_manifest(manifest, client)
        except httpx.HTTPError as exc:
            fail(f"cannot reach the API at {API} — is `make dev` running? ({exc})")
    print(
        f"applied: {approved} approved, {rejected} rejected.\n"
        f"The index is NOT updated by this script (D17) — run `make embed` next."
    )


if __name__ == "__main__":
    main()
