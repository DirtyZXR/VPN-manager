"""InboundConnection model for unique inbound connections."""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
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

    # Relationships
    subscription: Mapped["Subscription"] = relationship(
        "Subscription",
        back_populates="inbound_connections",
    )
    inbound: Mapped["Inbound"] = relationship("Inbound", back_populates="client_connections")

    def __repr__(self) -> str:
        return f"<InboundConnection(id={self.id}, uuid='{self.uuid}', enabled={self.is_enabled})>"
