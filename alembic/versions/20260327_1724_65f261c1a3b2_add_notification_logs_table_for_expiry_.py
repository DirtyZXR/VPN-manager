"""Mako template for migration scripts."""

"""add notification_logs table for expiry and traffic warnings

Revision ID: 65f261c1a3b2
Revises: 227475f1f48c
Create Date: 2026-03-27 17:24:46.295361

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '65f261c1a3b2'
down_revision = '227475f1f48c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create notification_logs table
    op.create_table(
        'notification_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('notification_type', sa.String(length=20), nullable=False),
        sa.Column('level', sa.String(length=20), nullable=False),
        sa.Column('group_key', sa.String(length=64), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['clients.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes
    op.create_index('ix_notification_logs_user_id', 'notification_logs', ['user_id'])
    op.create_index('ix_notification_logs_group_key', 'notification_logs', ['group_key'])
    op.create_index('ix_notification_logs_sent_at', 'notification_logs', ['sent_at'])
    op.create_index('idx_notification_logs_user_type', 'notification_logs', ['user_id', 'notification_type'])
    op.create_index('idx_notification_logs_user_type_level', 'notification_logs', ['user_id', 'notification_type', 'level'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('idx_notification_logs_user_type_level', 'notification_logs')
    op.drop_index('idx_notification_logs_user_type', 'notification_logs')
    op.drop_index('ix_notification_logs_sent_at', 'notification_logs')
    op.drop_index('ix_notification_logs_group_key', 'notification_logs')
    op.drop_index('ix_notification_logs_user_id', 'notification_logs')

    # Drop table
    op.drop_table('notification_logs')
