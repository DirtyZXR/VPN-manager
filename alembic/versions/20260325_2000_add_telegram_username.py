"""Add telegram_username to clients table

Revision ID: 20260325_2000
Revises: 20260325_1940
Create Date: 2026-03-25 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260325_2000'
down_revision = '20260325_1940'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add telegram_username column to clients table
    op.add_column('clients', sa.Column('telegram_username', sa.String(length=100), nullable=True))


def downgrade() -> None:
    # Remove telegram_username column from clients table
    op.drop_column('clients', 'telegram_username')
