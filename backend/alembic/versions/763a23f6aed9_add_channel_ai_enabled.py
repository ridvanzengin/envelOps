"""add channel ai_enabled

Revision ID: 763a23f6aed9
Revises: f556289472b0
Create Date: 2026-08-03 14:45:03.767651

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '763a23f6aed9'
down_revision: Union[str, None] = 'f556289472b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Server default backfills existing rows to True (default is on for
    # every channel, existing and new), then the column is left with the
    # same default going forward for future inserts via the model.
    op.add_column(
        'channels',
        sa.Column('ai_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column('channels', 'ai_enabled')
