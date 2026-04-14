"""Add session cookies storage to servers

Revision ID: 20260325_1710
Revises: 1800_add_verify_ssl
Create Date: 2026-03-25 17:10:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260325_1710'
down_revision = '1800_add_verify_ssl'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add session cookies storage fields to servers table
    op.add_column('servers', sa.Column('session_cookies_encrypted', sa.Text(), nullable=True))
    op.add_column('servers', sa.Column('session_created_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    # Remove session cookies storage fields from servers table
    op.drop_column('servers', 'session_created_at')
    op.drop_column('servers', 'session_cookies_encrypted')
