"""add_ssh_host_key_to_servers

Revision ID: a1b2c3d4e5f6
Revises: 7bd5fd04152f
Create Date: 2026-06-15 10:00:00.000000

"""
import sqlalchemy as sa

from alembic import op

revision = 'a1b2c3d4e5f6'
down_revision = '7bd5fd04152f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('servers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ssh_host_key', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('servers', schema=None) as batch_op:
        batch_op.drop_column('ssh_host_key')
