"""Server model for 3x-ui panels and VPN services."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime as SADateTime

from app.database.models.base import Base, SyncMixin, TimestampMixin

if TYPE_CHECKING:
    from app.database.models.inbound import Inbound


class Server(Base, TimestampMixin, SyncMixin):
    """Physical Server and VPN configuration."""

    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    # Network & Status
    ip_address: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_online: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0"
    )

    # 3x-ui / Main Panel connection (Legacy/Primary)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    verify_ssl: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Provider architecture
    panel_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    provider_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Custom paths for panel and subscriptions (Legacy)
    panel_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    subscription_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    subscription_json_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # SSH Access for direct management
    ssh_port: Mapped[int] = mapped_column(Integer, default=22, nullable=False, server_default="22")
    ssh_user: Mapped[str] = mapped_column(
        String(100), default="root", nullable=False, server_default="root"
    )
    ssh_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    ssh_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Session management
    session_cookies_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_created_at: Mapped[datetime | None] = mapped_column(
        SADateTime(timezone=True), nullable=True
    )

    # Relationships
    inbounds: Mapped[list["Inbound"]] = relationship(
        "Inbound",
        back_populates="server",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Server(id={self.id}, name='{self.name}', url='{self.url}')>"
