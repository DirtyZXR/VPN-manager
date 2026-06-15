"""normalize_expiry_tz

Normalise existing expiry_date values in subscriptions and inbound_connections
to UTC-aware TEXT format (``YYYY-MM-DD HH:MM:SS.ffffff+00:00``).

SQLite stores DateTime columns as TEXT.  When SQLAlchemy reads a row whose
text does NOT include a UTC offset it returns a naive datetime regardless of
``DateTime(timezone=True)``.  Appending ``+00:00`` makes aiosqlite/SQLite
return the value as an aware datetime, so model properties no longer need to
guess the timezone of stored data.

The upgrade is idempotent: rows that already contain a ``+`` offset are left
untouched.  NULL values are skipped.

Downgrade is a no-op with a comment: the ``+00:00``-suffixed values are still
valid ISO-8601 strings and all application code calls ``ensure_utc()`` which
handles both aware and naive inputs, so a rollback of *this migration only*
does not break anything.

Revision ID: e1f2a3b4c5d6
Revises: d5e6f7a8b9c0
Create Date: 2026-06-15 14:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None

_TABLES = ("subscriptions", "inbound_connections")


def _normalize_table(bind: sa.engine.Connection, table: str) -> int:
    """Add +00:00 suffix to all naive expiry_date TEXT values in *table*.

    Returns the count of rows updated.
    """
    rows = bind.execute(
        sa.text(f"SELECT id, expiry_date FROM {table} WHERE expiry_date IS NOT NULL")  # noqa: S608
    ).fetchall()

    updated = 0
    for row_id, raw in rows:
        if raw is None:
            continue
        raw_str: str = str(raw)
        # Already aware (contains a timezone marker)
        if "+" in raw_str or raw_str.endswith("Z"):
            continue
        # Strip trailing whitespace just in case
        raw_str = raw_str.strip()
        # Append UTC offset
        normalised = raw_str + "+00:00"
        bind.execute(
            sa.text(f"UPDATE {table} SET expiry_date = :val WHERE id = :id"),  # noqa: S608
            {"val": normalised, "id": row_id},
        )
        updated += 1

    return updated


def upgrade() -> None:
    bind = op.get_bind()
    for table in _TABLES:
        count = _normalize_table(bind, table)
        print(f"[normalize_expiry_tz] {table}: updated {count} rows")


def downgrade() -> None:
    # No-op: rows with +00:00 suffix are valid ISO-8601 datetimes.
    # All application code uses ensure_utc() which handles both naive and
    # aware inputs, so rolling back this migration alone is safe.
    pass
