"""Mako template for migration scripts."""

"""Add subscription requests

Revision ID: 9aa631a1d506
Revises: 80d3830a3271
Create Date: 2026-04-17 13:11:54.191868

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9aa631a1d506"
down_revision = "80d3830a3271"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscription_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("requested_name", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["template_id"], ["subscription_templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # 2. Add is_public with default value to avoid NOT NULL constraint failure
    with op.batch_alter_table("subscription_templates") as batch_op:
        batch_op.add_column(
            sa.Column("is_public", sa.Boolean(), server_default=sa.text("0"), nullable=False)
        )

    # 3. Drop is_unlimited from subscriptions if needed
    with op.batch_alter_table("subscriptions") as batch_op:
        batch_op.drop_column("is_unlimited")


def downgrade() -> None:
    with op.batch_alter_table("subscriptions") as batch_op:
        batch_op.add_column(
            sa.Column("is_unlimited", sa.BOOLEAN(), server_default=sa.text("'0'"), nullable=False)
        )

    with op.batch_alter_table("subscription_templates") as batch_op:
        batch_op.drop_column("is_public")

    op.drop_table("subscription_requests")
