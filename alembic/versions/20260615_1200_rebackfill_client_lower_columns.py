"""rebackfill_client_lower_columns

Re-backfill clients.name_lower and clients.telegram_username_lower using
Python's str.lower() which correctly handles Cyrillic, unlike SQLite LOWER().

The original migration (20260401_1200) used SQLite LOWER() which silently
no-ops on non-ASCII characters, leaving Cyrillic names in mixed case.

This migration is idempotent: running it twice produces the same result.

Revision ID: c9d0e1f2a3b4
Revises: b2f3a4c5d6e7
Create Date: 2026-06-15 12:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: str | None = "b2f3a4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    rows = bind.execute(
        sa.text("SELECT id, name, telegram_username FROM clients")
    ).fetchall()

    for row in rows:
        row_id, name, tg_username = row[0], row[1], row[2]

        name_lower = name.lower() if name else None
        tg_lower = tg_username.lower() if tg_username else None

        bind.execute(
            sa.text(
                "UPDATE clients"
                " SET name_lower = :name_lower, telegram_username_lower = :tg_lower"
                " WHERE id = :id"
            ),
            {"name_lower": name_lower, "tg_lower": tg_lower, "id": row_id},
        )


def downgrade() -> None:
    # No-op: the corrected lowercase values are strictly better than the
    # SQLite LOWER() output.  Rolling back would re-introduce broken data.
    pass
