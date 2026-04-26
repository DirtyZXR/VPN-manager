"""Subclasses for VPN Services."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime as SADateTime

from app.database.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.database.models.server import Server


class XUIPanel(Base, TimestampMixin):
    """3x-ui panel configuration."""

    __tablename__ = "xui_panels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    server: Mapped["Server"] = relationship("Server", back_populates="xui_panel")

    # 3x-ui specific connections
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    verify_ssl: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Provider architecture
    panel_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    provider_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Custom paths
    panel_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    subscription_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    subscription_json_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Installer params
    caddy_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inbound_ranges: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Session management
    session_cookies_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_created_at: Mapped[datetime | None] = mapped_column(
        SADateTime(timezone=True), nullable=True
    )


class AWGService(Base, TimestampMixin):
    """AmneziaWG service configuration."""

    __tablename__ = "awg_services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    server: Mapped["Server"] = relationship("Server", back_populates="awg_service")

    port: Mapped[int] = mapped_column(Integer, nullable=False)
    subnet_ip: Mapped[str] = mapped_column(String(50), nullable=False, default="10.8.0.1")
    subnet_cidr: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    obfuscation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    server_public_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    server_private_key: Mapped[str | None] = mapped_column(String(100), nullable=True)


class MTProxyService(Base, TimestampMixin):
    """MTProxy service configuration."""

    __tablename__ = "mtproxy_services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    server: Mapped["Server"] = relationship("Server", back_populates="mtproxy_service")

    implementation: Mapped[str] = mapped_column(String(20), nullable=False, default="mtg-multi")
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=443)
    domain: Mapped[str] = mapped_column(String(200), nullable=False, default="google.com")
    max_connections: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_secret: Mapped[str | None] = mapped_column(String(200), nullable=True)
