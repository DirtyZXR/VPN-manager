"""Server model for 3x-ui panels."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.database.models.inbound import Inbound
    from app.database.models.server_subscription import ServerSubscription


class Server(Base, TimestampMixin):
    """3x-ui panel server configuration."""

    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_sync: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    inbounds: Mapped[list["Inbound"]] = relationship(
        "Inbound",
        back_populates="server",
        cascade="all, delete-orphan",
    )
    server_subscriptions: Mapped[list["ServerSubscription"]] = relationship(
        "ServerSubscription",
        back_populates="server",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Server(id={self.id}, name='{self.name}', url='{self.url}')>"
