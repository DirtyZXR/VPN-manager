"""Inbound model for VPN inbounds."""

from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, SyncMixin, TimestampMixin

if TYPE_CHECKING:
    from app.database.models.inbound_connection import InboundConnection
    from app.database.models.server import Server
    from app.database.models.subscription_template_inbound import SubscriptionTemplateInbound


class Inbound(Base, TimestampMixin, SyncMixin):
    """Base inbound configuration."""

    __tablename__ = "inbounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("servers.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    remark: Mapped[str] = mapped_column(String(200), nullable=False)
    protocol: Mapped[str] = mapped_column(String(50), nullable=False)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __mapper_args__ = {
        "polymorphic_on": "type",
        "polymorphic_identity": "inbound",
        "with_polymorphic": "*",
    }

    # Relationships
    server: Mapped["Server"] = relationship("Server", back_populates="inbounds")
    client_connections: Mapped[list["InboundConnection"]] = relationship(
        "InboundConnection",
        back_populates="inbound",
        cascade="all, delete-orphan",
    )
    template_inbounds: Mapped[list["SubscriptionTemplateInbound"]] = relationship(
        "SubscriptionTemplateInbound",
        back_populates="inbound",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(id={self.id}, remark='{self.remark}', protocol='{self.protocol}')>"


class XUIInbound(Inbound):
    """Cached inbound configuration from 3x-ui."""

    __tablename__ = "xui_inbounds"

    id: Mapped[int] = mapped_column(
        Integer, ForeignKey("inbounds.id", ondelete="CASCADE"), primary_key=True
    )

    __mapper_args__ = {
        "polymorphic_identity": "xui_inbound",
    }

    xui_id: Mapped[int] = mapped_column(Integer, nullable=False)
    settings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    client_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )  # Number of XUI clients


class AWGInbound(Inbound):
    """AmneziaWG inbound configuration."""

    __tablename__ = "awg_inbounds"

    id: Mapped[int] = mapped_column(
        Integer, ForeignKey("inbounds.id", ondelete="CASCADE"), primary_key=True
    )

    __mapper_args__ = {
        "polymorphic_identity": "awg_inbound",
    }


class MTProxyInbound(Inbound):
    """MTProxy inbound configuration."""

    __tablename__ = "mtproxy_inbounds"

    id: Mapped[int] = mapped_column(
        Integer, ForeignKey("inbounds.id", ondelete="CASCADE"), primary_key=True
    )

    __mapper_args__ = {
        "polymorphic_identity": "mtproxy_inbound",
    }
