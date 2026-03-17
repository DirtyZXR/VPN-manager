"""SubscriptionGroup model for grouping user subscriptions."""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.database.models.user import User
    from app.database.models.server_subscription import ServerSubscription


class SubscriptionGroup(Base, TimestampMixin):
    """Group of subscriptions for a user (e.g., 'Main', 'Work')."""

    __tablename__ = "subscription_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="subscription_groups")
    server_subscriptions: Mapped[list["ServerSubscription"]] = relationship(
        "ServerSubscription",
        back_populates="subscription_group",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<SubscriptionGroup(id={self.id}, name='{self.name}', user_id={self.user_id})>"
