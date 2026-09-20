"""add loop metadata to chat_messages (issue #9)

Revision ID: 9f3c1a7d2e40
Revises: f280d48505b3
Create Date: 2026-07-29

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "9f3c1a7d2e40"
down_revision = "f280d48505b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_messages", sa.Column("pass_count", sa.Integer(), nullable=True), schema="app"
    )
    op.add_column(
        "chat_messages", sa.Column("judge_score", sa.Integer(), nullable=True), schema="app"
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "judge_score", schema="app")
    op.drop_column("chat_messages", "pass_count", schema="app")
