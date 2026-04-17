"""Subscription request model for tracking user requests for templates."""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.database.models.client import Client
    from app.database.models.subscription_template import SubscriptionTemplate


class SubscriptionRequest(Base, TimestampMixin):
    """User request for a subscription template."""

    __tablename__ = "subscription_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
    )
    template_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("subscription_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    requested_name: Mapped[str] = mapped_column(
        String(100),
        nullable=True,
    )

    # Relationships
    client: Mapped["Client"] = relationship("Client")
    template: Mapped["SubscriptionTemplate"] = relationship("SubscriptionTemplate")

    def __repr__(self) -> str:
        return (
            f"<SubscriptionRequest(id={self.id}, client_id={self.client_id}, "
            f"template_id={self.template_id})>"
        )
