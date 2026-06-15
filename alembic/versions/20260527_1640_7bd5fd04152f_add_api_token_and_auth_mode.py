"""add api_token and auth_mode to xui_panels

Revision ID: 7bd5fd04152f
Revises: ea4d8b67113e
Create Date: 2026-05-27 16:40:00.000000

"""
import sqlalchemy as sa

from alembic import op

revision = '7bd5fd04152f'
down_revision = 'ea4d8b67113e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('xui_panels', schema=None) as batch_op:
        batch_op.add_column(sa.Column('api_token_encrypted', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('auth_mode', sa.String(length=20), nullable=False, server_default='credentials'))


def downgrade() -> None:
    with op.batch_alter_table('xui_panels', schema=None) as batch_op:
        batch_op.drop_column('auth_mode')
        batch_op.drop_column('api_token_encrypted')
