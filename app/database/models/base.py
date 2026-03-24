"""Base model class for SQLAlchemy models."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, func, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


class TimestampMixin:
    """Mixin for created_at and updated_at timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SyncMixin:
    """Mixin for synchronization tracking fields."""

    sync_status: Mapped[str] = mapped_column(
        String(20),
        default="synced",
        nullable=False,
    )  # "synced", "pending", "error", "offline"
    last_sync_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    sync_error: Mapped[str] = mapped_column(
        Text,
        nullable=True,
    )
