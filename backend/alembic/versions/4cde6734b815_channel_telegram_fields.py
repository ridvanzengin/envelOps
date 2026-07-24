"""channel telegram fields

Revision ID: 4cde6734b815
Revises: d06b1d0eef5a
Create Date: 2026-07-24 14:06:24.746382

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '4cde6734b815'
down_revision: Union[str, None] = 'd06b1d0eef5a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Autogenerate again detected the checkpoint_* tables as "removed" (see
# CLAUDE.md) -- stripped out by hand, same as every migration since the
# checkpointer's .setup() has been run against this dev DB.


def upgrade() -> None:
    op.add_column('channels', sa.Column('bot_token', sa.String(), nullable=True))
    op.add_column('channels', sa.Column('webhook_secret', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('channels', 'webhook_secret')
    op.drop_column('channels', 'bot_token')
