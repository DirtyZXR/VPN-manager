"""Profile model for VPN client profiles."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.database.models.inbound import Inbound
    from app.database.models.server_subscription import ServerSubscription


class Profile(Base, TimestampMixin):
    """VPN client profile on a specific inbound."""

    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_subscription_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("server_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    inbound_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("inbounds.id", ondelete="CASCADE"),
        nullable=False,
    )
    xui_client_id: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(200), nullable=False)
    uuid: Mapped[str] = mapped_column(String(100), nullable=False)
    total_gb: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    used_gb: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expiry_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    server_subscription: Mapped["ServerSubscription"] = relationship(
        "ServerSubscription",
        back_populates="profiles",
    )
    inbound: Mapped["Inbound"] = relationship("Inbound", back_populates="profiles")

    def __repr__(self) -> str:
        return f"<Profile(id={self.id}, email='{self.email}', uuid='{self.uuid}')>"

    @property
    def remaining_gb(self) -> int:
        """Calculate remaining traffic in GB."""
        if self.total_gb == 0:
            return -1  # Unlimited
        return max(0, self.total_gb - self.used_gb)

    @property
    def is_unlimited(self) -> bool:
        """Check if profile has unlimited traffic."""
        return self.total_gb == 0

    @property
    def is_expired(self) -> bool:
        """Check if profile has expired."""
        if self.expiry_date is None:
            return False
        return datetime.utcnow() > self.expiry_date
