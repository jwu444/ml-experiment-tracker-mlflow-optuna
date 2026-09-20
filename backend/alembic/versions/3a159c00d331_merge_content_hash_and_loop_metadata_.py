"""merge content_hash and loop metadata heads

Revision ID: 3a159c00d331
Revises: 5d48200b8d8a, 9f3c1a7d2e40
Create Date: 2026-07-31 16:58:43.975698

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3a159c00d331'
down_revision: str | None = ('5d48200b8d8a', '9f3c1a7d2e40')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
