"""add pending_divergences table

Revision ID: a7d1e2f3b4c5
Revises: f2a3b4c5d6e7
Create Date: 2026-06-22 12:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "a7d1e2f3b4c5"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pending_divergences",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("server_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("batch_id", sa.String(length=16), nullable=False),
        sa.Column("notify_message_refs", sa.JSON(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_pending_divergences_server_id", "pending_divergences", ["server_id"]
    )
    op.create_index(
        "ix_pending_divergences_status", "pending_divergences", ["status"]
    )
    op.create_index(
        "ix_pending_divergences_batch_id", "pending_divergences", ["batch_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_pending_divergences_batch_id", table_name="pending_divergences")
    op.drop_index("ix_pending_divergences_status", table_name="pending_divergences")
    op.drop_index("ix_pending_divergences_server_id", table_name="pending_divergences")
    op.drop_table("pending_divergences")
