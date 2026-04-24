"""Fix migration chain for server paths

Revision ID: 20260325_1930
Revises: 20260325_1920
Create Date: 2026-03-25 19:30:00.000000
"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = '20260325_1930'
down_revision = '20260325_1920'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add custom path columns to servers table with defaults
    op.add_column('servers', sa.Column('panel_path', sa.String(length=500), nullable=False, server_default='/'))
    op.add_column('servers', sa.Column('subscription_path', sa.String(length=500), nullable=False, server_default='/sub'))
    op.add_column('servers', sa.Column('subscription_json_path', sa.String(length=500), nullable=False, server_default='/subjson'))


def downgrade() -> None:
    # Remove custom path columns from servers table
    op.drop_column('servers', 'subscription_json_path')
    op.drop_column('servers', 'subscription_path')
    op.drop_column('servers', 'panel_path')
