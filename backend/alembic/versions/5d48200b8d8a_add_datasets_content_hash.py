"""add datasets.content_hash

Revision ID: 5d48200b8d8a
Revises: f280d48505b3
Create Date: 2026-07-26 14:19:57.480337

"""
import hashlib
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '5d48200b8d8a'
down_revision: str | None = 'f280d48505b3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add the column nullable so existing rows don't violate NOT NULL yet.
    op.add_column(
        "datasets",
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        schema="app",
    )
    # 2. Backfill from the stored CSV text. Best-effort: the original raw bytes
    #    are gone, so this hashes the decoded text — see the design doc caveat.
    #    No-op on an empty table.
    #
    #    Pre-existing rows may already contain byte-identical `data_csv` —
    #    exactly the duplicate-upload mess this feature is meant to clean up.
    #    Two such rows would hash to the same value, and step 4's unique
    #    constraint would then abort the whole migration. So before setting
    #    content_hash, collapse identical-content duplicates down to a single
    #    surviving row: keep the earliest (by created_at, then id as a
    #    tiebreaker) and delete the rest. Only the survivor gets hashed.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, data_csv FROM app.datasets ORDER BY created_at, id")
    ).fetchall()
    seen_hashes: dict[str, str] = {}
    for row in rows:
        digest = hashlib.sha256(row.data_csv.encode("utf-8")).hexdigest()
        if digest in seen_hashes:
            # A later row with identical content to one already processed —
            # drop it so the unique constraint can be created below.
            bind.execute(
                sa.text("DELETE FROM app.datasets WHERE id = :id"),
                {"id": row.id},
            )
            continue
        seen_hashes[digest] = row.id
        bind.execute(
            sa.text("UPDATE app.datasets SET content_hash = :h WHERE id = :id"),
            {"h": digest, "id": row.id},
        )
    # 3. Enforce NOT NULL now that every row has a value.
    op.alter_column(
        "datasets", "content_hash",
        existing_type=sa.String(length=64), nullable=False, schema="app",
    )
    # 4. Uniqueness (its backing index also serves dedup lookups).
    op.create_unique_constraint(
        "uq_datasets_content_hash", "datasets", ["content_hash"], schema="app"
    )


def downgrade() -> None:
    op.drop_constraint("uq_datasets_content_hash", "datasets", schema="app", type_="unique")
    op.drop_column("datasets", "content_hash", schema="app")
