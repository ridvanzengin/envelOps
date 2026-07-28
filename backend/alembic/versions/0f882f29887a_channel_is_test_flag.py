"""channel is_test flag

Revision ID: 0f882f29887a
Revises: a35c185a3878
Create Date: 2026-07-28 15:20:06.717722

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0f882f29887a'
down_revision: Union[str, None] = 'a35c185a3878'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default backfills existing rows (the real Telegram channel) to
    # False, not null -- autogenerate's checkpoint*-table DROP ops stripped
    # out, see CLAUDE.md's Alembic gotcha #2 (those tables are LangGraph's
    # own, not Alembic-managed).
    op.add_column(
        'channels',
        sa.Column('is_test', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('channels', 'is_test')
