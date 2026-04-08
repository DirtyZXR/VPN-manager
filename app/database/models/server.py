"""Server model for 3x-ui panels."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime as SADateTime

from app.database.models.base import Base, SyncMixin, TimestampMixin

if TYPE_CHECKING:
    from app.database.models.inbound import Inbound


class Server(Base, TimestampMixin, SyncMixin):
    """3x-ui panel server configuration."""

    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    verify_ssl: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Custom paths for panel and subscriptions
    panel_path: Mapped[str] = mapped_column(String(500), nullable=False, server_default="/")
    subscription_path: Mapped[str] = mapped_column(String(500), nullable=False, server_default="/sub/")
    subscription_json_path: Mapped[str] = mapped_column(String(500), nullable=False, server_default="/subjson/")

    # Session management
    session_cookies_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_created_at: Mapped[datetime | None] = mapped_column(SADateTime(timezone=True), nullable=True)

    # Relationships
    inbounds: Mapped[list["Inbound"]] = relationship(
        "Inbound",
        back_populates="server",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Server(id={self.id}, name='{self.name}', url='{self.url}')>"
