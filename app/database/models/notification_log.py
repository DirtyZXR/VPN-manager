"""NotificationLog model for tracking sent notifications."""

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, TimestampMixin


class NotificationType(str, Enum):
    """Notification type constants."""
    EXPIRY_24H = "expiry_24h"
    EXPIRY_12H = "expiry_12h"
    EXPIRY_1H = "expiry_1h"
    TRAFFIC_5GB = "traffic_5gb"

    @classmethod
    def all(cls) -> list["NotificationType"]:
        """Get all notification types."""
        return list(cls)


class NotificationLevel(str, Enum):
    """Notification level constants."""
    PROFILE = "profile"
    SUBSCRIPTION = "subscription"
    USER = "user"

    @classmethod
    def all(cls) -> list["NotificationLevel"]:
        """Get all notification levels."""
        return list(cls)


class NotificationLog(Base, TimestampMixin):
    """Log of sent notifications to prevent duplicates."""

    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    notification_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    level: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    group_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,  # Hash of grouped IDs
        index=True,
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # Relationships
    client: Mapped["Client"] = relationship("Client")

    # Composite indexes for efficient queries
    __table_args__ = (
        Index("idx_notification_logs_user_type", "user_id", "notification_type"),
        Index("idx_notification_logs_user_type_level", "user_id", "notification_type", "level"),
    )

    def __repr__(self) -> str:
        return (
            f"<NotificationLog(id={self.id}, user_id={self.user_id}, "
            f"type='{self.notification_type}', level='{self.level}')>"
        )

    @classmethod
    def should_notify(
        cls,
        user_id: int,
        notification_type: str,
        level: str,
        group_key: str,
        sent_at: datetime,
        cooldown_hours: int = 24,
    ) -> bool:
        """Check if notification should be sent.

        Args:
            user_id: User ID
            notification_type: Type of notification
            level: Level of notification
            group_key: Hash of grouped IDs
            sent_at: Current time to check from
            cooldown_hours: Minimum hours between similar notifications

        Returns:
            True if notification should be sent
        """
        from datetime import timedelta
        cutoff_time = sent_at - timedelta(hours=cooldown_hours)

        # If sent_at is more recent than cutoff, we should NOT notify
        if sent_at > cutoff_time:
            return False

        return True
