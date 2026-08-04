"""add fake commerce products

Revision ID: 81b56f2ca1c6
Revises: 763a23f6aed9
Create Date: 2026-08-04 15:15:04.603441

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '81b56f2ca1c6'
down_revision: Union[str, None] = '763a23f6aed9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('fake_commerce_products',
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('size', sa.String(), nullable=True),
    sa.Column('in_stock', sa.Boolean(), nullable=False),
    sa.Column('quantity_available', sa.Integer(), nullable=True),
    sa.Column('restock_eta_days', sa.Integer(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_fake_commerce_products_tenant_id'), 'fake_commerce_products', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_fake_commerce_products_tenant_id'), table_name='fake_commerce_products')
    op.drop_table('fake_commerce_products')
