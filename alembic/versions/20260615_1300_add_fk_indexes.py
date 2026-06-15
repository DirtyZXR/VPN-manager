"""add_fk_indexes

Add missing indexes on FK columns for tables where SQLite does not create
them automatically.  Full-table scans on FK columns become increasingly
expensive as the dataset grows.

Skipped (already covered by existing constraints/indexes):
- inbound_connections.subscription_id: covered as leading column of the
  UNIQUE constraint uq_subscription_inbound (subscription_id, inbound_id).

Revision ID: d5e6f7a8b9c0
Revises: c9d0e1f2a3b4
Create Date: 2026-06-15 13:00:00.000000

"""

from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: str | None = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_inbounds_server_id", "inbounds", ["server_id"])
    op.create_index(
        "ix_inbound_connections_inbound_id", "inbound_connections", ["inbound_id"]
    )
    op.create_index("ix_subscriptions_client_id", "subscriptions", ["client_id"])
    op.create_index(
        "ix_subscription_template_inbounds_template_id",
        "subscription_template_inbounds",
        ["template_id"],
    )
    op.create_index(
        "ix_subscription_template_inbounds_inbound_id",
        "subscription_template_inbounds",
        ["inbound_id"],
    )
    op.create_index(
        "ix_subscription_requests_client_id", "subscription_requests", ["client_id"]
    )
    op.create_index(
        "ix_subscription_requests_template_id",
        "subscription_requests",
        ["template_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_subscription_requests_template_id", "subscription_requests")
    op.drop_index("ix_subscription_requests_client_id", "subscription_requests")
    op.drop_index(
        "ix_subscription_template_inbounds_inbound_id",
        "subscription_template_inbounds",
    )
    op.drop_index(
        "ix_subscription_template_inbounds_template_id",
        "subscription_template_inbounds",
    )
    op.drop_index("ix_subscriptions_client_id", "subscriptions")
    op.drop_index(
        "ix_inbound_connections_inbound_id", "inbound_connections"
    )
    op.drop_index("ix_inbounds_server_id", "inbounds")
