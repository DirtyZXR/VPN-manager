"""Client model for VPN clients."""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.database.models.subscription import Subscription


class Client(Base, TimestampMixin):
    """VPN client (real person with Telegram)."""

    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_lower: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    telegram_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    telegram_username: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        unique=True,
    )
    telegram_username_lower: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    subscriptions: Mapped[list["Subscription"]] = relationship(
        "Subscription",
        back_populates="client",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Client(id={self.id}, name='{self.name}', email='{self.email}')>"
