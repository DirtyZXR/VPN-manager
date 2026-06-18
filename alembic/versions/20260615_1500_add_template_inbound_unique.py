"""add_template_inbound_unique

Add UNIQUE(template_id, inbound_id) to subscription_template_inbounds.
Before creating the constraint, deduplicate any existing duplicate pairs by
keeping the row with the minimum id and deleting the rest.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-06-15 15:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: remove duplicate (template_id, inbound_id) pairs, keeping the
    # row with the lowest id in each group.
    op.execute(
        sa.text(
            "DELETE FROM subscription_template_inbounds"
            " WHERE id NOT IN ("
            "  SELECT MIN(id)"
            "  FROM subscription_template_inbounds"
            "  GROUP BY template_id, inbound_id"
            ")"
        )
    )

    # Step 2: create the UNIQUE constraint via batch_alter_table (required by
    # SQLite which does not support ALTER TABLE ADD CONSTRAINT directly).
    with op.batch_alter_table("subscription_template_inbounds", schema=None) as batch_op:
        batch_op.create_unique_constraint("uq_template_inbound", ["template_id", "inbound_id"])


def downgrade() -> None:
    with op.batch_alter_table("subscription_template_inbounds", schema=None) as batch_op:
        batch_op.drop_constraint("uq_template_inbound", type_="unique")
