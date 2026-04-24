"""Server model for base VPN services."""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, SyncMixin, TimestampMixin

if TYPE_CHECKING:
    from app.database.models.inbound import Inbound
    from app.database.models.services import AWGService, MTProxyService, XUIPanel


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
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="1"
    )

    # SSH Access for direct management
    ssh_port: Mapped[int] = mapped_column(Integer, default=22, nullable=False, server_default="22")
    ssh_user: Mapped[str] = mapped_column(
        String(100), default="root", nullable=False, server_default="root"
    )
    ssh_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    ssh_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    inbounds: Mapped[list["Inbound"]] = relationship(
        "Inbound",
        back_populates="server",
        cascade="all, delete-orphan",
    )
    xui_panel: Mapped["XUIPanel | None"] = relationship(
        "XUIPanel",
        back_populates="server",
        uselist=False,
        cascade="all, delete-orphan",
    )
    awg_service: Mapped["AWGService | None"] = relationship(
        "AWGService",
        back_populates="server",
        uselist=False,
        cascade="all, delete-orphan",
    )
    mtproxy_service: Mapped["MTProxyService | None"] = relationship(
        "MTProxyService",
        back_populates="server",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Server(id={self.id}, name='{self.name}')>"
