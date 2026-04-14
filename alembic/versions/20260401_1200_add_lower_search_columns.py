"""Add name_lower and telegram_username_lower columns for case-insensitive search.

Revision ID: 20260401_1200
Revises: 65f261c1a3b2
Create Date: 2026-04-01 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260401_1200"
down_revision: Union[str, None] = "65f261c1a3b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new columns
    op.add_column("clients", sa.Column("name_lower", sa.String(200), nullable=True))
    op.add_column("clients", sa.Column("telegram_username_lower", sa.String(100), nullable=True))

    # Backfill existing records using SQLite LOWER() for ASCII names.
    # NOTE: SQLite LOWER() does NOT handle Cyrillic properly.
    # For databases with Cyrillic names, run a Python backfill script:
    #   from app.database import async_session_factory
    #   from app.services.client_service import ClientService
    #   async with async_session_factory() as session:
    #       result = await session.execute(select(Client))
    #       for client in result.scalars().all():
    #           client.name_lower = client.name.lower() if client.name else None
    #           client.telegram_username_lower = client.telegram_username.lower() if client.telegram_username else None
    #       await session.commit()
    op.execute("UPDATE clients SET name_lower = LOWER(name) WHERE name IS NOT NULL")
    op.execute(
        "UPDATE clients SET telegram_username_lower = LOWER(telegram_username) WHERE telegram_username IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("clients", "telegram_username_lower")
    op.drop_column("clients", "name_lower")
