"""conversation followed_up_at

Revision ID: a35c185a3878
Revises: d06d9bc11b66
Create Date: 2026-07-27 16:03:25.693668

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a35c185a3878'
down_revision: Union[str, None] = 'd06d9bc11b66'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # checkpoint_migrations/checkpoints/checkpoint_blobs/checkpoint_writes
    # are LangGraph-managed, not Alembic-managed -- autogenerate sees them
    # as "removed" from our metadata and drafts DROP TABLEs for them.
    # Stripped by hand per the CLAUDE.md gotcha; the only real change here
    # is the new conversations.followed_up_at column.
    op.add_column('conversations', sa.Column('followed_up_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('conversations', 'followed_up_at')
