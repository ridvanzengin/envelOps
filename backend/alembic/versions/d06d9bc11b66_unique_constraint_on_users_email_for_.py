"""unique constraint on users email for login lookup

Revision ID: d06d9bc11b66
Revises: 4cde6734b815
Create Date: 2026-07-27 14:11:45.925386

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd06d9bc11b66'
down_revision: Union[str, None] = '4cde6734b815'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # checkpoint_migrations/checkpoints/checkpoint_blobs/checkpoint_writes
    # are LangGraph-managed, not Alembic-managed -- autogenerate sees them
    # as "removed" from our metadata and drafts DROP TABLEs for them.
    # Stripped by hand per the CLAUDE.md gotcha; the only real change here
    # is the users.email index becoming unique.
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=False)
