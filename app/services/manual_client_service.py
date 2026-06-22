"""Импорт/удаление созданных вручную клиентов XUI-панели.

Клиенты, заведённые на панели не ботом, бот раньше только замечал в логах. Этот
сервис даёт on-demand механизм: перечислить «неуправляемых» клиентов сервера,
импортировать их в бота (создать подписку + соединения, переиспользуя панельный
subId) или удалить с панели.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import select


@dataclass
class UnmanagedClient:
    """Клиент панели, не управляемый ботом (создан вручную)."""

    email: str
    uuid: str
    sub_id: str
    inbound_db_ids: list[int]  # известные боту inbound'ы (доступные к импорту)
    expiry_ms: int
    total_gb: int  # в ГБ (из байтов панели)
    enable: bool
    importable: bool  # есть хотя бы один inbound_db_id


class ManualClientService:
    """Детект, импорт и удаление ручных клиентов панели."""

    def __init__(self, session) -> None:
        self.session = session

    async def list_unmanaged(self, server) -> list[UnmanagedClient]:
        """Список панельных клиентов сервера, не управляемых ботом."""
        from app.database.models import XUIInboundConnection
        from app.database.models.inbound import XUIInbound
        from app.services.xui_service import XUIService

        rows = (
            await self.session.execute(
                select(XUIInboundConnection.email, XUIInboundConnection.uuid)
                .select_from(XUIInboundConnection)
                .join(XUIInbound, XUIInbound.id == XUIInboundConnection.inbound_id)
                .where(XUIInbound.server_id == server.id)
            )
        ).all()
        bot_emails = {(r[0] or "").lower() for r in rows if r[0]}
        bot_uuids = {r[1] for r in rows if r[1]}

        xui_rows = (
            await self.session.execute(
                select(XUIInbound.xui_id, XUIInbound.id).where(XUIInbound.server_id == server.id)
            )
        ).all()
        xui_to_db = {r[0]: r[1] for r in xui_rows}

        try:
            client = await XUIService(self.session)._get_client(server)
            snapshot = await client.get_clients() or []
        except Exception as e:
            logger.warning("list_unmanaged: панель сервера {} недоступна: {}", server.id, e)
            return []

        result: list[UnmanagedClient] = []
        for pc in snapshot:
            email = pc.get("email") or ""
            uuid = pc.get("id") or pc.get("uuid") or ""
            if (email.lower() in bot_emails) or (uuid and uuid in bot_uuids):
                continue  # это наш клиент
            inbound_db_ids = [
                xui_to_db[x] for x in (pc.get("inboundIds") or []) if x in xui_to_db
            ]
            result.append(
                UnmanagedClient(
                    email=email,
                    uuid=uuid,
                    sub_id=pc.get("subId") or "",
                    inbound_db_ids=inbound_db_ids,
                    expiry_ms=int(pc.get("expiryTime") or 0),
                    total_gb=int(pc.get("totalGB") or 0) // (1024**3),
                    enable=bool(pc.get("enable", True)),
                    importable=bool(inbound_db_ids),
                )
            )
        return result
