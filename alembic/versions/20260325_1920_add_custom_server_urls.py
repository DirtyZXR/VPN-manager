"""Add custom URLs for server panel and subscriptions

Revision ID: 20260325_1920
Revises: 20260325_1710
Create Date: 2026-03-25 19:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260325_1920'
down_revision = '20260325_1710'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add custom URL columns to servers table
    op.add_column('servers', sa.Column('panel_url', sa.String(length=500), nullable=True))
    op.add_column('servers', sa.Column('subscription_url', sa.String(length=500), nullable=True))
    op.add_column('servers', sa.Column('subscription_json_url', sa.String(length=500), nullable=True))


def downgrade() -> None:
    # Remove custom URL columns from servers table
    op.drop_column('servers', 'subscription_json_url')
    op.drop_column('servers', 'subscription_url')
    op.drop_column('servers', 'panel_url')
