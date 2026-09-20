"""Reconcile the retrieval index against what is currently approved (`make embed`).

Deliberately a script and not a route (D17): an embedding call inside
PATCH /runs/{id} would mean an approval fails when Voyage is down, turning a
local bookkeeping action into something that needs a vendor to be up.

Accepted cost: the index lags approval, and nothing detects the gap between an
approval decision and the next run of this script.
"""

import sys

from app.db import SessionLocal
from app.embeddings import backfill


def main() -> int:
    with SessionLocal() as session:
        report = backfill(session)
    print(
        f"indexed={report.indexed} reindexed={report.reindexed} "
        f"reaped={report.reaped} unchanged={report.unchanged}"
    )
    total = report.indexed + report.reindexed + report.unchanged
    if total == 0:
        print(
            "Nothing is approved yet. Approve run notes in the experiment's review "
            "dialog and findings in the findings panel, then run `make embed` again."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
