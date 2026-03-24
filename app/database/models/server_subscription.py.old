"""ServerSubscription model for linking subscription groups to servers."""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.database.models.server import Server
    from app.database.models.subscription_group import SubscriptionGroup
    from app.database.models.profile import Profile


class ServerSubscription(Base, TimestampMixin):
    """Link between subscription group and server with subscription token."""

    __tablename__ = "server_subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "subscription_group_id",
            "server_id",
            name="uq_subscription_group_server",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subscription_group_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("subscription_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    server_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("servers.id", ondelete="CASCADE"),
        nullable=False,
    )
    subscription_token: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
    )

    # Relationships
    subscription_group: Mapped["SubscriptionGroup"] = relationship(
        "SubscriptionGroup",
        back_populates="server_subscriptions",
    )
    server: Mapped["Server"] = relationship(
        "Server",
        back_populates="server_subscriptions",
    )
    profiles: Mapped[list["Profile"]] = relationship(
        "Profile",
        back_populates="server_subscription",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<ServerSubscription(id={self.id}, token='{self.subscription_token}')>"
