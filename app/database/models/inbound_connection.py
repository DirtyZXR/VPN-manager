"""InboundConnection model for unique inbound connections."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, TimestampMixin, SyncMixin

if TYPE_CHECKING:
    from app.database.models.inbound import Inbound
    from app.database.models.subscription import Subscription


class InboundConnection(Base, TimestampMixin, SyncMixin):
    """Unique connection to an inbound (within a subscription)."""

    __tablename__ = "inbound_connections"
    __table_args__ = (
        UniqueConstraint(
            "subscription_id",
            "inbound_id",
            name="uq_subscription_inbound",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subscription_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    inbound_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("inbounds.id", ondelete="CASCADE"),
        nullable=False,
    )
    xui_client_id: Mapped[str] = mapped_column(String(100), nullable=False)  # UUID from XUI
    email: Mapped[str] = mapped_column(String(200), nullable=False)  # Email from XUI
    uuid: Mapped[str] = mapped_column(String(100), nullable=False)  # UUID from XUI
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Per-connection traffic and expiry settings (can differ per inbound)
    total_gb: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 0 = unlimited
    expiry_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    subscription: Mapped["Subscription"] = relationship(
        "Subscription",
        back_populates="inbound_connections",
    )
    inbound: Mapped["Inbound"] = relationship("Inbound", back_populates="client_connections")

    def __repr__(self) -> str:
        return f"<InboundConnection(id={self.id}, uuid='{self.uuid}', enabled={self.is_enabled})>"

    @property
    def is_unlimited(self) -> bool:
        """Check if connection has unlimited traffic."""
        return self.total_gb == 0

    @property
    def is_expired(self) -> bool:
        """Check if connection has expired."""
        if self.expiry_date is None:
            return False
        return datetime.now() > self.expiry_date

    @property
    def remaining_days(self) -> int | None:
        """Calculate remaining days until expiry."""
        if self.expiry_date is None:
            return None
        delta = self.expiry_date - datetime.now()
        return max(0, delta.days)
