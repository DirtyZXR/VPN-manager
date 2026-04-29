"""set_null_template_fk_and_unique_telegram_id

Revision ID: a38f0cdc7e8c
Revises: 1ab520fe48a5
Create Date: 2026-04-25 15:13:17.778448

"""
from alembic import op
import sqlalchemy as sa


revision = 'a38f0cdc7e8c'
down_revision = '1ab520fe48a5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('clients', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_clients_telegram_id', ['telegram_id'])

    with op.batch_alter_table('subscriptions', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_subscriptions_template_id'), type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_subscriptions_template_id',
            'subscription_templates',
            ['template_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade() -> None:
    with op.batch_alter_table('subscriptions', schema=None) as batch_op:
        batch_op.drop_constraint('fk_subscriptions_template_id', type_='foreignkey')
        batch_op.create_foreign_key(
            batch_op.f('fk_subscriptions_template_id'),
            'subscription_templates',
            ['template_id'],
            ['id'],
            ondelete='CASCADE',
        )

    with op.batch_alter_table('clients', schema=None) as batch_op:
        batch_op.drop_constraint('uq_clients_telegram_id', type_='unique')
