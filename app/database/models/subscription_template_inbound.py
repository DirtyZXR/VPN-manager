"""Subscription template inbound model for template-inbound relationships."""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.database.models.inbound import Inbound
    from app.database.models.subscription_template import SubscriptionTemplate


class SubscriptionTemplateInbound(Base, TimestampMixin):
    """Relationship between subscription template and inbound."""

    __tablename__ = "subscription_template_inbounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("subscription_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    inbound_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("inbounds.id", ondelete="CASCADE"),
        nullable=False,
    )
    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # For ordering inbounds

    # Relationships
    template: Mapped["SubscriptionTemplate"] = relationship("SubscriptionTemplate", back_populates="template_inbounds")
    inbound: Mapped["Inbound"] = relationship("Inbound")

    def __repr__(self) -> str:
        return f"<SubscriptionTemplateInbound(template_id={self.template_id}, inbound_id={self.inbound_id}, order={self.order})>"
