"""tenant behavior_config

Revision ID: f556289472b0
Revises: ae1dbe90b3a6
Create Date: 2026-07-30 13:56:38.037167

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f556289472b0'
down_revision: Union[str, None] = 'ae1dbe90b3a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Autogenerate also emitted DROP TABLE ops for checkpoints/
    # checkpoint_migrations/checkpoint_writes/checkpoint_blobs -- a known,
    # documented gotcha (CLAUDE.md): this dev DB has had LangGraph's
    # AsyncPostgresSaver.setup() run against it, and those tables aren't
    # in our SQLAlchemy metadata by design (they're LangGraph's own, not
    # Alembic-managed), so autogenerate always sees them as "removed."
    # Stripped by hand -- applying them would delete the safety-gate
    # pause/resume state. Only the real change below is intentional.
    op.add_column(
        'tenants',
        sa.Column('behavior_config', sa.JSON(), nullable=False, server_default='{}'),
    )


def downgrade() -> None:
    op.drop_column('tenants', 'behavior_config')
