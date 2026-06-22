"""Модель открытого расхождения БД ↔ панель, ожидающего решения админа."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.database.models.server import Server


class PendingDivergence(Base, TimestampMixin):
    """Одно открытое расхождение между БД и панелью.

    Дедуплицируется по (server_id, kind, email) среди записей со статусом 'open':
    реконсайлер не плодит дубли и не спамит уведомлениями каждый цикл.
    """

    __tablename__ = "pending_divergences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("servers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    email: Mapped[str] = mapped_column(String(200), nullable=False)
    subscription_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", index=True
    )
    batch_id: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # Список [[chat_id, message_id], ...] разосланных дайджест-сообщений для правки.
    notify_message_refs: Mapped[list | None] = mapped_column(JSON, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by: Mapped[int | None] = mapped_column(Integer, nullable=True)

    server: Mapped["Server"] = relationship("Server")

    def __repr__(self) -> str:
        return (
            f"<PendingDivergence(id={self.id}, kind={self.kind!r}, "
            f"email={self.email!r}, status={self.status!r})>"
        )
