#!/usr/bin/env bash
# Ingest the datasets Project 2 trains on into the `datasets` table (design
# D13/D18). Everything uploaded here is a committed file under `data-sources/`:
# no network access, so a checkout pins the exact training input.
#
# Static snapshots only — §2.1 rules out scraping PCPartPicker/Newegg/Amazon.
set -euo pipefail

API="${API:-http://localhost:8000}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)/data-sources"

upload() {  # upload <path> <name-in-datasets>
  if [ ! -f "$1" ]; then
    echo "Missing $1 — run 'make prepare-data', or is data-sources/ checked out?" >&2
    exit 1
  fi
  echo "Uploading $2 ..."
  # The upload endpoint is idempotent on a SHA-256 of the content, so re-running
  # this script returns the existing row instead of creating a duplicate.
  # --fail-with-body: without it curl exits 0 on a 4xx/5xx and pipes the error
  # JSON into python, which dies on a missing key — so a "dataset too large" or
  # "backend not running" turns into a KeyError traceback instead of the reason.
  local body
  if ! body=$(curl -sS --fail-with-body -X POST "${API}/datasets" -F "file=@$1;filename=$2"); then
    echo "  upload of $2 failed: ${body:-no response from ${API}}" >&2
    exit 1
  fi
  printf '%s' "$body" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("  %s: id=%s rows=%s cols=%s" % (d["name"], d["id"], d["n_rows"], d["n_cols"]))'
}

# The prepared modelling panel (D18) — what Phase 2a trains on.
upload "${ROOT}/prepared/revenue_nowcast.csv" "revenue-nowcast.csv"

# Phase 1's component tables, kept as a second, non-temporal dataset.
for part in video-card cpu; do
  upload "${ROOT}/pc-part-dataset/${part}.csv" "pc-part-${part}.csv"
done
