"""add two_factor_code to xui_panels

Revision ID: ea4d8b67113e
Revises: cc6484af2b44
Create Date: 2026-05-27 15:33:00.000000

"""
import sqlalchemy as sa

from alembic import op

revision = 'ea4d8b67113e'
down_revision = 'cc6484af2b44'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('xui_panels', schema=None) as batch_op:
        batch_op.add_column(sa.Column('two_factor_code_encrypted', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('xui_panels', schema=None) as batch_op:
        batch_op.drop_column('two_factor_code_encrypted')
