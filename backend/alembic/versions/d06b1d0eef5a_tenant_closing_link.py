"""tenant closing_link

Revision ID: d06b1d0eef5a
Revises: 846b477f0238
Create Date: 2026-07-24 11:41:09.110283

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd06b1d0eef5a'
down_revision: Union[str, None] = '846b477f0238'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Autogenerate also detected the checkpoint_* tables (LangGraph's own,
# created by AsyncPostgresSaver.setup() -- see CLAUDE.md) as "removed",
# since they're not in our SQLAlchemy metadata by design. Those DROP
# TABLE/DROP INDEX ops have been stripped from this migration by hand --
# applying them would have deleted the safety-gate pause/resume state.
# Expect this every time autogenerate runs after .setup() has run against
# the same dev DB; always check for it, don't apply blind.


def upgrade() -> None:
    op.add_column('tenants', sa.Column('closing_link', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('tenants', 'closing_link')
