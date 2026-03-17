"""Inbound model for 3x-ui inbounds."""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.database.models.server import Server
    from app.database.models.profile import Profile


class Inbound(Base, TimestampMixin):
    """Cached inbound configuration from 3x-ui."""

    __tablename__ = "inbounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("servers.id", ondelete="CASCADE"),
        nullable=False,
    )
    xui_id: Mapped[int] = mapped_column(Integer, nullable=False)
    remark: Mapped[str] = mapped_column(String(200), nullable=False)
    protocol: Mapped[str] = mapped_column(String(50), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    settings_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    server: Mapped["Server"] = relationship("Server", back_populates="inbounds")
    profiles: Mapped[list["Profile"]] = relationship(
        "Profile",
        back_populates="inbound",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Inbound(id={self.id}, remark='{self.remark}', protocol='{self.protocol}')>"
