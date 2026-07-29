"""message audience/escalation_id, escalation blocks_pipeline

Revision ID: ae1dbe90b3a6
Revises: 0f882f29887a
Create Date: 2026-07-29 14:49:14.213247

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'ae1dbe90b3a6'
down_revision: Union[str, None] = '0f882f29887a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Autogenerate's checkpoint*-table DROP ops stripped out, see
    # CLAUDE.md's Alembic gotcha #2 (those tables are LangGraph's own, not
    # Alembic-managed). server_default backfills every existing row
    # (blocks_pipeline=True, audience="customer") rather than leaving them
    # null -- same convention as 0f882f29887a's is_test/846b477f0238's
    # closing_action.
    op.add_column(
        'escalations',
        sa.Column('blocks_pipeline', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        'messages',
        sa.Column('audience', sa.String(), nullable=False, server_default='customer'),
    )
    op.add_column('messages', sa.Column('escalation_id', sa.UUID(), nullable=True))
    # Explicit name -- op.create_foreign_key(None, ...) lets Postgres pick
    # one at create time, but downgrade's drop_constraint needs a name it
    # can actually reference, not None.
    op.create_foreign_key(
        'fk_messages_escalation_id', 'messages', 'escalations', ['escalation_id'], ['id']
    )


def downgrade() -> None:
    op.drop_constraint('fk_messages_escalation_id', 'messages', type_='foreignkey')
    op.drop_column('messages', 'escalation_id')
    op.drop_column('messages', 'audience')
    op.drop_column('escalations', 'blocks_pipeline')
